from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cli.supervisor import ProcessSupervisor
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.maintenance import backup_database, list_backups, restore_backup
from app.repository import Repository

from .conftest import FAKE_CLI, HEADERS, create_project, create_task, wait_for_run


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "data_dir": tmp_path / "data",
        "db_path": tmp_path / "data" / "iris.db",
        "claude_command": [sys.executable, str(FAKE_CLI)],
        "max_turns": 5,
        "run_timeout_seconds": 30,
        "max_context_chars": 4000,
        "max_event_payload_chars": 4000,
        "sse_poll_seconds": 0.1,
    }
    values.update(overrides)
    return Settings(**values)


def test_timeout_marks_run_failed(tmp_path: Path):
    workspace = tmp_path / "timeout-workspace"
    workspace.mkdir()
    settings = make_settings(tmp_path, run_timeout_seconds=1)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        project = create_project(client, workspace)
        task = create_task(client, project["id"], "Timeout", "SLEEP for a long time")
        response = client.post(
            f"/api/tasks/{task['id']}/runs",
            headers=HEADERS,
            json={"mode": "new", "permission_profile": "execute"},
        )
        assert response.status_code == 200, response.text
        run = wait_for_run(client, response.json()["id"], timeout=15)
        assert run["status"] == "failed", run
        assert run["error_type"] == "timeout", run


def test_missing_cli_marks_spawn_failed(tmp_path: Path):
    workspace = tmp_path / "missing-cli-workspace"
    workspace.mkdir()
    settings = make_settings(
        tmp_path, claude_command=["definitely-not-a-real-iris-cli"]
    )
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        project = create_project(client, workspace)
        task = create_task(client, project["id"], "Missing CLI", "do work")
        response = client.post(
            f"/api/tasks/{task['id']}/runs",
            headers=HEADERS,
            json={"mode": "new", "permission_profile": "edit"},
        )
        assert response.status_code == 200, response.text
        run = wait_for_run(client, response.json()["id"], timeout=15)
        assert run["status"] == "failed", run
        assert run["error_type"] == "cli_spawn_failed", run


def test_malformed_output_is_audited(tmp_path: Path):
    workspace = tmp_path / "malformed-workspace"
    workspace.mkdir()
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        project = create_project(client, workspace)
        task = create_task(client, project["id"], "Malformed", "MALFORMED output")
        response = client.post(
            f"/api/tasks/{task['id']}/runs",
            headers=HEADERS,
            json={"mode": "new", "permission_profile": "edit"},
        )
        run = wait_for_run(client, response.json()["id"], timeout=15)
        assert run["status"] == "succeeded", run
        assert run["result_text"] == "FAKE_MALFORMED_OK"
        events = client.get(f"/api/runs/{run['id']}/events").json()
        assert any(event["kind"] == "cli.unparsed" for event in events)


def test_backup_is_readable(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    response = client.post("/api/maintenance/backup", headers=HEADERS)
    assert response.status_code == 200, response.text
    backup = response.json()
    path = Path(backup["path"])
    assert path.is_file()
    assert path.stat().st_size > 0

    conn = sqlite3.connect(path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    finally:
        conn.close()
    assert count >= 1
    assert project["id"]

    listing = client.get("/api/maintenance/backups").json()
    assert any(item["name"] == backup["name"] for item in listing)


def test_restore_backup_roundtrip(tmp_path: Path):
    db_path = tmp_path / "data" / "iris.db"
    database = Database(db_path)
    database.init()
    repo = Repository(database)
    project = repo.create_project("Restore me", str(tmp_path), "brief")
    backup = backup_database(db_path, tmp_path / "backups")
    assert list_backups(tmp_path / "backups")[0]["name"] == backup["name"]

    repo.delete_project(project["id"])
    assert repo.get_project(project["id"]) is None

    safety = restore_backup(db_path, Path(backup["path"]))
    restored = Repository(Database(db_path))
    assert restored.get_project(project["id"]) is not None
    assert safety is not None and safety.is_file()


def test_security_warnings_headers_and_content_type(app_client):
    client, workspace = app_client
    create_project(client, workspace)
    (workspace / ".env").write_text("SECRET=not-a-real-secret\n", encoding="utf-8")
    project = client.get("/api/projects").json()[0]
    task = create_task(client, project["id"], "Warnings", "inspect")
    preview = client.get(f"/api/tasks/{task['id']}/context-preview").json()
    assert preview["security_warnings"]
    assert any(".env" in warning for warning in preview["security_warnings"])

    health = client.get("/api/health")
    assert health.headers.get("x-content-type-options") == "nosniff"
    assert health.headers.get("x-frame-options") == "DENY"
    assert "default-src 'self'" in health.headers.get("content-security-policy", "")

    bad = client.post(
        "/api/projects",
        headers={**HEADERS, "Content-Type": "text/plain"},
        content="not json",
    )
    assert bad.status_code == 415


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object test")
def test_job_object_kills_descendants_on_close(tmp_path: Path):
    win32api = pytest.importorskip("win32api")
    win32con = pytest.importorskip("win32con")
    supervisor = ProcessSupervisor()
    if not supervisor.job.available:
        pytest.skip("Job Object is unavailable")

    workspace = tmp_path / "job-workspace"
    workspace.mkdir()
    code = (
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "pathlib.Path('child.pid').write_text(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    process = None
    try:
        process = supervisor.start([sys.executable, "-c", code], workspace, "")
        if not supervisor.last_job_attach_ok:
            pytest.skip("process was already in another Windows job")
        pid_file = workspace / "child.pid"
        deadline = time.time() + 8
        while time.time() < deadline and not pid_file.exists():
            time.sleep(0.05)
        assert pid_file.exists(), "child process did not start"
        child_pid = int(pid_file.read_text(encoding="utf-8"))

        access = getattr(
            win32con,
            "PROCESS_QUERY_LIMITED_INFORMATION",
            win32con.PROCESS_QUERY_INFORMATION,
        )

        def alive(pid: int) -> bool:
            try:
                handle = win32api.OpenProcess(access, False, pid)
                win32api.CloseHandle(handle)
                return True
            except Exception:
                return False

        assert process.poll() is None
        assert alive(child_pid)
        supervisor.close()
        deadline = time.time() + 5
        while time.time() < deadline and (
            process.poll() is None or alive(child_pid)
        ):
            time.sleep(0.1)
        # Popen keeps a process handle open, so OpenProcess can still succeed
        # for the wrapper after termination; poll() is the reliable signal.
        assert process.poll() is not None, "wrapper process survived job close"
        assert not alive(child_pid), "descendant survived job close"
    finally:
        if process is not None:
            supervisor.terminate(process)
        supervisor.close()
