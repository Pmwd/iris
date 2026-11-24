from __future__ import annotations

import time

from tests.conftest import (
    HEADERS,
    create_session,
    create_workspace,
    send_and_wait,
    wait_for_summary,
)


def _wait_cli_cleared(client, session_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = client.get(f"/api/sessions/{session_id}").json()
        if not last.get("cli_session_id"):
            return last
        time.sleep(0.05)
    raise AssertionError(f"cli session was not cleared: {last}")


def test_auto_summary_after_threshold(summary_client):
    client, workspace = summary_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])

    send_and_wait(client, session["id"], "EDIT first", profile="edit")
    send_and_wait(client, session["id"], "EDIT second", profile="edit")

    data = wait_for_summary(client, session["id"])
    summary = data["summary"]
    assert summary is not None
    assert summary["status"] == "succeeded"
    assert summary["covers_through_turn_seq"] == 2
    assert "Fake session summary" in summary["content_md"]


def test_summary_failure_does_not_block(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])

    send_and_wait(client, session["id"], "SUMMARY_FAIL hello", profile="edit")
    queued = client.post(
        f"/api/sessions/{session['id']}/summary", headers=HEADERS
    )
    assert queued.status_code == 200, queued.text

    data = wait_for_summary(client, session["id"])
    assert data["items"][0]["status"] == "failed"
    assert "FAKE_SUMMARY_ERROR" in (data["items"][0]["error"] or "")

    follow_up = send_and_wait(client, session["id"], "hello again", profile="edit")
    assert follow_up["status"] == "succeeded"


def test_compact_starts_fresh_session_with_summary(summary_client):
    client, workspace = summary_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])

    send_and_wait(client, session["id"], "EDIT first", profile="edit")
    send_and_wait(client, session["id"], "EDIT second", profile="edit")
    wait_for_summary(client, session["id"])

    compacted = client.post(
        f"/api/sessions/{session['id']}/compact", headers=HEADERS
    )
    assert compacted.status_code == 200, compacted.text
    _wait_cli_cleared(client, session["id"])

    fresh = send_and_wait(client, session["id"], "hello new", profile="edit")
    assert fresh["mode"] == "new"
    assert fresh["prompt_manifest"]["summary_included"] is True

    resumed = send_and_wait(client, session["id"], "hello again", profile="edit")
    assert resumed["mode"] == "resume"
    assert resumed["prompt_manifest"]["summary_included"] is False


def test_end_triggers_final_summary(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])
    send_and_wait(client, session["id"], "EDIT first", profile="edit")

    ended = client.post(f"/api/sessions/{session['id']}/end", headers=HEADERS)
    assert ended.status_code == 200
    data = wait_for_summary(client, session["id"])
    assert data["summary"]["kind"] == "final"
    assert data["summary"]["covers_through_turn_seq"] == 1


def test_final_summary_auto_captures_candidates(client_factory):
    client, workspace, _app = client_factory(memory_auto_capture="session_end")
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])
    send_and_wait(client, session["id"], "EDIT first", profile="edit")
    ended = client.post(f"/api/sessions/{session['id']}/end", headers=HEADERS)
    assert ended.status_code == 200
    wait_for_summary(client, session["id"])

    deadline = time.time() + 20
    candidates = []
    extractions = []
    while time.time() < deadline:
        candidates = client.get("/api/facts?status=candidate").json()
        extractions = client.get("/api/fact-extractions").json()
        if candidates and any(item["status"] == "succeeded" for item in extractions):
            break
        time.sleep(0.05)
    assert candidates, "auto capture did not create candidates"
    assert candidates[0]["origin"] == "extraction"
    assert candidates[0]["extraction_id"]
    assert candidates[0]["status"] == "candidate"
    assert candidates[0]["source_session_ids"] == [session["id"]]
    assert any(item["trigger"] == "session_end" for item in extractions)
    assert client.get("/api/facts?status=accepted").json() == []


def test_auto_capture_can_be_disabled(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])
    send_and_wait(client, session["id"], "EDIT first", profile="edit")
    ended = client.post(f"/api/sessions/{session['id']}/end", headers=HEADERS)
    assert ended.status_code == 200
    wait_for_summary(client, session["id"])
    time.sleep(0.3)
    assert client.get("/api/facts?status=candidate").json() == []
