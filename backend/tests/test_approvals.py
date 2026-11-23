from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from uuid import uuid4

from tests.conftest import HEADERS


def _new_turn(app, tmp_path: Path):
    repo_sessions = app.state.session_repo
    session = repo_sessions.create_session("coding", "approval", None)
    turn = repo_sessions.create_turn(
        turn_id=str(uuid4()),
        session_id=session["id"],
        role="coding",
        project_id=None,
        mode="new",
        permission_profile="edit",
        cli_session_id=None,
        context_manifest={},
        raw_log_path=str(tmp_path / "raw.jsonl"),
    )
    return session, turn


def _emitter(repo_sessions, turn_id: str):
    state = {"seq": 0}
    lock = threading.Lock()

    def emit(kind: str, payload) -> None:
        with lock:
            state["seq"] += 1
            seq = state["seq"]
        repo_sessions.add_turn_event(turn_id, seq, kind, payload)

    return emit


def _start_request(manager, session, turn, emitter, input_data=None):
    result: dict = {}
    data = input_data or {"command": "Set-Content -Path sdk-approval.txt -Value ok"}

    def run() -> None:
        async def main():
            return await manager.request(
                turn_id=turn["id"],
                session_id=session["id"],
                tool_name="PowerShell",
                input_data=data,
                context=None,
                emit=emitter,
            )

        result["value"] = asyncio.run(main())

    thread = threading.Thread(target=run)
    thread.start()
    return thread, result


