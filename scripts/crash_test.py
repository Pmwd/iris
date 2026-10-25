r"""Manual reliability check: kill the Iris backend and verify the CLI tree dies.

Run from the repository root with the project virtual environment:

    .\.venv\Scripts\python.exe scripts\crash_test.py

This is intentionally not part of the normal test suite because it launches a
real server process and hard-kills it.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
FAKE_CLI = ROOT / "backend" / "tests" / "fake_cli.py"
PORT = 8123
HEADERS = {"X-Iris-Client": "web"}


def wait_port(port: int, timeout: float = 20) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        sock = socket.socket()
        sock.settimeout(1)
        try:
            sock.connect(("127.0.0.1", port))
            return
        except OSError:
            time.sleep(0.2)
        finally:
            sock.close()
    raise RuntimeError(f"port {port} did not open")


def pid_alive(pid: int) -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return str(pid) in (result.stdout or "")


def start_backend(data_dir: Path) -> subprocess.Popen:
    env = {
        **os_environ(),
        "IRIS_DATA_DIR": str(data_dir),
        "IRIS_CLAUDE_COMMAND_JSON": json.dumps([sys.executable, str(FAKE_CLI)]),
        "IRIS_RUN_TIMEOUT_SECONDS": "60",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--app-dir",
            "backend",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    wait_port(PORT)
    return process


def os_environ() -> dict[str, str]:
    import os

    return dict(os.environ)


def kill(process: subprocess.Popen, tree: bool = False) -> None:
    command = ["taskkill", "/PID", str(process.pid), "/F"]
    if tree:
        command.insert(3, "/T")
    subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> int:
    temp = Path(tempfile.mkdtemp(prefix="iris-crash-"))
    data_dir = temp / "data"
    workspace = temp / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("crash test\n", encoding="utf-8")
    backend = None
    restarted = None
    child_pid = None
    try:
        backend = start_backend(data_dir)
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{PORT}", headers=HEADERS, timeout=30
        )
        project = client.post(
            "/api/projects",
            json={
                "name": "Crash test",
                "workspace_path": str(workspace),
                "allowed_tools": ["PowerShell(python *)"],
            },
        ).json()
        task = client.post(
            f"/api/projects/{project['id']}/tasks",
            json={"title": "Long run", "goal_md": "SLEEP for a while"},
        ).json()
        run = client.post(
            f"/api/tasks/{task['id']}/runs",
            json={"mode": "new", "permission_profile": "execute"},
        ).json()
        run_id = run["id"]
        child_file = workspace / "fake_child.pid"
        deadline = time.time() + 15
        while time.time() < deadline and not child_file.exists():
            time.sleep(0.1)
        if not child_file.exists():
            raise RuntimeError("fake CLI did not start its child")
        child_pid = int(child_file.read_text(encoding="utf-8"))
        print(f"backend_pid={backend.pid} run_id={run_id} child_pid={child_pid}")

        # Kill only the backend, not its process tree. The Job Object should
        # close with the server and kill the CLI and its descendant.
        kill(backend)
        backend = None
        time.sleep(3)
        if pid_alive(child_pid):
            raise AssertionError("CLI descendant survived backend crash")
        print("child process gone after backend crash")

        restarted = start_backend(data_dir)
        latest = httpx.get(
            f"http://127.0.0.1:{PORT}/api/runs/{run_id}", timeout=30
        ).json()
        print(f"run_after_restart={latest['status']}")
        if latest["status"] != "interrupted":
            raise AssertionError("run was not reconciled to interrupted")
        print("backend restart reconciliation: OK")
        return 0
    finally:
        if backend is not None:
            kill(backend, tree=True)
        if restarted is not None:
            kill(restarted, tree=True)
        if child_pid is not None and pid_alive(child_pid):
            subprocess.run(
                ["taskkill", "/PID", str(child_pid), "/T", "/F"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
