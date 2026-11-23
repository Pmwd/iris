from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from tests.conftest import (
    HEADERS,
    create_session,
    create_workspace,
    send_and_wait,
    send_message,
    wait_for_summary,
    wait_for_turn,
)


def test_coding_session_requires_workspace(app_client):
    client, _ = app_client
    response = client.post(
        "/api/sessions", headers=HEADERS, json={"role": "coding"}
    )
    assert response.status_code == 422

    response = client.post(
        "/api/sessions", headers=HEADERS, json={"role": "scholar"}
    )
    assert response.status_code == 200, response.text


def test_send_message_persists_raw_and_result(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])

    turn = send_and_wait(client, session["id"], "EDIT please", profile="edit")
    assert turn["status"] == "succeeded"
    assert turn["result_text"] == "FAKE_EDIT_DONE"
    assert turn["mode"] == "new"

    messages = client.get(f"/api/sessions/{session['id']}/messages").json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[-1]["content"] == "FAKE_EDIT_DONE"

    events = client.get(f"/api/turns/{turn['id']}/events").json()
    kinds = [event["kind"] for event in events]
    for kind in ("tool.use", "tool.result", "run.result", "process.exit"):
        assert kind in kinds

    raw = client.get(f"/api/turns/{turn['id']}/raw")
    assert raw.status_code == 200
    assert "tool_use" in raw.text

    assert (workspace / "fake_output.txt").read_text(encoding="utf-8") == "FAKE_EDIT_OK"

    updated = client.get(f"/api/sessions/{session['id']}").json()
    assert updated["cli_session_id"]
    assert updated["title"] == "EDIT please"


def test_multi_turn_resume_reuses_cli_session(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])

    send_and_wait(client, session["id"], "hello", profile="edit")
    after_first = client.get(f"/api/sessions/{session['id']}").json()
    cli_session = after_first["cli_session_id"]
    assert cli_session

    second = send_and_wait(client, session["id"], "RECALL now", profile="edit")
    assert second["mode"] == "resume"
    assert second["cli_session_id"] == cli_session
    assert second["result_text"] == "FAKE_RECALL_OK"


def test_one_active_turn_per_session_and_cancel(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])

    started = send_message(client, session["id"], "SLEEP now", profile="edit")
    assert started.status_code == 200, started.text
    turn = started.json()["turn"]

    duplicate = send_message(client, session["id"], "second", profile="edit")
    assert duplicate.status_code == 409

    canceled = client.post(f"/api/turns/{turn['id']}/cancel", headers=HEADERS)
    assert canceled.status_code == 200
    finished = wait_for_turn(client, turn["id"])
    assert finished["status"] == "canceled"

    after = send_and_wait(client, session["id"], "hello after cancel", profile="edit")
    assert after["status"] == "succeeded"


def test_coding_workspace_lock(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    first = create_session(client, project_id=project["id"])
    second = create_session(client, project_id=project["id"])

    started = send_message(client, first["id"], "SLEEP now", profile="edit")
    assert started.status_code == 200
    turn = started.json()["turn"]

    blocked = send_message(client, second["id"], "hello", profile="edit")
    assert blocked.status_code == 409
    assert "workspace" in blocked.json()["detail"]

    client.post(f"/api/turns/{turn['id']}/cancel", headers=HEADERS)
    wait_for_turn(client, turn["id"])

    allowed = send_message(client, second["id"], "hello", profile="edit")
    assert allowed.status_code == 200, allowed.text
    wait_for_turn(client, allowed.json()["turn"]["id"])


def test_scholar_sessions_run_concurrently(app_client):
    client, _ = app_client
    first = create_session(client, role="scholar")
    second = create_session(client, role="scholar")

    one = send_message(client, first["id"], "SLEEP one")
    two = send_message(client, second["id"], "SLEEP two")
    assert one.status_code == 200, one.text
    assert two.status_code == 200, two.text

    for turn in (one.json()["turn"], two.json()["turn"]):
        client.post(f"/api/turns/{turn['id']}/cancel", headers=HEADERS)
        wait_for_turn(client, turn["id"])


def test_resume_failure_is_not_retried(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])

    send_and_wait(client, session["id"], "hello", profile="edit")
    failed = send_and_wait(client, session["id"], "SESSION_LOST now", profile="edit")
    assert failed["status"] == "failed"
    assert failed["mode"] == "resume"
    assert "No conversation found" in (failed["error_message"] or "")

    turns = client.get(f"/api/sessions/{session['id']}/turns").json()
    assert len(turns) == 2


def test_end_session_and_active_guard(summary_client):
    client, workspace = summary_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])
    send_and_wait(client, session["id"], "EDIT first", profile="edit")

    ended = client.post(f"/api/sessions/{session['id']}/end", headers=HEADERS)
    assert ended.status_code == 200
    assert ended.json()["status"] == "ended"
    data = wait_for_summary(client, session["id"])
    assert data["summary"]["kind"] == "final"

    active_session = create_session(client, project_id=project["id"])
    started = send_message(client, active_session["id"], "SLEEP now", profile="edit")
    assert started.status_code == 200
    blocked = client.post(
        f"/api/sessions/{active_session['id']}/end", headers=HEADERS
    )
    assert blocked.status_code == 409
    client.post(
        f"/api/turns/{started.json()['turn']['id']}/cancel", headers=HEADERS
    )
    wait_for_turn(client, started.json()["turn"]["id"])


def test_startup_reconciliation(client_factory):
    client, workspace, app = client_factory()
    repo = app.state.session_repo
    session = repo.create_session("scholar", "reconcile", None)
    turn = repo.create_turn(
        turn_id=str(uuid4()),
        session_id=session["id"],
        role="scholar",
        project_id=None,
        mode="new",
        permission_profile="read_only",
        cli_session_id=str(uuid4()),
        context_manifest={},
        raw_log_path=str(workspace / "unused.jsonl"),
    )
    assert app.state.session_manager.reconcile_interrupted_turns() == 1
    assert repo.get_turn(turn["id"])["status"] == "interrupted"


def test_delete_session_removes_raw_logs(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])
    turn = send_and_wait(client, session["id"], "hello", profile="edit")
    raw_path = Path(turn["raw_log_path"])
    assert raw_path.is_file()

    deleted = client.delete(f"/api/sessions/{session['id']}", headers=HEADERS)
    assert deleted.status_code == 200
    assert not raw_path.exists()
