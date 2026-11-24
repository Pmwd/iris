from __future__ import annotations

from tests.conftest import (
    HEADERS,
    create_session,
    create_workspace,
    send_and_wait,
)


def _fact(client, **overrides):
    payload = {
        "scope": "global",
        "role": "both",
        "kind": "preference",
        "title": "记忆",
        "content_md": "",
    }
    payload.update(overrides)
    response = client.post("/api/facts", headers=HEADERS, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_cjk_query_matches_title_bigram(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    fact = _fact(
        client,
        title="每周全身锻炼 3 次",
        content_md="偏好晚上训练，每次 30 分钟。",
    )
    session = create_session(client, project_id=project["id"])
    turn = send_and_wait(client, session["id"], "这周怎么练全身", profile="edit")
    titles = [item["title"] for item in turn["prompt_manifest"]["included_facts"]]
    assert fact["title"] in titles
    assert turn["prompt_manifest"]["selection"]["abstained"] is False
    included = turn["prompt_manifest"]["included_facts"][0]
    assert included["score"] > 0
    assert included["score_parts"]["fts"] > 0


def test_tags_and_aliases_are_searchable(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    fact = _fact(
        client,
        title="Deployment target",
        content_md="Production deploys to new.example.com.",
        aliases=["上线地址"],
        tags=["deployment", "infra"],
    )
    session = create_session(client, project_id=project["id"])
    turn = send_and_wait(client, session["id"], "deployment target", profile="edit")
    titles = [item["title"] for item in turn["prompt_manifest"]["included_facts"]]
    assert fact["title"] in titles


def test_unrelated_query_abstains_instead_of_injecting_noise(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    _fact(
        client,
        title="饮食禁忌",
        content_md="对芒果严重过敏。",
        aliases=["聚会"],
    )
    session = create_session(client, project_id=project["id"])
    turn = send_and_wait(client, session["id"], "GIL 是什么", profile="edit")
    manifest = turn["prompt_manifest"]
    assert manifest["included_facts"] == []
    assert manifest["selection"]["abstained"] is True
    assert manifest["selection"]["abstain_reason"] in {
        "no_relevant_facts",
        "below_threshold",
    }


def test_stale_facts_are_excluded(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    _fact(
        client,
        title="旧部署地址",
        content_md="旧地址 old.example.com。",
        valid_until="2000-01-01T00:00:00+00:00",
    )
    session = create_session(client, project_id=project["id"])
    turn = send_and_wait(client, session["id"], "旧部署地址是什么", profile="edit")
    manifest = turn["prompt_manifest"]
    assert manifest["included_facts"] == []
    assert any(
        item["reason"] == "stale" for item in manifest["excluded_facts"]
    )


def test_single_weak_content_term_does_not_inject(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    _fact(client, title="Zebra", content_md="alpha")
    session = create_session(client, project_id=project["id"])
    turn = send_and_wait(client, session["id"], "alpha", profile="edit")
    assert turn["prompt_manifest"]["included_facts"] == []


def test_related_endpoint_returns_reasons(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    fact = _fact(
        client,
        title="每周全身锻炼 3 次",
        content_md="偏好晚上训练。",
        aliases=["健身"],
    )
    response = client.get(
        "/api/memory/related",
        params={"q": "怎么练全身", "role": "coding", "project_id": project["id"]},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert any(item["id"] == fact["id"] for item in data["facts"])
    assert data["facts"][0]["score"] > 0
    assert data["facts"][0]["score_parts"]["fts"] >= 0
