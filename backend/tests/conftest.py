from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

FAKE_CLI = Path(__file__).with_name("fake_cli.py")
HEADERS = {"X-Iris-Client": "web"}


@pytest.fixture
def app_client(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("test workspace\n", encoding="utf-8")

    settings = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "iris.db",
        claude_command=[sys.executable, str(FAKE_CLI)],
        max_turns=5,
        run_timeout_seconds=30,
        max_context_chars=4000,
        max_event_payload_chars=4000,
        sse_poll_seconds=0.1,
    )
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client, workspace


def create_project(client: TestClient, workspace: Path, **overrides):
    payload = {
        "name": "Test project",
        "workspace_path": str(workspace),
        "brief_md": "The project brief.",
        "allowed_tools": ["PowerShell(python *)"],
    }
    payload.update(overrides)
    response = client.post("/api/projects", headers=HEADERS, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def create_task(client: TestClient, project_id: str, title: str, goal: str):
    response = client.post(
        f"/api/projects/{project_id}/tasks",
        headers=HEADERS,
        json={"title": title, "goal_md": goal},
    )
    assert response.status_code == 200, response.text
    return response.json()


def wait_for_run(client: TestClient, run_id: str, timeout: float = 15.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] not in {"starting", "running", "canceling"}:
            return last
        time.sleep(0.05)
    raise AssertionError(f"run did not finish: {last}")
