from __future__ import annotations

from tests.conftest import (
    HEADERS,
    create_session,
    create_workspace,
    send_and_wait,
    wait_for_extraction,
    wait_for_summary,
)


def _ended_session(client, workspace, first_message: str = "EDIT deterministic tests"):
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])
    send_and_wait(client, session["id"], first_message, profile="edit")
    ended = client.post(f"/api/sessions/{session['id']}/end", headers=HEADERS)
    assert ended.status_code == 200, ended.text
    wait_for_summary(client, session["id"])
    return project, session


def test_manual_fact_crud(app_client):
    client, _ = app_client
    created = client.post(
        "/api/facts",
        headers=HEADERS,
        json={
            "scope": "global",
            "kind": "preference",
            "title": "Likes deterministic tests",
            "content_md": "Prefers reproducible tests.",
        },
    )
    assert created.status_code == 200, created.text
    fact = created.json()
    assert fact["status"] == "accepted"

    pinned = client.patch(
        f"/api/facts/{fact['id']}", headers=HEADERS, json={"pinned": True}
    )
    assert pinned.status_code == 200
    assert pinned.json()["pinned"] is True

    archived = client.delete(f"/api/facts/{fact['id']}", headers=HEADERS)
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert any(
        item["id"] == fact["id"]
        for item in client.get("/api/facts?status=archived").json()
    )

    invalid = client.post(
        "/api/facts",
        headers=HEADERS,
        json={"scope": "workspace", "title": "Bad scope"},
    )
    assert invalid.status_code == 422


def test_extraction_creates_candidates_only(app_client):
    client, workspace = app_client
    project, session = _ended_session(client, workspace)

    response = client.post(
        "/api/facts/extract",
        headers=HEADERS,
        json={"role": "coding", "project_id": project["id"]},
    )
    assert response.status_code == 200, response.text
    job = wait_for_extraction(client, response.json()["id"])
    assert job["status"] == "succeeded"
    assert job["candidate_count"] == 1

    candidates = client.get("/api/facts?status=candidate").json()
    assert len(candidates) == 1
    assert candidates[0]["title"] == "Fake durable preference"
    assert len(candidates[0]["source_session_ids"]) == 1
    assert client.get("/api/facts?status=accepted").json() == []


def test_candidate_injected_only_after_accept(app_client):
    client, workspace = app_client
    project, session = _ended_session(client, workspace)
    job = client.post(
        "/api/facts/extract",
        headers=HEADERS,
        json={"role": "coding", "project_id": project["id"]},
    ).json()
    wait_for_extraction(client, job["id"])
    candidate = client.get("/api/facts?status=candidate").json()[0]

    before = create_session(client, project_id=project["id"])
    before_turn = send_and_wait(
        client, before["id"], "deterministic tests check", profile="edit"
    )
    assert before_turn["prompt_manifest"]["included_facts"] == []

    accepted = client.patch(
        f"/api/facts/{candidate['id']}",
        headers=HEADERS,
        json={"status": "accepted"},
    )
    assert accepted.status_code == 200, accepted.text

    after = create_session(client, project_id=project["id"])
    after_turn = send_and_wait(
        client, after["id"], "deterministic tests check", profile="edit"
    )
    titles = [
        fact["title"] for fact in after_turn["prompt_manifest"]["included_facts"]
    ]
    assert "Fake durable preference" in titles

    facts = client.get("/api/facts?status=accepted").json()
    assert facts[0]["use_count"] >= 1


def test_fact_scope_and_role_filtering(app_client):
    client, workspace = app_client
    other = workspace.parent / "workspace-other"
    other.mkdir()
    project = create_workspace(client, workspace, name="One")
    project_two = create_workspace(client, other, name="Two")

    fact_response = client.post(
        "/api/facts",
        headers=HEADERS,
        json={
            "scope": "workspace",
            "project_id": project["id"],
            "role": "coding",
            "kind": "constraint",
            "title": "Alpha beta token",
            "content_md": "Alpha beta",
        },
    )
    assert fact_response.status_code == 200, fact_response.text

    other_session = create_session(client, project_id=project_two["id"])
    other_turn = send_and_wait(
        client, other_session["id"], "alpha beta", profile="edit"
    )
    assert other_turn["prompt_manifest"]["included_facts"] == []

    same_session = create_session(client, project_id=project["id"])
    same_turn = send_and_wait(
        client, same_session["id"], "alpha beta", profile="edit"
    )
    assert any(
        fact["title"] == "Alpha beta token"
        for fact in same_turn["prompt_manifest"]["included_facts"]
    )

    scholar_session = create_session(
        client, role="scholar", project_id=project["id"]
    )
    scholar_turn = send_and_wait(client, scholar_session["id"], "alpha beta")
    assert scholar_turn["prompt_manifest"]["included_facts"] == []


