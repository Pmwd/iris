from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# app.main creates a module-level app on import. Point it at a throwaway data
# directory so importing the test suite never migrates the real data/iris.db.
os.environ.setdefault(
    "IRIS_DATA_DIR", tempfile.mkdtemp(prefix="iris-test-default-")
)

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

FAKE_CLI = Path(__file__).with_name("fake_cli.py")
HEADERS = {"X-Iris-Client": "web"}


def _make_settings(root: Path, **overrides) -> Settings:
    workspace = root / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("test workspace\n", encoding="utf-8")
    values = dict(
        data_dir=root / "data",
        db_path=root / "data" / "iris.db",
        claude_command=[sys.executable, str(FAKE_CLI)],
        max_turns=5,
        run_timeout_seconds=30,
        max_context_chars=4000,
        max_event_payload_chars=4000,
        sse_poll_seconds=0.05,
        summary_trigger_turns=1000,
        summary_trigger_chars=10_000_000,
        summary_input_max_chars=30000,
        extraction_max_sessions=8,
        extraction_input_max_chars=40000,
        fact_context_max_chars=4000,
        memory_concurrency=1,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def client_factory(tmp_path: Path):
    created: list[tuple[TestClient, Path]] = []
    counter = {"n": 0}

    def make(**overrides):
        index = counter["n"]
        counter["n"] += 1
        root = tmp_path / f"app{index}"
        root.mkdir()
        settings = _make_settings(root, **overrides)
        app = create_app(settings)
        client = TestClient(app, base_url="http://127.0.0.1")
        client.__enter__()
        created.append((client, root / "workspace"))
        return client, root / "workspace", app

    yield make
    for client, _ in created:
        try:
            client.__exit__(None, None, None)
        except Exception:
            pass


@pytest.fixture
def app_client(client_factory):
    client, workspace, app = client_factory()
    yield client, workspace


@pytest.fixture
def summary_client(client_factory):
    client, workspace, app = client_factory(
        summary_trigger_turns=2, summary_trigger_chars=100000
    )
    yield client, workspace


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def create_workspace(client: TestClient, workspace: Path, **overrides) -> dict:
    payload = {
        "name": "Test workspace",
        "workspace_path": str(workspace),
        "brief_md": "The workspace brief.",
        "allowed_tools": ["PowerShell(python *)"],
    }
    payload.update(overrides)
    response = client.post("/api/workspaces", headers=HEADERS, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def create_session(
    client: TestClient,
    *,
    role: str = "coding",
    project_id: str | None = None,
    title: str = "",
) -> dict:
    response = client.post(
        "/api/sessions",
        headers=HEADERS,
        json={"role": role, "project_id": project_id, "title": title},
    )
    assert response.status_code == 200, response.text
    return response.json()


def send_message(
    client: TestClient,
    session_id: str,
    content: str,
    *,
    profile: str | None = None,
    fact_ids: list[str] | None = None,
):
    body = {"content": content}
    if profile:
        body["permission_profile"] = profile
    if fact_ids is not None:
        body["fact_ids"] = fact_ids
    return client.post(
        f"/api/sessions/{session_id}/messages", headers=HEADERS, json=body
    )


def wait_for_turn(client: TestClient, turn_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get(f"/api/turns/{turn_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] not in {"starting", "running", "canceling"}:
            return last
        time.sleep(0.05)
    raise AssertionError(f"turn did not finish: {last}")


def send_and_wait(
    client: TestClient,
    session_id: str,
    content: str,
    *,
    profile: str | None = None,
    fact_ids: list[str] | None = None,
    timeout: float = 15.0,
) -> dict:
    response = send_message(
        client, session_id, content, profile=profile, fact_ids=fact_ids
    )
    assert response.status_code == 200, response.text
    turn = response.json()["turn"]
    return wait_for_turn(client, turn["id"], timeout=timeout)


def wait_for_summary(client: TestClient, session_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        data = client.get(f"/api/sessions/{session_id}/summary").json()
        last = data
        if data.get("active") is None and data.get("items"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"summary did not finish: {last}")


def wait_for_extraction(
    client: TestClient, extraction_id: str, timeout: float = 15.0
) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get(f"/api/fact-extractions/{extraction_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] != "running":
            return last
        time.sleep(0.05)
    raise AssertionError(f"extraction did not finish: {last}")
