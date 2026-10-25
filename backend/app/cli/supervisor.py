from __future__ import annotations

import logging
import os
import signal
import subprocess
from pathlib import Path

logger = logging.getLogger("iris.supervisor")

if os.name == "nt":
    try:
        import win32api
        import win32con
        import win32job
    except Exception:  # pragma: no cover - optional Windows dependency
        win32api = None
        win32con = None
        win32job = None
else:
    win32api = None
    win32con = None
    win32job = None


class WindowsJob:
    """Kill-on-close Job Object used as a backstop for server crashes."""

    def __init__(self) -> None:
        self.handle = None
        if os.name != "nt" or win32job is None:
            return
        try:
            handle = win32job.CreateJobObject(None, "")
            info = win32job.QueryInformationJobObject(
                handle, win32job.JobObjectExtendedLimitInformation
            )
            info["BasicLimitInformation"]["LimitFlags"] |= (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            win32job.SetInformationJobObject(
                handle,
                win32job.JobObjectExtendedLimitInformation,
                info,
            )
            self.handle = handle
        except Exception as exc:  # noqa: BLE001 - fallback is taskkill
            logger.warning("Could not create kill-on-close job object: %s", exc)
            self.handle = None

    @property
    def available(self) -> bool:
        return self.handle is not None

    def attach(self, pid: int) -> bool:
        if self.handle is None or win32api is None or win32con is None:
            return False
        process_handle = None
        try:
            process_handle = win32api.OpenProcess(
                win32con.PROCESS_ALL_ACCESS, False, pid
            )
            win32job.AssignProcessToJobObject(self.handle, process_handle)
            return True
        except Exception as exc:  # noqa: BLE001 - process may already be in a job
            logger.warning("Could not attach pid %s to job object: %s", pid, exc)
            return False
        finally:
            if process_handle is not None:
                try:
                    win32api.CloseHandle(process_handle)
                except Exception:
                    pass

    def close(self) -> None:
        if self.handle is not None:
            try:
                win32api.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None


class ProcessSupervisor:
    def __init__(self) -> None:
        self.job = WindowsJob()
        self.last_job_attach_ok = False

    def start(
        self, command: list[str], cwd: Path, stdin_text: str
    ) -> subprocess.Popen:
        kwargs: dict = {
            "cwd": str(cwd),
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(command, **kwargs)
        if self.job.available:
            self.last_job_attach_ok = self.job.attach(process.pid)
        try:
            assert process.stdin is not None
            process.stdin.write(stdin_text)
            process.stdin.close()
        except (BrokenPipeError, OSError):
            process.kill()
            raise
        return process

    def terminate(self, process: subprocess.Popen) -> bool:
        if process.poll() is not None:
            return True
        if os.name == "nt":
            try:
                result = subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                )
                if result.returncode == 0:
                    return True
            except (OSError, subprocess.SubprocessError):
                pass
            try:
                process.kill()
            except OSError:
                pass
            return False

        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            process.wait(timeout=5)
            return True
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except OSError:
                pass
            return False

    def close(self) -> None:
        self.job.close()
