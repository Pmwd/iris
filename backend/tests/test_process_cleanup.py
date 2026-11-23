from __future__ import annotations

import os
import subprocess
import sys

import pytest

from app.cli.supervisor import WindowsJob
from app.services.sdk_runner import _kill_tree

pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="Windows job objects / taskkill"
)


def _spawn_sleeper() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"]
    )


def test_windows_job_kills_process_on_close():
    process = _spawn_sleeper()
    try:
        job = WindowsJob()
        assert job.available
        assert job.attach(process.pid)
        job.close()
        process.wait(timeout=10)
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()


def test_kill_tree_terminates_process():
    process = _spawn_sleeper()
    try:
        _kill_tree(process.pid)
        process.wait(timeout=10)
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()
