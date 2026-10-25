from __future__ import annotations

import time
from pathlib import Path

from app.cli.adapter import build_command
from app.config import Settings
from app.roles import get_role

from .conftest import HEADERS, create_project, create_task


def _scholar_task(client, project_id: str, title="Research topic"):
    response = client.post(
        f"/api/projects/{project_id}/tasks",
        headers=HEADERS,
        json={
            "title": title,
            "goal_md": "Research the topic and separate facts, opinions, and hypotheses.",
            "role": "scholar",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_plan(client, task_id, allow_web=False):
    response = client.post(
        f"/api/tasks/{task_id}/research/plan",
        headers=HEADERS,
        json={"allow_web": allow_web},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _wait_job(client, job_id: str, terminal=True, timeout: float = 20.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get(f"/api/research/{job_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if not terminal or last["status"] not in {
            "planning",
            "planned",
            "running",
            "canceling",
        }:
            return last
        time.sleep(0.05)
    raise AssertionError(f"research job did not finish: {last}")


def test_scholar_plan_start_synthesis(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    task = _scholar_task(client, project["id"])
    assert task["role"] == "scholar"

    job = _create_plan(client, task["id"], allow_web=False)
    assert job["status"] == "planned"
    assert len(job["plan"]) == 2

    edited = client.patch(
        f"/api/research/{job['id']}/plan",
        headers=HEADERS,
        json={
            "questions": [
                "What are the key facts?",
                "What are competing interpretations?",
                "What remains uncertain?",
            ]
        },
    )
    assert edited.status_code == 200
    assert len(edited.json()["plan"]) == 3

    started = client.post(
        f"/api/research/{job['id']}/start", headers=HEADERS
    )
    assert started.status_code == 200, started.text
    final = _wait_job(client, job["id"], timeout=30)
    assert final["status"] == "completed", final
    assert len(final["subtasks"]) == 3
    assert all(item["status"] == "succeeded" for item in final["subtasks"])
    assert final["synthesis_note_id"]

    note = client.get(f"/api/projects/{project['id']}/notes").json()
    synthesis = next(n for n in note if n["id"] == final["synthesis_note_id"])
    assert synthesis["kind"] == "research"
    assert synthesis["status"] == "draft"
    assert "Known facts" in synthesis["content_md"]
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "needs_review"


def test_scholar_subtask_retries_transient_failure(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    task = _scholar_task(client, project["id"], "Retry research")
    job = _create_plan(client, task["id"], allow_web=False)
    client.patch(
        f"/api/research/{job['id']}/plan",
        headers=HEADERS,
        json={"questions": ["FLAKY research question"]},
    )
    started = client.post(
        f"/api/research/{job['id']}/start", headers=HEADERS
    )
    assert started.status_code == 200, started.text
    final = _wait_job(client, job["id"], timeout=30)
    assert final["status"] == "completed", final
    assert len(final["subtasks"]) == 1
    assert final["subtasks"][0]["status"] == "succeeded"
    assert final["subtasks"][0]["attempts"] == 2


def test_scholar_job_can_be_canceled(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    task = _scholar_task(client, project["id"], "Cancelable research")
    job = _create_plan(client, task["id"], allow_web=False)
    client.patch(
        f"/api/research/{job['id']}/plan",
        headers=HEADERS,
        json={"questions": ["SLEEP research question"]},
    )
    started = client.post(
        f"/api/research/{job['id']}/start", headers=HEADERS
    )
    assert started.status_code == 200, started.text
    deadline = time.time() + 10
    while time.time() < deadline:
        current = _wait_job(client, job["id"], terminal=False)
        if current["subtasks"] and current["subtasks"][0]["status"] == "running":
            break
        time.sleep(0.05)
    canceled = client.post(
        f"/api/research/{job['id']}/cancel", headers=HEADERS
    )
    assert canceled.status_code == 200, canceled.text
    final = _wait_job(client, job["id"], timeout=20)
    assert final["status"] == "canceled", final
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "canceled"


def test_scholar_role_and_research_profile():
    role = get_role("scholar")
    assert role.default_profile == "read_only"
    assert "research" in role.allowed_profiles

    settings = Settings(
        data_dir=Path("unused"),
        db_path=Path("unused") / "iris.db",
        claude_command=["claude"],
        max_turns=7,
    )
    command = build_command(
        settings,
        session_id="research-session",
        mode="new",
        profile="research",
        allowed_tools=[],
        role_instruction=get_role("scholar").system_instruction,
    )
    assert command[command.index("--tools") + 1] == (
        "Read,Glob,Grep,WebSearch,WebFetch"
    )
    allowed = command[command.index("--allowedTools") + 1]
    assert "WebSearch" in allowed and "WebFetch" in allowed
    assert "Write" not in allowed and "Edit" not in allowed
