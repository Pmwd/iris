from __future__ import annotations

from tests.conftest import HEADERS, create_session, create_workspace


def _remember(client, **overrides):
    payload = {
        "text": "以后都用 pnpm。",
        "title": "构建使用 pnpm",
        "scope": "global",
        "role": "both",
        "kind": "constraint",
    }
    payload.update(overrides)
    response = client.post("/api/facts/remember", headers=HEADERS, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_remember_exact_duplicate_is_idempotent(app_client):
    client, _ = app_client
    first = _remember(client)
    assert first["accepted"] is True
    second = _remember(client)
    assert second["created"] is False
    assert second["fact"]["id"] == first["fact"]["id"]
    assert len(client.get("/api/facts?status=accepted").json()) == 1


def test_remember_similar_fact_goes_to_inbox(app_client):
    client, _ = app_client
    target = _remember(client)["fact"]
    similar = _remember(
        client,
        title="构建改用 npm",
        text="团队决定改用 npm，不再使用 pnpm。",
    )
    assert similar["created"] is True
    assert similar["needs_review"] is True
    assert similar["fact"]["status"] == "candidate"
    assert similar["relation"]["target_fact_id"] == target["id"]

    inbox = client.get("/api/memory/inbox", headers=HEADERS).json()
    assert inbox["counts"]["candidates"] >= 1
    assert any(
        group["target_fact"] and group["target_fact"]["id"] == target["id"]
        for group in inbox["groups"]
    )


def test_merge_unions_sources_and_archives_candidate(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])
    target = _remember(
        client,
        scope="workspace",
        project_id=project["id"],
        source_session_id=session["id"],
        tags=["tooling"],
    )["fact"]
    candidate = _remember(
        client,
        title="构建使用 pnpm 包管理",
        text="构建时使用 pnpm。",
        scope="workspace",
        project_id=project["id"],
        source_session_id=session["id"],
    )["fact"]
    assert candidate["status"] == "candidate"

    merged = client.post(
        f"/api/facts/{candidate['id']}/merge",
        headers=HEADERS,
        json={"target_fact_id": target["id"], "mode": "merge"},
    )
    assert merged.status_code == 200, merged.text
    source = merged.json()["fact"]
    final = merged.json()["target"]
    assert source["status"] == "archived"
    assert source["merged_into_id"] == target["id"]
    assert final["status"] == "accepted"
    accepted = client.get("/api/facts?status=accepted").json()
    assert any(item["id"] == target["id"] for item in accepted)
    assert all(item["id"] != candidate["id"] for item in accepted)


def test_supersede_archives_target_and_sets_reverse_edge(app_client):
    client, _ = app_client
    target = _remember(client)["fact"]
    replacement = _remember(
        client,
        title="构建改用 npm",
        text="不再使用 pnpm，改用 npm。",
    )["fact"]
    assert replacement["status"] == "candidate"
    response = client.post(
        f"/api/facts/{replacement['id']}/merge",
        headers=HEADERS,
        json={"target_fact_id": target["id"], "mode": "supersede"},
    )
    assert response.status_code == 200, response.text
    updated_target = response.json()["target"]
    assert updated_target["status"] == "archived"
    assert updated_target["superseded_by_id"] == replacement["id"]
    accepted = client.get("/api/facts?status=accepted").json()
    assert any(item["id"] == replacement["id"] for item in accepted)


def test_relation_suggestions_do_not_cross_workspaces(app_client):
    client, workspace = app_client
    other = workspace.parent / "workspace-other"
    other.mkdir()
    project_a = create_workspace(client, workspace, name="A")
    project_b = create_workspace(client, other, name="B")
    _remember(
        client,
        scope="workspace",
        project_id=project_a["id"],
        title="构建使用 pnpm",
        text="构建使用 pnpm。",
    )
    result = _remember(
        client,
        scope="workspace",
        project_id=project_b["id"],
        title="构建改用 npm",
        text="构建改用 npm。",
    )
    assert result["needs_review"] is False
    assert result["fact"]["status"] == "accepted"


def test_confirm_and_sources(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])
    fact = _remember(
        client,
        scope="workspace",
        project_id=project["id"],
        source_session_id=session["id"],
        valid_until="2000-01-01T00:00:00+00:00",
    )["fact"]
    stale = client.get("/api/facts?status=accepted&stale=true").json()
    assert any(item["id"] == fact["id"] for item in stale)

    confirmed = client.post(
        f"/api/facts/{fact['id']}/confirm",
        headers=HEADERS,
        json={"valid_until": None},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["last_confirmed_at"]
    assert confirmed.json()["valid_until"] is None

    sources = client.get(f"/api/facts/{fact['id']}/sources").json()
    assert any(item["id"] == session["id"] for item in sources["sessions"])


def test_remember_persists_tags_origin_and_tag_filter(app_client):
    client, _ = app_client
    result = _remember(client, tags=["tooling", "pnpm"])
    fact = result["fact"]
    assert fact["origin"] == "quick_capture"
    assert fact["tags"] == ["tooling", "pnpm"]
    filtered = client.get("/api/facts?tag=tooling").json()
    assert any(item["id"] == fact["id"] for item in filtered)
