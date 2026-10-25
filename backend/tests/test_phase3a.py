from __future__ import annotations

from app.cli.adapter import build_command
from app.config import Settings

from .conftest import HEADERS, create_project, create_task, wait_for_run


def _accept_note(client, project_id, task_id, run_id, title="Source outcome"):
    response = client.post(
        f"/api/projects/{project_id}/notes",
        headers=HEADERS,
        json={
            "title": title,
            "content_md": "The coding task result is ready for independent verification.",
            "status": "accepted",
            "task_id": task_id,
            "source_run_id": run_id,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_testing_task(client, project_id, source_task_id, title="Verify result"):
    response = client.post(
        f"/api/projects/{project_id}/tasks",
        headers=HEADERS,
        json={
            "title": title,
            "goal_md": "Independently verify the source task result and run tests.",
            "role": "testing",
            "source_task_id": source_task_id,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_roles_endpoint(app_client):
    client, _ = app_client
    roles = client.get("/api/roles").json()
    by_id = {role["id"]: role for role in roles}
    assert by_id["coding"]["default_profile"] == "edit"
    assert by_id["testing"]["default_profile"] == "verify"
    assert "execute" not in by_id["testing"]["allowed_profiles"]


def test_testing_handoff_reuses_accepted_note_and_own_session(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    coding = create_task(client, project["id"], "Implement", "EDIT the workspace")
    response = client.post(
        f"/api/tasks/{coding['id']}/runs",
        headers=HEADERS,
        json={"mode": "new", "permission_profile": "edit"},
    )
    assert response.status_code == 200, response.text
    coding_run = wait_for_run(client, response.json()["id"])
    assert coding_run["status"] == "succeeded"
    source_note = _accept_note(
        client, project["id"], coding["id"], coding_run["id"]
    )

    testing = _create_testing_task(client, project["id"], coding["id"])
    assert testing["role"] == "testing"
    assert testing["source_task_id"] == coding["id"]

    preview = client.get(f"/api/tasks/{testing['id']}/context-preview").json()
    by_id = {note["id"]: note for note in preview["notes"]}
    assert source_note["id"] in preview["selected_note_ids"]
    assert by_id[source_note["id"]]["reason"] == "handoff"

    response = client.post(
        f"/api/tasks/{testing['id']}/runs",
        headers=HEADERS,
        json={"mode": "new", "permission_profile": "verify"},
    )
    assert response.status_code == 200, response.text
    testing_run = wait_for_run(client, response.json()["id"])
    assert testing_run["status"] == "succeeded", testing_run
    assert testing_run["context_manifest"]["role"] == "testing"
    included = testing_run["context_manifest"]["included_notes"]
    assert any(note["id"] == source_note["id"] for note in included)
    assert next(
        note for note in included if note["id"] == source_note["id"]
    )["reason"] == "handoff"

    coding_after = client.get(f"/api/tasks/{coding['id']}").json()
    testing_after = client.get(f"/api/tasks/{testing['id']}").json()
    assert testing_after["current_session_id"]
    assert testing_after["current_session_id"] != coding_after["current_session_id"]


def test_testing_rejects_edit_profile(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    coding = create_task(client, project["id"], "Source", "do work")
    testing = _create_testing_task(client, project["id"], coding["id"])
    response = client.post(
        f"/api/tasks/{testing['id']}/runs",
        headers=HEADERS,
        json={"mode": "new", "permission_profile": "edit"},
    )
    assert response.status_code == 422
    assert "not allowed" in response.json()["detail"]


def test_testing_requires_source_task(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    response = client.post(
        f"/api/projects/{project['id']}/tasks",
        headers=HEADERS,
        json={
            "title": "Testing without source",
            "goal_md": "verify",
            "role": "testing",
        },
    )
    assert response.status_code == 422
    assert "source_task_id" in response.json()["detail"]


def test_verify_profile_has_no_edit_tools():
    settings = Settings(
        data_dir=__import__("pathlib").Path("unused"),
        db_path=__import__("pathlib").Path("unused") / "iris.db",
        claude_command=["claude"],
        max_turns=7,
    )
    command = build_command(
        settings,
        session_id="session-verify",
        mode="new",
        profile="verify",
        allowed_tools=["PowerShell(python *)"],
        role_instruction="You are the Testing role.",
    )
    assert command[command.index("--tools") + 1] == "Read,Glob,Grep,PowerShell"
    assert command[command.index("--permission-mode") + 1] == "dontAsk"
    allowed = command[command.index("--allowedTools") + 1]
    assert "PowerShell(python *)" in allowed
    assert "Write" not in allowed
    assert "Edit" not in allowed
    system_prompt = command[command.index("--append-system-prompt") + 1]
    assert "Testing role" in system_prompt