def _wait_pending(manager, turn_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    last = []
    while time.time() < deadline:
        last = manager.repo.list_pending_for_turn(turn_id)
        for item in last:
            if manager.is_pending(item["id"]):
                return item
        time.sleep(0.02)
    raise AssertionError(f"approval did not become pending: {last}")


def test_approval_allow_via_api(client_factory, tmp_path):
    client, _, app = client_factory(approval_timeout_seconds=5)
    manager = app.state.approval_manager
    repo_sessions = app.state.session_repo
    session, turn = _new_turn(app, tmp_path)
    emitter = _emitter(repo_sessions, turn["id"])

    thread, result = _start_request(manager, session, turn, emitter)
    pending = _wait_pending(manager, turn["id"])
    assert pending["tool_name"] == "PowerShell"
    assert pending["input"]["command"].startswith("Set-Content")

    response = client.post(
        f"/api/approvals/{pending['id']}/decide",
        headers=HEADERS,
        json={"decision": "allow"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "allowed"
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert result["value"]["behavior"] == "allow"

    approval = manager.get(pending["id"])
    assert approval is not None
    assert approval["status"] == "allowed"
    assert approval["decided_by"] == "user"
    kinds = [
        event["kind"]
        for event in repo_sessions.list_turn_events(turn["id"])
    ]
    assert "approval.requested" in kinds
    assert "approval.decided" in kinds

    listed = client.get(f"/api/turns/{turn['id']}/approvals").json()
    assert any(item["id"] == pending["id"] for item in listed)
    fetched = client.get(f"/api/approvals/{pending['id']}")
    assert fetched.status_code == 200
    assert client.get("/api/approvals/not-found").status_code == 404

    # A decided approval cannot be decided again.
    again = client.post(
        f"/api/approvals/{pending['id']}/decide",
        headers=HEADERS,
        json={"decision": "deny"},
    )
    assert again.status_code == 409


def test_approval_deny_and_timeout(client_factory, tmp_path):
    client, _, app = client_factory(approval_timeout_seconds=5)
    manager = app.state.approval_manager
    repo_sessions = app.state.session_repo
    session, turn = _new_turn(app, tmp_path)
    emitter = _emitter(repo_sessions, turn["id"])

    thread, result = _start_request(manager, session, turn, emitter)
    pending = _wait_pending(manager, turn["id"])
    response = client.post(
        f"/api/approvals/{pending['id']}/decide",
        headers=HEADERS,
        json={"decision": "deny", "message": "no"},
    )
    assert response.status_code == 200
    thread.join(timeout=5)
    assert result["value"]["behavior"] == "deny"
    assert result["value"]["message"] == "no"
    assert manager.get(pending["id"])["status"] == "denied"

    # Timeout path: no decision arrives.
    client2, _, app2 = client_factory(approval_timeout_seconds=0.1)
    manager2 = app2.state.approval_manager
    repo_sessions2 = app2.state.session_repo
    session2, turn2 = _new_turn(app2, tmp_path)
    emitter2 = _emitter(repo_sessions2, turn2["id"])

    async def run_request():
        return await manager2.request(
            turn_id=turn2["id"],
            session_id=session2["id"],
            tool_name="PowerShell",
            input_data={"command": "Set-Content -Path timeout.txt -Value x"},
            context=None,
            emit=emitter2,
        )

    timed_out = asyncio.run(run_request())
    assert timed_out["behavior"] == "deny"
    approvals = manager2.list_for_turn(turn2["id"])
    assert approvals
    assert approvals[0]["status"] == "expired"


def test_always_allow_creates_rule_and_auto_allows(client_factory, tmp_path):
    client, _, app = client_factory(approval_timeout_seconds=5)
    manager = app.state.approval_manager
    repo_sessions = app.state.session_repo
    session, turn = _new_turn(app, tmp_path)
    emitter = _emitter(repo_sessions, turn["id"])

    thread, result = _start_request(manager, session, turn, emitter)
    pending = _wait_pending(manager, turn["id"])
    response = client.post(
        f"/api/approvals/{pending['id']}/decide",
        headers=HEADERS,
        json={"decision": "always"},
    )
    assert response.status_code == 200
    thread.join(timeout=5)
    assert result["value"]["behavior"] == "allow"
    rules = manager.repo.list_rules(session["id"], "PowerShell")
    assert any(rule["match_type"] == "prefix" for rule in rules)

    async def auto_request():
        return await manager.request(
            turn_id=turn["id"],
            session_id=session["id"],
            tool_name="PowerShell",
            input_data={"command": "Set-Content -Path another.txt -Value y"},
            context=None,
            emit=emitter,
        )

    auto = asyncio.run(auto_request())
    assert auto["behavior"] == "allow"
    assert auto.get("rule")
    auto_approvals = [
        item
        for item in manager.list_for_turn(turn["id"])
        if item["decided_by"] == "auto"
    ]
    assert auto_approvals


def test_cancel_turn_denies_pending(client_factory, tmp_path):
    _, _, app = client_factory(approval_timeout_seconds=5)
    manager = app.state.approval_manager
    repo_sessions = app.state.session_repo
    session, turn = _new_turn(app, tmp_path)
    emitter = _emitter(repo_sessions, turn["id"])

    thread, result = _start_request(manager, session, turn, emitter)
    pending = _wait_pending(manager, turn["id"])
    manager.cancel_turn(turn["id"], "canceled in test")
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert result["value"]["behavior"] == "deny"
    approval = manager.get(pending["id"])
    assert approval is not None
    assert approval["status"] == "expired"
    assert approval["decided_by"] == "system"


def test_permission_rule_matching(client_factory, tmp_path):
    _, _, app = client_factory()
    repo = app.state.approval_repo
    session_id = "session-rule-test"
    # The FK requires a real session; create one through the session repo.
    session = app.state.session_repo.create_session("coding", "rules", None)
    session_id = session["id"]

    prefix = repo.add_rule_for_input(
        session_id, "PowerShell", {"command": "npm start"}
    )
    assert prefix["match_type"] == "prefix"
    assert (
        repo.match_rule(
            session_id, "PowerShell", {"command": "npm run build"}
        )
        is not None
    )
    assert (
        repo.match_rule(session_id, "PowerShell", {"command": "git status"})
        is None
    )

    path = repo.add_rule_for_input(
        session_id, "Write", {"file_path": "C:/tmp/out.txt"}
    )
    assert path["match_type"] == "path"
    assert (
        repo.match_rule(
            session_id, "Write", {"file_path": "C:/tmp/out.txt"}
        )
        is not None
    )
    assert (
        repo.match_rule(
            session_id, "Write", {"file_path": "C:/tmp/other.txt"}
        )
        is None
    )

    exact = repo.add_rule_for_input(
        session_id, "WebSearch", {"query": "iris"}
    )
    assert exact["match_type"] == "exact"
    assert (
        repo.match_rule(session_id, "WebSearch", {"query": "iris"})
        is not None
    )
    assert (
        repo.match_rule(session_id, "WebSearch", {"query": "other"})
        is None
    )
