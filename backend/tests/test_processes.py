from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import HEADERS, create_workspace


def _sleeping_command(workspace: Path) -> str:
    script = workspace / "runner_fixture.py"
    script.write_text(
        "import time\n"
        "print('runner ready', flush=True)\n"
        "print('second line', flush=True)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    prefix = "& " if os.name == "nt" else ""
    return f'{prefix}"{sys.executable}" "{script}"'


def _wait_for_status(
    client: TestClient,
    process_id: str,
    statuses: set[str],
    timeout: float = 15.0,
) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get(f"/api/processes/{process_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] in statuses:
            return last
        time.sleep(0.05)
    raise AssertionError(f"process did not reach {statuses}: {last}")


def _wait_for_log(
    client: TestClient, process_id: str, needle: str, timeout: float = 15.0
) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get(f"/api/processes/{process_id}/logs")
        assert response.status_code == 200, response.text
        last = response.json()
        if any(needle in line["text"] for line in last["lines"]):
            return last
        time.sleep(0.05)
    raise AssertionError(f"log line {needle!r} not found: {last}")


def test_start_logs_stop(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)

    response = client.post(
        f"/api/workspaces/{project['id']}/processes",
        headers=HEADERS,
        json={"command": _sleeping_command(workspace), "label": "demo runner"},
    )
    assert response.status_code == 200, response.text
    started = response.json()
    assert started["project_id"] == project["id"]
    assert started["label"] == "demo runner"
    assert started["pid"]
    assert started["status"] in {"running", "starting"}

    logs = _wait_for_log(client, started["id"], "second line")
    assert logs["process"]["id"] == started["id"]
    assert [line["seq"] for line in logs["lines"]] == sorted(
        line["seq"] for line in logs["lines"]
    )
    last_seq = logs["lines"][-1]["seq"]

    after = client.get(
        f"/api/processes/{started['id']}/logs", params={"after_seq": last_seq}
    )
    assert after.status_code == 200
    assert all(line["seq"] > last_seq for line in after.json()["lines"])

    listed = client.get(f"/api/workspaces/{project['id']}/processes")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [started["id"]]

    stopped = client.post(
        f"/api/processes/{started['id']}/stop", headers=HEADERS
    )
    assert stopped.status_code == 200, stopped.text
    final = _wait_for_status(client, started["id"], {"stopped", "failed"})
    assert final["status"] == "stopped"
    assert final["ended_at"]
    assert final["exit_code"] is not None or final["status"] == "stopped"

    # A second stop on a terminal process is idempotent.
    again = client.post(f"/api/processes/{started['id']}/stop", headers=HEADERS)
    assert again.status_code == 200
    assert again.json()["status"] == "stopped"


def test_start_validation_and_missing_processes(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)

    missing = client.post(
        "/api/workspaces/does-not-exist/processes",
        headers=HEADERS,
        json={"command": "echo hi"},
    )
    assert missing.status_code == 404

    blank = client.post(
        f"/api/workspaces/{project['id']}/processes",
        headers=HEADERS,
        json={"command": "   "},
    )
    assert blank.status_code == 422

    empty = client.post(
        f"/api/workspaces/{project['id']}/processes",
        headers=HEADERS,
        json={"command": ""},
    )
    assert empty.status_code == 422

    assert client.get("/api/processes/nope").status_code == 404
    assert client.get("/api/processes/nope/logs").status_code == 404
    assert (
        client.post("/api/processes/nope/stop", headers=HEADERS).status_code == 404
    )
    assert client.get("/api/workspaces/nope/processes").status_code == 404


def test_archived_workspace_cannot_start(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    archived = client.patch(
        f"/api/workspaces/{project['id']}",
        headers=HEADERS,
        json={"archived": True},
    )
    assert archived.status_code == 200, archived.text

    response = client.post(
        f"/api/workspaces/{project['id']}/processes",
        headers=HEADERS,
        json={"command": _sleeping_command(workspace)},
    )
    assert response.status_code == 409


def test_deleting_workspace_stops_processes(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    response = client.post(
        f"/api/workspaces/{project['id']}/processes",
        headers=HEADERS,
        json={"command": _sleeping_command(workspace)},
    )
    assert response.status_code == 200, response.text
    process_id = response.json()["id"]
    _wait_for_log(client, process_id, "runner ready")

    deleted = client.delete(f"/api/workspaces/{project['id']}", headers=HEADERS)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True
    _wait_for_status(client, process_id, {"stopped", "failed"})
