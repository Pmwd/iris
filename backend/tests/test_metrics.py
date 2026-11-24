from __future__ import annotations

from tests.conftest import (
    HEADERS,
    create_session,
    create_workspace,
    send_and_wait,
    wait_for_summary,
)


def test_metrics_overview_counts_and_filters(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])

    send_and_wait(client, session["id"], "hello", profile="read_only")
    send_and_wait(client, session["id"], "EDIT the project", profile="edit")
    send_and_wait(client, session["id"], "FAIL on purpose", profile="read_only")

    fact = client.post(
        "/api/facts",
        headers=HEADERS,
        json={
            "scope": "workspace",
            "project_id": project["id"],
            "role": "both",
            "kind": "preference",
            "status": "accepted",
            "title": "Pinned preference",
            "content_md": "Always use npm run build.",
            "aliases": ["build"],
            "pinned": True,
        },
    )
    assert fact.status_code == 200, fact.text
    fact_id = fact.json()["id"]

    candidate = client.post(
        "/api/facts",
        headers=HEADERS,
        json={
            "scope": "workspace",
            "project_id": project["id"],
            "role": "both",
            "kind": "insight",
            "status": "candidate",
            "title": "Pending candidate",
            "content_md": "A candidate awaiting review.",
        },
    )
    assert candidate.status_code == 200, candidate.text

    second = create_session(client, project_id=project["id"])
    send_and_wait(client, second["id"], "RECALL the preference", profile="read_only")
    ended = client.post(f"/api/sessions/{second['id']}/end", headers=HEADERS)
    assert ended.status_code == 200, ended.text
    wait_for_summary(client, second["id"])

    response = client.get(
        "/api/metrics/overview",
        params={
            "range": "24h",
            "role": "coding",
            "project_id": project["id"],
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["range"] == "24h"
    assert data["filters"] == {"role": "coding", "project_id": project["id"]}
    turns = data["turns"]
    assert turns["total"] >= 4
    assert turns["succeeded"] >= 3
    assert turns["failed"] >= 1
    assert 0 < turns["success_rate"] <= 1
    assert turns["duration_p95_seconds"] is not None
    assert data["cost"]["total_usd"] > 0
    assert data["cost"]["by_session"]
    assert data["tools"]["calls"] >= 1
    assert data["tools"]["top"][0]["name"] == "Write"
    assert data["errors"]["top"]
    assert data["memory"]["fact_candidates_pending"] >= 1
    assert any(item["id"] == fact_id for item in data["memory"]["fact_use_top"])
    assert data["memory"]["fact_injection_rate"] > 0
    assert data["memory"]["summary_coverage"] > 0
    assert data["memory"]["summary_lag"] >= 0
    assert data["storage"]["db_bytes"] > 0

    scholar = client.get(
        "/api/metrics/overview",
        params={"range": "24h", "role": "scholar", "project_id": project["id"]},
    )
    assert scholar.status_code == 200
    assert scholar.json()["turns"]["total"] == 0

    invalid = client.get("/api/metrics/overview", params={"range": "1y"})
    assert invalid.status_code == 422


def test_metrics_health_and_recent_errors(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])
    send_and_wait(client, session["id"], "FAIL for metrics", profile="read_only")

    health = client.get("/api/metrics/health")
    assert health.status_code == 200, health.text
    data = health.json()
    assert data["db_ok"] is True
    assert data["status"] == "ok"
    assert data["cli"]["installed"] is True
    assert data["turns"]["active"] == 0
    assert "queues" in data

    errors = client.get(
        "/api/metrics/errors",
        params={"role": "coding", "project_id": project["id"], "limit": 10},
    )
    assert errors.status_code == 200, errors.text
    rows = errors.json()
    assert rows
    row = rows[0]
    assert row["error_type"]
    assert len(row["error_message"]) <= 300
    assert "result_text" not in row
    assert "content" not in row


def test_metrics_empty_database(client_factory):
    client, _workspace, _app = client_factory()
    overview = client.get("/api/metrics/overview")
    assert overview.status_code == 200, overview.text
    data = overview.json()
    assert data["turns"]["total"] == 0
    assert data["turns"]["success_rate"] is None
    assert data["cost"]["total_usd"] == 0
    assert data["storage"]["db_bytes"] > 0

    health = client.get("/api/metrics/health")
    assert health.status_code == 200
    assert health.json()["turns"]["active"] == 0


def test_timeseries_rollups_and_filters(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])
    send_and_wait(client, session["id"], "hello", profile="read_only")
    send_and_wait(client, session["id"], "FAIL for timeseries", profile="read_only")

    response = client.get(
        "/api/metrics/timeseries",
        params={
            "metric": "turns",
            "range": "24h",
            "bucket": "hour",
            "role": "coding",
            "project_id": project["id"],
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["metric"] == "turns"
    assert data["bucket"] == "hour"
    assert data["points"]
    assert sum(point["value"] for point in data["points"]) >= 2

    cost = client.get(
        "/api/metrics/timeseries",
        params={
            "metric": "cost_usd",
            "range": "24h",
            "bucket": "hour",
            "project_id": project["id"],
        },
    )
    assert cost.status_code == 200
    assert sum(point["value"] for point in cost.json()["points"]) > 0

    scholar = client.get(
        "/api/metrics/timeseries",
        params={
            "metric": "turns",
            "range": "24h",
            "bucket": "hour",
            "role": "scholar",
            "project_id": project["id"],
        },
    )
    assert scholar.status_code == 200
    assert sum(point["value"] for point in scholar.json()["points"]) == 0

    assert (
        client.get(
            "/api/metrics/timeseries",
            params={"metric": "bogus", "range": "24h"},
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/metrics/timeseries",
            params={"metric": "turns", "range": "24h", "bucket": "week"},
        ).status_code
        == 422
    )


def test_dashboard_overview(app_client):
    client, workspace = app_client
    project = create_workspace(client, workspace)
    session = create_session(client, project_id=project["id"])
    send_and_wait(client, session["id"], "FAIL for dashboard", profile="read_only")

    response = client.get(
        "/api/dashboard/overview",
        params={"range": "24h", "role": "coding", "project_id": project["id"]},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["range"] == "24h"
    assert data["generated_at"]
    assert data["health"]["db_ok"] is True
    assert data["overview"]["turns"]["failed"] >= 1
    assert isinstance(data["alerts"], list)
    assert isinstance(data["recent_errors"], list)
    assert data["recent_errors"]
