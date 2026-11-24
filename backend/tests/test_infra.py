from __future__ import annotations

import sqlite3
from pathlib import Path

from app.cli.adapter import build_command
from app.config import Settings
from app.db import Database
from app.repository import Repository
from app.services.prompts import build_turn_prompt
from app.services.sdk_runner import _disallowed_tools
from tests.conftest import (
    HEADERS,
    create_session,
    create_workspace,
    send_and_wait,
    send_message,
    wait_for_turn,
)


def _settings() -> Settings:
    return Settings(
        data_dir=Path("."),
        db_path=Path("."),
        claude_command=["claude"],
    )


def test_command_builder_flags():
    settings = _settings()
    command = build_command(
        settings, "sid", "new", "edit", [], role_instruction="ROLE"
    )
    assert "--session-id" in command
    assert "--resume" not in command
    assert "ROLE" in command
    assert "Read,Glob,Grep,Write,Edit" in command

    resumed = build_command(
        settings,
        "sid",
        "resume",
        "execute",
        ["PowerShell(python *)"],
        role_instruction="ROLE",
    )
    assert "--resume" in resumed
    allowed = resumed[resumed.index("--allowedTools") + 1]
    assert "PowerShell(python *)" in allowed

    research = build_command(settings, "sid", "new", "research", [])
    joined = " ".join(research)
    assert "WebSearch" not in joined
    assert "WebFetch" not in joined
    assert "Read,Glob,Grep" in joined

    web_settings = Settings(
        data_dir=Path("."),
        db_path=Path("."),
        claude_command=["claude"],
        scholar_web_enabled=True,
    )
    web_research = build_command(web_settings, "sid", "new", "research", [])
    web_joined = " ".join(web_research)
    assert "WebSearch" in web_joined
    assert "WebFetch" in web_joined


def test_prompt_builder_delimits_reference_data():
    fact = {
        "id": "f1",
        "scope": "global",
        "kind": "preference",
        "title": "T",
        "content_md": "C",
        "reason": "matched",
        "pinned": False,
        "updated_at": "2026-01-01T00:00:00+00:00",
        "use_count": 0,
        "aliases": [],
    }
    pack = build_turn_prompt(
        role="coding",
        session={"id": "s1"},
        workspace=None,
        fact_selection={
            "facts": [fact],
            "selected_ids": ["f1"],
            "budget_chars": 1000,
            "selection_mode": "auto",
        },
        summary_md="SUMMARY",
        user_message="USER_MESSAGE",
        max_chars=4000,
    )
    assert "REFERENCE DATA" in pack.prompt
    assert "<user_message>" in pack.prompt
    assert "USER_MESSAGE" in pack.prompt
    assert "<session_summary>" in pack.prompt
    assert "SUMMARY" in pack.prompt
    assert pack.manifest["included_facts"][0]["id"] == "f1"
    assert pack.manifest["summary_included"] is True


def test_security_headers_and_content_type(app_client):
    client, _ = app_client
    health = client.get("/api/health")
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-frame-options"] == "DENY"

    missing = client.post("/api/sessions", json={"role": "scholar"})
    assert missing.status_code == 403

    wrong_type = client.post(
        "/api/sessions",
        headers={**HEADERS, "Content-Type": "text/plain"},
        content="x",
    )
    assert wrong_type.status_code == 415


def test_backup_and_list(app_client):
    client, _ = app_client
    response = client.post("/api/maintenance/backup", headers=HEADERS)
    assert response.status_code == 200, response.text
    info = response.json()
    assert Path(info["path"]).is_file()
    backups = client.get("/api/maintenance/backups").json()
    assert any(item["name"] == info["name"] for item in backups)


def test_malformed_output_is_audited(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])
    turn = send_and_wait(client, session["id"], "MALFORMED input", profile="edit")
    assert turn["status"] == "succeeded"
    events = client.get(f"/api/turns/{turn['id']}/events").json()
    assert "cli.unparsed" in [event["kind"] for event in events]


def test_timeout_marks_turn_failed(client_factory):
    client, workspace, app = client_factory(run_timeout_seconds=1)
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])
    started = send_message(client, session["id"], "SLEEP now", profile="edit")
    assert started.status_code == 200
    turn = wait_for_turn(client, started.json()["turn"]["id"], timeout=20)
    assert turn["status"] == "failed"
    assert turn["error_type"] == "timeout"


def test_spawn_failure_marks_turn_failed(client_factory):
    client, workspace, app = client_factory(
        claude_command=["definitely-not-a-real-iris-cli"]
    )
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])
    started = send_message(client, session["id"], "hello", profile="edit")
    assert started.status_code == 200
    turn = wait_for_turn(client, started.json()["turn"]["id"])
    assert turn["status"] == "failed"
    assert turn["error_type"] == "cli_spawn_failed"


def test_schema_v9_is_non_destructive(tmp_path: Path):
    db_path = tmp_path / "iris.db"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    database = Database(db_path)
    database.init()
    repo = Repository(database)
    project = repo.create_project("Legacy", str(workspace), brief_md="b")
    repo.create_task(project["id"], "Legacy task", "goal")
    repo.create_note(project["id"], "Legacy note", "content")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA user_version = 6")
    conn.commit()
    conn.close()

    Database(db_path).init()

    conn = sqlite3.connect(db_path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "projects",
                "tasks",
                "notes",
                "sessions",
                "messages",
                "turns",
                "facts",
                "session_summaries",
                "turn_approvals",
                "permission_rules",
                "metric_rollups",
            )
        }
    finally:
        conn.close()

    assert version == 9
    for table in (
        "sessions",
        "turns",
        "messages",
        "turn_events",
        "session_summaries",
        "facts",
        "fact_extractions",
        "facts_fts",
        "turn_approvals",
        "permission_rules",
        "metric_rollups",
    ):
        assert table in tables
    assert counts["projects"] == 1
    assert counts["tasks"] == 1
    assert counts["notes"] == 1
    assert counts["sessions"] == 0
    assert counts["facts"] == 0


def test_scholar_web_toggle_in_sdk_tools():
    assert "WebSearch" in _disallowed_tools("research")
    assert "WebFetch" in _disallowed_tools("research")
    assert "PowerShell" in _disallowed_tools("research")

    enabled = _disallowed_tools("research", web_enabled=True)
    assert "WebSearch" not in enabled
    assert "WebFetch" not in enabled
    assert "PowerShell" in enabled
    assert "Write" in enabled