def test_fact_aliases_improve_recall(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    client.post(
        "/api/facts",
        headers=HEADERS,
        json={
            "scope": "global",
            "kind": "preference",
            "title": "饮食禁忌",
            "content_md": "对芒果严重过敏。",
            "aliases": ["聚会", "安全"],
        },
    )
    session = create_session(client, project_id=project["id"])
    turn = send_and_wait(client, session["id"], "聚会食物安全", profile="edit")
    titles = [fact["title"] for fact in turn["prompt_manifest"]["included_facts"]]
    assert "饮食禁忌" in titles


def test_accept_update_archives_target(client_factory):
    client, workspace, app = client_factory()
    target = client.post(
        "/api/facts",
        headers=HEADERS,
        json={
            "scope": "global",
            "kind": "insight",
            "title": "Old insight",
            "content_md": "old",
        },
    ).json()

    repo = app.state.fact_repo
    candidate = repo.create_fact(
        scope="global",
        project_id=None,
        role="both",
        kind="insight",
        status="candidate",
        title="New insight",
        content_md="new",
        supersedes_id=target["id"],
    )

    accepted = client.patch(
        f"/api/facts/{candidate['id']}",
        headers=HEADERS,
        json={"status": "accepted"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["supersedes_id"] == target["id"]
    archived = client.get("/api/facts?status=archived").json()
    assert any(item["id"] == target["id"] for item in archived)


def test_extraction_invalid_json_fails_safely(app_client):
    client, workspace = app_client
    project, session = _ended_session(
        client, workspace, first_message="EXTRACT_INVALID check"
    )
    response = client.post(
        "/api/facts/extract",
        headers=HEADERS,
        json={"role": "coding", "project_id": project["id"]},
    )
    assert response.status_code == 200, response.text
    job = wait_for_extraction(client, response.json()["id"])
    assert job["status"] == "failed"
    assert "JSON" in (job["error"] or "")
    assert client.get("/api/facts?status=candidate").json() == []


def test_extraction_requires_summary(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])
    response = client.post(
        "/api/facts/extract",
        headers=HEADERS,
        json={"session_ids": [session["id"]]},
    )
    assert response.status_code == 422


def test_concurrent_extraction_conflict(app_client):
    client, workspace = app_client
    project, session = _ended_session(
        client, workspace, first_message="SLOW_EXTRACT setup"
    )
    first = client.post(
        "/api/facts/extract",
        headers=HEADERS,
        json={"role": "coding", "project_id": project["id"]},
    )
    assert first.status_code == 200, first.text
    second = client.post(
        "/api/facts/extract",
        headers=HEADERS,
        json={"role": "coding", "project_id": project["id"]},
    )
    assert second.status_code == 409
    job = wait_for_extraction(client, first.json()["id"])
    assert job["status"] == "succeeded"


def test_extraction_existing_facts_are_scoped(client_factory, tmp_path):
    client, _workspace, app = client_factory()
    project_a = create_workspace(client, _workspace, name="Scope A")
    workspace_b = tmp_path / "scope-b"
    workspace_b.mkdir()
    project_b = create_workspace(client, workspace_b, name="Scope B")

    facts = app.state.fact_repo

    def add(scope, project_id, role, title):
        return facts.create_fact(
            scope=scope,
            project_id=project_id,
            role=role,
            kind="insight",
            status="accepted",
            title=title,
            content_md="",
        )

    global_fact = add("global", None, "both", "Global")
    a_coding = add("workspace", project_a["id"], "coding", "A coding")
    a_scholar = add("workspace", project_a["id"], "scholar", "A scholar")
    b_coding = add("workspace", project_b["id"], "coding", "B coding")

    memory = app.state.memory_manager
    scoped_ids = {
        fact["id"]
        for fact in memory._accepted_facts_for_extraction(
            "coding", project_a["id"]
        )
    }
    assert global_fact["id"] in scoped_ids
    assert a_coding["id"] in scoped_ids
    assert a_scholar["id"] not in scoped_ids
    assert b_coding["id"] not in scoped_ids

    global_ids = {
        fact["id"]
        for fact in memory._accepted_facts_for_extraction("coding", None)
    }
    assert global_fact["id"] in global_ids
    assert a_coding["id"] not in global_ids
    assert b_coding["id"] not in global_ids
