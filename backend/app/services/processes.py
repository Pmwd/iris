from __future__ import annotations

import base64
import logging
import os
import signal
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..config import Settings
from ..db import utcnow
from ..repository import Repository

logger = logging.getLogger("iris.processes")

MAX_LINES = 2000
MAX_ACTIVE_PER_WORKSPACE = 5
MAX_KEPT_PROCESSES = 60
ACTIVE_STATUSES = {"starting", "running", "stopping"}
TERMINAL_STATUSES = {"stopped", "failed"}


class ProcessError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class ManagedProcess:
    id: str
    project_id: str
    command: str
    label: str
    cwd: Path
    log_path: Path
    status: str = "starting"
    pid: int | None = None
    started_at: str = field(default_factory=utcnow)
    ended_at: str | None = None
    exit_code: int | None = None
    error: str | None = None
    seq: int = 0
    output: list[tuple[int, str]] = field(default_factory=list)
    process: subprocess.Popen | None = None
    stop_requested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "command": self.command,
            "label": self.label,
            "cwd": str(self.cwd),
            "status": self.status,
            "pid": self.pid,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_code": self.exit_code,
            "error": self.error,
            "seq": self.seq,
        }


class WorkspaceProcessManager:
    """Runs long-lived workspace commands (dev servers) outside chat turns.

    Processes are managed in memory and are stopped when Iris shuts down. Logs
    are additionally appended to data/workspace_processes/<id>.log so a crashed
    or stopped process can still be inspected.
    """

    def __init__(self, repo_projects: Repository, settings: Settings) -> None:
        self.repo_projects = repo_projects
        self.settings = settings
        self._lock = threading.Lock()
        self._processes: dict[str, ManagedProcess] = {}
        self._log_dir = settings.data_dir / "workspace_processes"
        self._log_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def list(self, project_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            records = [
                record
                for record in self._processes.values()
                if project_id is None or record.project_id == project_id
            ]
        records.sort(key=lambda record: record.started_at, reverse=True)
        return [record.to_dict() for record in records]

    def get(self, process_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._processes.get(process_id)
            return record.to_dict() if record else None

    def logs(self, process_id: str, after_seq: int = 0) -> dict[str, Any] | None:
        with self._lock:
            record = self._processes.get(process_id)
            if not record:
                return None
            lines = [
                {"seq": seq, "text": text}
                for seq, text in record.output
                if seq > after_seq
            ]
            return {"process": record.to_dict(), "lines": lines}

    def start(
        self, project_id: str, command: str, label: str = ""
    ) -> dict[str, Any]:
        command = (command or "").strip()
        if not command:
            raise ProcessError("command is required", 422)
        project = self.repo_projects.get_project(project_id)
        if not project:
            raise ProcessError("workspace not found", 404)
        if project.get("archived_at"):
            raise ProcessError("workspace is archived", 409)
        cwd = Path(project["workspace_path"]).expanduser().resolve()
        if not cwd.is_dir():
            raise ProcessError(f"workspace does not exist: {cwd}", 422)

        with self._lock:
            active = sum(
                1
                for record in self._processes.values()
                if record.project_id == project_id
                and record.status in ACTIVE_STATUSES
            )
            if active >= MAX_ACTIVE_PER_WORKSPACE:
                raise ProcessError(
                    "too many active processes in this workspace; stop one first",
                    409,
                )
            self._prune_locked()
            process_id = str(uuid4())
            record = ManagedProcess(
                id=process_id,
                project_id=project_id,
                command=command,
                label=(label or command).strip()[:120],
                cwd=cwd,
                log_path=self._log_dir / f"{process_id}.log",
            )
            self._processes[process_id] = record

        try:
            self._spawn(record)
        except Exception as exc:  # noqa: BLE001 - surfaced to the API
            logger.error("process.spawn_failed process_id=%s error=%s", record.id, exc)
            with self._lock:
                record.status = "failed"
                record.error = str(exc)[:2000]
                record.ended_at = utcnow()
                record.process = None
            raise ProcessError(f"could not start command: {exc}", 422) from exc

        logger.info(
            "process.started process_id=%s project_id=%s pid=%s",
            record.id,
            project_id,
            record.pid,
        )
        return record.to_dict()

    def stop(self, process_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._processes.get(process_id)
            if not record:
                raise ProcessError("process not found", 404)
            process = record.process
            if record.status in TERMINAL_STATUSES or process is None:
                return record.to_dict()
            record.stop_requested = True
            record.status = "stopping"
        self._terminate(process)
        logger.info("process.stop_requested process_id=%s", process_id)
        return self.get(process_id) or record.to_dict()

    def stop_for_project(self, project_id: str) -> int:
        """Stop every active process belonging to a workspace.

        Used when the workspace is deleted so a dev server cannot outlive the
        configuration that launched it.
        """
        with self._lock:
            active = [
                record.id
                for record in self._processes.values()
                if record.project_id == project_id
                and record.status in ACTIVE_STATUSES
            ]
        for process_id in active:
            try:
                self.stop(process_id)
            except ProcessError:
                logger.exception(
                    "process.stop_for_project_failed process_id=%s", process_id
                )
        return len(active)

    def shutdown(self) -> None:
        with self._lock:
            records = [
                record
                for record in self._processes.values()
                if record.process is not None
            ]
            for record in records:
                record.stop_requested = True
                record.status = "stopping"
        for record in records:
            if record.process is not None:
                try:
                    self._terminate(record.process)
                except Exception:
                    logger.exception(
                        "process.shutdown_terminate_failed process_id=%s", record.id
                    )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _prune_locked(self) -> None:
        terminal = [
            record
            for record in self._processes.values()
            if record.status in TERMINAL_STATUSES
        ]
        if len(self._processes) <= MAX_KEPT_PROCESSES:
            return
        terminal.sort(key=lambda record: record.ended_at or record.started_at)
        excess = len(self._processes) - MAX_KEPT_PROCESSES
        for record in terminal[:excess]:
            self._processes.pop(record.id, None)

    def _spawn(self, record: ManagedProcess) -> None:
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        if os.name == "nt":
            # -EncodedCommand avoids the Windows/PowerShell quoting trap: a
            # command such as `"C:\path\python.exe" script.py` otherwise gets
            # mangled by subprocess.list2cmdline's backslash-escaped quotes.
            encoded = base64.b64encode(record.command.encode("utf-16-le"))
            argv = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                encoded.decode("ascii"),
            ]
            kwargs: dict[str, Any] = {
                "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
            }
        else:
            argv = ["/bin/sh", "-c", record.command]
            kwargs = {"start_new_session": True}

        process = subprocess.Popen(
            argv,
            cwd=str(record.cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            **kwargs,
        )
        with self._lock:
            record.process = process
            record.pid = process.pid
            record.status = "running"
        thread = threading.Thread(
            target=self._reader, args=(record,), daemon=True
        )
        thread.start()

    def _reader(self, record: ManagedProcess) -> None:
        log_file = None
        try:
            try:
                log_file = open(
                    record.log_path, "a", encoding="utf-8", errors="replace"
                )
            except OSError:
                logger.exception(
                    "process.log_open_failed process_id=%s", record.id
                )
            process = record.process
            if process is None or process.stdout is None:
                return
            for line in process.stdout:
                text = line.rstrip("\r\n")
                with self._lock:
                    record.seq += 1
                    record.output.append((record.seq, text))
                    if len(record.output) > MAX_LINES:
                        record.output = record.output[-MAX_LINES:]
                if log_file is not None:
                    log_file.write(text + "\n")
                    log_file.flush()
        except Exception as exc:  # noqa: BLE001 - keep the record consistent
            logger.exception("process.reader_failed process_id=%s", record.id)
            with self._lock:
                record.error = str(exc)[:2000]
        finally:
            if log_file is not None:
                try:
                    log_file.close()
                except OSError:
                    pass
            process = record.process
            exit_code = None
            if process is not None:
                try:
                    exit_code = process.wait(timeout=5)
                except Exception:
                    exit_code = process.poll()
            with self._lock:
                record.exit_code = exit_code
                record.ended_at = utcnow()
                record.process = None
                if record.status in ACTIVE_STATUSES:
                    if record.stop_requested:
                        record.status = "stopped"
                    elif exit_code == 0:
                        record.status = "stopped"
                    else:
                        record.status = "failed"
            logger.info(
                "process.exited process_id=%s status=%s exit_code=%s",
                record.id,
                record.status,
                exit_code,
            )

    def _terminate(self, process: subprocess.Popen) -> bool:
        if process.poll() is not None:
            return True
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                )
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
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            return True
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass
            return False
