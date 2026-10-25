from __future__ import annotations

import time
from pathlib import Path

from app.cli.adapter import build_command
from app.config import Settings
from app.services.context import build_context

from .conftest import HEADERS, create_project, create_task, wait_for_run


def test_run_edit_note_and_context_reuse(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    task_a = create_task(client, project["id"], "Implement edit", "EDIT the workspace")

    response = client.post(
        f"/api/tasks/{task_a['id']}/runs",
        headers=HEADERS,
        json={"mode": "new", "permission_profile": "edit", "context_note_ids": []},
    )
    assert response.status_code == 200, response.text
    run_a = wait_for_run(client, response.json()["id"])
    assert run_a["status"] == "succeeded", run_a
    assert run_a["result_text"] == "FAKE_EDIT_DONE"
    assert (workspace / "fake_output.txt").read_text(encoding="utf-8") == "FAKE_EDIT_OK"

    events = client.get(f"/api/runs/{run_a['id']}/events").json()
    kinds = {event["kind"] for event in events}
    assert "system.init" in kinds
    assert "tool.use" in kinds
    assert "run.result" in kinds

    note_response = client.post(
        f"/api/projects/{project['id']}/notes",
        headers=HEADERS,
        json={
            "title": "Task A outcome",
            "content_md": "FAKE_CONTEXT_MARKER: the implementation lives in fake_output.txt.",
            "task_id": task_a["id"],
            "source_run_id": run_a["id"],
            "status": "accepted",
        },
    )
    assert note_response.status_code == 200, note_response.text
    note = note_response.json()

    task_b = create_task(
        client, project["id"], "Reuse context", "FAKE_CONTEXT_MARKER: continue the work"
    )
    preview = client.get(f"/api/tasks/{task_b['id']}/context-preview")
    assert preview.status_code == 200
    preview_data = preview.json()
    assert [n["id"] for n in preview_data["notes"]] == [note["id"]]
    assert preview_data["selected_note_ids"] == [note["id"]]

    response = client.post(
        f"/api/tasks/{task_b['id']}/runs",
        headers=HEADERS,
        json={
            "mode": "new",
            "permission_profile": "read_only",
            "context_note_ids": [note["id"]],
        },
    )
    assert response.status_code == 200, response.text
    run_b = wait_for_run(client, response.json()["id"])
    assert run_b["status"] == "succeeded", run_b
    assert run_b["result_text"] == "CONTEXT_SEEN"
    assert run_b["context_manifest"]["included_notes"][0]["id"] == note["id"]

    assert client.get(f"/api/tasks/{task_a['id']}").json()["status"] == "needs_review"
    assert client.get(f"/api/tasks/{task_b['id']}").json()["status"] == "needs_review"

    complete = client.post(f"/api/tasks/{task_a['id']}/complete", headers=HEADERS)
    assert complete.status_code == 200
    assert complete.json()["status"] == "done"


def test_cli_error_marks_task_failed(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    task = create_task(client, project["id"], "Fail", "FAIL deliberately")

    response = client.post(
        f"/api/tasks/{task['id']}/runs",
        headers=HEADERS,
        json={"mode": "new", "permission_profile": "edit"},
    )
    assert response.status_code == 200, response.text
    run = wait_for_run(client, response.json()["id"])
    assert run["status"] == "failed"
    assert run["error_type"] == "cli_api_error"
    assert run["error_message"] == "FAKE_API_ERROR"
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "failed"


def test_cancel_then_resume_session(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    task = create_task(client, project["id"], "Long task", "SLEEP for a while")

    response = client.post(
        f"/api/tasks/{task['id']}/runs",
        headers=HEADERS,
        json={"mode": "new", "permission_profile": "execute"},
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["id"]

    deadline = time.time() + 10
    while time.time() < deadline:
        if (workspace / "fake_child.pid").exists():
            break
        time.sleep(0.05)
    assert (workspace / "fake_child.pid").exists(), "fake CLI child did not start"

    cancel = client.post(f"/api/runs/{run_id}/cancel", headers=HEADERS)
    assert cancel.status_code == 200, cancel.text
    canceled = wait_for_run(client, run_id)
    assert canceled["status"] == "canceled"
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "canceled"

    update = client.patch(
        f"/api/tasks/{task['id']}",
        headers=HEADERS,
        json={"goal_md": "RECALL the previous session"},
    )
    assert update.status_code == 200

    resumed_response = client.post(
        f"/api/tasks/{task['id']}/runs",
        headers=HEADERS,
        json={"mode": "resume", "permission_profile": "read_only"},
    )
    assert resumed_response.status_code == 200, resumed_response.text
    resumed = wait_for_run(client, resumed_response.json()["id"])
    assert resumed["status"] == "succeeded", resumed
    assert resumed["result_text"] == "FAKE_RECALL_OK"
    assert resumed["cli_session_id"] == canceled["cli_session_id"]


def test_execute_requires_allowed_tools(app_client):
    client, workspace = app_client
    project = create_project(client, workspace, allowed_tools=[])
    task = create_task(client, project["id"], "Execute", "do work")

    response = client.post(
        f"/api/tasks/{task['id']}/runs",
        headers=HEADERS,
        json={"mode": "new", "permission_profile": "execute"},
    )
    assert response.status_code == 422
    assert "allowed PowerShell" in response.json()["detail"]


def test_local_api_requires_client_header(app_client):
    client, workspace = app_client
    response = client.post(
        "/api/projects",
        json={"name": "No header", "workspace_path": str(workspace)},
    )
    assert response.status_code == 403


def test_command_builder_flags():
    settings = Settings(
        data_dir=Path("unused"),
        db_path=Path("unused") / "iris.db",
        claude_command=["claude"],
        max_turns=7,
    )
    command = build_command(
        settings,
        session_id="session-1",
        mode="new",
        profile="execute",
        allowed_tools=["PowerShell(python *)"],
    )
    assert "--safe-mode" in command
    assert "--output-format" in command
    assert command[command.index("--output-format") + 1] == "stream-json"
    assert command[command.index("--tools") + 1] == "Read,Glob,Grep,Write,Edit,PowerShell"
    assert command[command.index("--permission-mode") + 1] == "dontAsk"
    assert command[command.index("--session-id") + 1] == "session-1"
    allowed = command[command.index("--allowedTools") + 1]
    assert "PowerShell(python *)" in allowed

    resume = build_command(
        settings,
        session_id="session-2",
        mode="resume",
        profile="read_only",
        allowed_tools=[],
    )
    assert resume[resume.index("--resume") + 1] == "session-2"
    assert resume[resume.index("--tools") + 1] == "Read,Glob,Grep"


def test_startup_reconciliation_marks_interrupted(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    task = create_task(client, project["id"], "Interrupted", "was running")
    repo = client.app.state.repo
    run = repo.create_run(
        task_id=task["id"],
        session_id="session-interrupted",
        permission_profile="edit",
        workspace_path=str(workspace),
        context_manifest={},
        prompt_version="test",
    )
    count = repo.reconcile_interrupted_runs()
    assert count >= 1
    assert repo.get_run(run["id"])["status"] == "interrupted"
    assert repo.get_task(task["id"])["status"] == "interrupted"


def test_context_builder_records_manifest():
    project = {
        "workspace_path": "C:/workspace",
        "brief_md": "A brief",
    }
    task = {"title": "Task", "goal_md": "Goal"}
    notes = [
        {
            "id": "note-1",
            "title": "Outcome",
            "content_md": "Use the existing module.",
            "status": "accepted",
            "updated_at": "now",
        }
    ]
    pack = build_context(project, task, notes, ["note-1"], 4000)
    assert "Use the existing module." in pack.prompt
    assert pack.manifest["included_notes"][0]["id"] == "note-1"
    assert pack.manifest["total_chars"] == len(pack.prompt)
