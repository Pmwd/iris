from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..cli.adapter import build_command, normalize_event
from ..cli.supervisor import ProcessSupervisor
from ..config import Settings
from ..repository import Repository
from ..repository_facts import FactRepository
from ..repository_sessions import SessionRepository
from ..roles import ROLES, get_role
from .facts import FactSelectionError, select_facts
from .prompts import build_turn_prompt

logger = logging.getLogger("iris.sessions")

ACTIVE_STATUSES = {"starting", "running", "canceling"}
MAX_RESULT_CHARS = 2_000_000


class TurnError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _cap(text: str | None, limit: int = MAX_RESULT_CHARS) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[:limit] + "\n...[result truncated by Iris]"


class SessionManager:
    def __init__(
        self,
        repo_projects: Repository,
        repo_sessions: SessionRepository,
        repo_facts: FactRepository,
        settings: Settings,
    ) -> None:
        self.repo_projects = repo_projects
        self.repo_sessions = repo_sessions
        self.repo_facts = repo_facts
        self.settings = settings
        self.memory: Any = None  # set after construction to avoid a cycle
        self.supervisor = ProcessSupervisor()
        self._lock = threading.Lock()
        self._processes: dict[str, Any] = {}
        self._cancel_reasons: dict[str, str] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._shutting_down = False
        self._scholar_workspace = settings.data_dir / "scholar-workspace"

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def create_session(
        self, role_id: str, title: str = "", project_id: str | None = None
    ) -> dict[str, Any]:
        if role_id not in ROLES:
            raise TurnError(f"unknown role: {role_id}", 422)
        role = get_role(role_id)
        project = None
        if project_id:
            project = self.repo_projects.get_project(project_id)
            if not project:
                raise TurnError("workspace not found", 404)
            if project.get("archived_at"):
                raise TurnError("workspace is archived", 409)
        if role.requires_workspace and not project:
            raise TurnError("Coding sessions require a workspace", 422)
        clean_title = (title or "").strip() or "新会话"
        return self.repo_sessions.create_session(role.id, clean_title, project_id)

    def end_session(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self.repo_sessions.get_session(session_id)
            if not session:
                raise TurnError("session not found", 404)
            if self.repo_sessions.active_turn_for_session(session_id):
                raise TurnError("cannot end a session with an active turn", 409)
            updated = self.repo_sessions.update_session(
                session_id, {"status": "ended"}
            )
        if self.memory is not None:
            try:
                self.memory.request_summary(session_id, "final")
            except Exception:
                logger.exception("memory.final_summary_failed session_id=%s", session_id)
        assert updated is not None
        return updated

    def compact_session(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self.repo_sessions.get_session(session_id)
            if not session:
                raise TurnError("session not found", 404)
            if self.repo_sessions.active_turn_for_session(session_id):
                raise TurnError("cannot compact while a turn is active", 409)
        if self.memory is None:
            self.repo_sessions.clear_session_cli(session_id)
            return {
                "queued": True,
                "session": self.repo_sessions.get_session(session_id) or session,
            }
        # The CLI session is cleared only after the compact summary succeeds.
        outcome = self.memory.request_summary(session_id, "compact")
        return {
            "queued": bool(outcome.get("queued")),
            "session": self.repo_sessions.get_session(session_id) or session,
        }

    # ------------------------------------------------------------------
    # Turns
    # ------------------------------------------------------------------
    def send_message(
        self,
        session_id: str,
        content: str,
        *,
        permission_profile: str | None = None,
        fact_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        content = content.strip()
        if not content:
            raise TurnError("message content is empty", 422)

        with self._lock:
            session = self.repo_sessions.get_session(session_id)
            if not session:
                raise TurnError("session not found", 404)
            if session["status"] != "active":
                raise TurnError("session is not active", 409)
            role = get_role(session["role"])
            profile = permission_profile or role.default_profile
            if profile not in role.allowed_profiles:
                raise TurnError(
                    f"permission profile '{profile}' is not allowed for the "
                    f"{role.name} role",
                    422,
                )
            if self.repo_sessions.active_turn_for_session(session_id):
                raise TurnError("another turn is active in this session", 409)

            project = None
            if session.get("project_id"):
                project = self.repo_projects.get_project(session["project_id"])
                if not project:
                    raise TurnError("workspace not found", 422)
                if project.get("archived_at"):
                    raise TurnError("workspace is archived", 409)
            if role.requires_workspace and not project:
                raise TurnError("this role requires a workspace", 422)
            if role.id == "coding" and project:
                if self.repo_sessions.active_coding_turn_for_project(project["id"]):
                    raise TurnError(
                        "another coding turn is active in this workspace", 409
                    )
            if profile == "execute" and not (project and project.get("allowed_tools")):
                raise TurnError(
                    "execute profile requires at least one allowed PowerShell pattern",
                    422,
                )

            if project:
                workspace = Path(project["workspace_path"]).expanduser().resolve()
                if not workspace.is_dir():
                    raise TurnError(f"workspace does not exist: {workspace}", 422)
            else:
                workspace = self._scholar_workspace
                workspace.mkdir(parents=True, exist_ok=True)

            mode = "resume" if session.get("cli_session_id") else "new"
            cli_session_id = session.get("cli_session_id") or str(uuid4())
            summary = (
                self.repo_sessions.latest_summary(session_id, "succeeded")
                if mode == "new"
                else None
            )
            try:
                selection = select_facts(
                    self.repo_facts,
                    role=role.id,
                    project_id=session.get("project_id"),
                    query=content,
                    budget_chars=self.settings.fact_context_max_chars,
                    explicit_ids=fact_ids,
                )
            except FactSelectionError as exc:
                raise TurnError(exc.message, exc.status_code) from exc

            pack = build_turn_prompt(
                role=role.id,
                session=session,
                workspace=project,
                fact_selection=selection,
                summary_md=(summary or {}).get("content_md") if summary else None,
                user_message=content,
                max_chars=self.settings.max_context_chars,
            )
            pack.manifest["mode"] = mode

            if session.get("title") in {"", "新会话"}:
                title = content.splitlines()[0].strip()[:40] or "新会话"
                self.repo_sessions.update_session(session_id, {"title": title})

            turn_id = str(uuid4())
            log_dir = self.settings.data_dir / "session_logs" / session_id
            log_dir.mkdir(parents=True, exist_ok=True)
            raw_log_path = log_dir / f"{turn_id}.jsonl"
            try:
                turn = self.repo_sessions.create_turn(
                    turn_id=turn_id,
                    session_id=session_id,
                    role=role.id,
                    project_id=session.get("project_id"),
                    mode=mode,
                    permission_profile=profile,
                    cli_session_id=cli_session_id,
                    context_manifest=pack.manifest,
                    raw_log_path=str(raw_log_path),
                )
            except sqlite3.IntegrityError as exc:
                raise TurnError(
                    "another turn became active for this session or workspace", 409
                ) from exc

            user_message = self.repo_sessions.add_message(
                session_id=session_id,
                role="user",
                kind="text",
                content=content,
                turn_id=turn_id,
            )
            try:
                self.repo_facts.mark_facts_used(selection["selected_ids"])
            except Exception:
                logger.exception("facts.mark_used_failed turn_id=%s", turn_id)

            command = build_command(
                self.settings,
                cli_session_id,
                mode,
                profile,
                list(project.get("allowed_tools") or []) if project else [],
                role_instruction=role.system_instruction,
            )
            thread = threading.Thread(
                target=self._monitor,
                args=(
                    turn_id,
                    session_id,
                    command,
                    workspace,
                    pack.prompt,
                    raw_log_path,
                    cli_session_id,
                ),
                daemon=True,
            )
            self._threads[turn_id] = thread
            thread.start()
            logger.info(
                "turn.started turn_id=%s session_id=%s role=%s profile=%s mode=%s",
                turn_id,
                session_id,
                role.id,
                profile,
                mode,
            )
            return {
                "turn": self.repo_sessions.get_turn(turn_id) or turn,
                "user_message": user_message,
            }

    def cancel_turn(self, turn_id: str) -> dict[str, Any]:
        turn = self.repo_sessions.get_turn(turn_id)
        if not turn:
            raise TurnError("turn not found", 404)
        if turn["status"] not in ACTIVE_STATUSES:
            raise TurnError("turn is not active", 409)

        with self._lock:
            process = self._processes.get(turn_id)
            self._cancel_reasons[turn_id] = "user"
            self.repo_sessions.set_turn_canceling(turn_id)
        logger.info("turn.cancel_requested turn_id=%s", turn_id)

        if process is None:
            self.repo_sessions.finish_turn(
                turn_id,
                turn["session_id"],
                "canceled",
                error_type="canceled",
                error_message="Turn was canceled by the user.",
                add_result_message=False,
            )
        else:
            self.supervisor.terminate(process)
        return self.repo_sessions.get_turn(turn_id) or turn

    def shutdown(self) -> None:
        self._shutting_down = True
        with self._lock:
            active = list(self._processes.items())
            for turn_id, _ in active:
                self._cancel_reasons[turn_id] = "shutdown"
            threads = list(self._threads.values())
        if active:
            logger.info("iris.shutdown active_turns=%s", len(active))
        for _, process in active:
            self.supervisor.terminate(process)
        for thread in threads:
            thread.join(timeout=3)
        self.supervisor.close()

    def reconcile_interrupted_turns(self) -> int:
        return self.repo_sessions.reconcile_interrupted_turns()

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------
    def _monitor(
        self,
        turn_id: str,
        session_id: str,
        command: list[str],
        workspace: Path,
        prompt: str,
        raw_log_path: Path,
        planned_cli_session_id: str,
    ) -> None:
        seq = 0
        finished = False
        process = None
        timer: threading.Timer | None = None
        stderr_thread: threading.Thread | None = None
        stderr_lines: list[str] = []
        raw_file = None

        try:
            process = self.supervisor.start(command, workspace, prompt)
        except Exception as exc:  # noqa: BLE001 - surfaced as a turn error
            logger.error("turn.spawn_failed turn_id=%s error=%s", turn_id, exc)
            self.repo_sessions.finish_turn(
                turn_id,
                session_id,
                "failed",
                error_type="cli_spawn_failed",
                error_message=str(exc)[:4000],
                add_result_message=False,
            )
            self._cleanup(turn_id)
            return

        with self._lock:
            self._processes[turn_id] = process

        self.repo_sessions.set_turn_running(turn_id, process.pid)
        timer = threading.Timer(
            self.settings.run_timeout_seconds,
            self._on_timeout,
            args=(turn_id,),
        )
        timer.daemon = True
        timer.start()
        with self._lock:
            self._timers[turn_id] = timer

        def read_stderr() -> None:
            try:
                for line in process.stderr:
                    if line.strip() and len(stderr_lines) < 50:
                        stderr_lines.append(line.rstrip())
            except Exception:
                pass

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()

        try:
            try:
                raw_file = open(raw_log_path, "a", encoding="utf-8", errors="replace")
            except OSError:
                logger.exception("turn.raw_log_open_failed turn_id=%s", turn_id)
                raw_file = None

            for raw_line in process.stdout:
                if raw_file is not None:
                    raw_file.write(
                        raw_line if raw_line.endswith("\n") else raw_line + "\n"
                    )
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    seq += 1
                    self.repo_sessions.add_turn_event(
                        turn_id,
                        seq,
                        "cli.unparsed",
                        {"text": line[: self.settings.max_event_payload_chars]},
                        truncated=True,
                    )
                    continue

                for kind, payload, truncated in normalize_event(
                    event, self.settings.max_event_payload_chars
                ):
                    seq += 1
                    self.repo_sessions.add_turn_event(
                        turn_id, seq, kind, payload, truncated
                    )
                    if kind == "run.result":
                        finished = True
                        self._finish_from_result(
                            turn_id,
                            session_id,
                            payload,
                            planned_cli_session_id,
                        )
                        for denial in payload.get("permission_denials") or []:
                            seq += 1
                            self.repo_sessions.add_turn_event(
                                turn_id, seq, "permission.denied", denial
                            )
        except Exception as exc:  # noqa: BLE001 - keep turn state consistent
            logger.exception("turn.monitor_failed turn_id=%s", turn_id)
            if not finished:
                finished = True
                self.repo_sessions.finish_turn(
                    turn_id,
                    session_id,
                    "failed",
                    error_type="cli_monitor_failed",
                    error_message=str(exc)[:4000],
                    add_result_message=False,
                )
        finally:
            if raw_file is not None:
                try:
                    raw_file.close()
                except OSError:
                    pass
            try:
                process.wait(timeout=10)
            except Exception:
                self.supervisor.terminate(process)
            if timer is not None:
                timer.cancel()
            if stderr_thread is not None:
                stderr_thread.join(timeout=2)

            exit_code = process.returncode
            if stderr_lines:
                seq += 1
                self.repo_sessions.add_turn_event(
                    turn_id,
                    seq,
                    "cli.stderr",
                    {"lines": stderr_lines},
                    truncated=len(stderr_lines) >= 50,
                )
            seq += 1
            self.repo_sessions.add_turn_event(
                turn_id, seq, "process.exit", {"exit_code": exit_code}
            )

            current = self.repo_sessions.get_turn(turn_id)
            if current and current["status"] in ACTIVE_STATUSES:
                reason = self._cancel_reasons.get(turn_id)
                logger.info(
                    "turn.ended_without_result turn_id=%s reason=%s exit_code=%s",
                    turn_id,
                    reason or "none",
                    exit_code,
                )
                if self._shutting_down:
                    self.repo_sessions.finish_turn(
                        turn_id,
                        session_id,
                        "interrupted",
                        exit_code=exit_code,
                        error_type="service_stopped",
                        error_message="Iris stopped while the turn was active.",
                        add_result_message=False,
                    )
                elif reason == "timeout":
                    self.repo_sessions.finish_turn(
                        turn_id,
                        session_id,
                        "failed",
                        exit_code=exit_code,
                        error_type="timeout",
                        error_message="Turn exceeded the configured time limit.",
                        add_result_message=False,
                    )
                elif reason == "user":
                    self.repo_sessions.finish_turn(
                        turn_id,
                        session_id,
                        "canceled",
                        exit_code=exit_code,
                        error_type="canceled",
                        error_message="Turn was canceled by the user.",
                        add_result_message=False,
                    )
                else:
                    message = "\n".join(stderr_lines).strip()
                    self.repo_sessions.finish_turn(
                        turn_id,
                        session_id,
                        "failed",
                        exit_code=exit_code,
                        error_type=(
                            "cli_nonzero_exit" if exit_code else "cli_no_result"
                        ),
                        error_message=(
                            message[:4000]
                            if message
                            else "The CLI exited without a result event."
                        ),
                        add_result_message=False,
                    )
            else:
                self.repo_sessions.set_turn_exit_code(turn_id, exit_code)

            if finished and current and current["status"] == "succeeded":
                self._notify_success(session_id)
            self._cleanup(turn_id)

    def _finish_from_result(
        self,
        turn_id: str,
        session_id: str,
        payload: dict[str, Any],
        planned_cli_session_id: str,
    ) -> str:
        current = self.repo_sessions.get_turn(turn_id)
        if current and current["status"] not in ACTIVE_STATUSES:
            return current["status"]

        terminal_reason = payload.get("terminal_reason")
        subtype = payload.get("subtype")
        is_error = bool(payload.get("is_error"))
        result_text = _cap(payload.get("result"))
        result_session_id = payload.get("session_id") or planned_cli_session_id
        cost = payload.get("total_cost_usd")
        usage = payload.get("usage")
        failed = (
            is_error
            or terminal_reason in {"api_error", "error"}
            or (subtype is not None and subtype != "success")
        )
        if failed:
            error_type = (
                "cli_api_error" if payload.get("api_error_status") else "cli_error"
            )
            error_message = (
                result_text
                or f"CLI terminated with {terminal_reason or subtype or 'an error'}"
            )
            logger.warning(
                "turn.failed turn_id=%s error_type=%s terminal=%s",
                turn_id,
                error_type,
                terminal_reason or subtype,
            )
            self.repo_sessions.finish_turn(
                turn_id,
                session_id,
                "failed",
                result_text=result_text,
                cli_session_id=result_session_id,
                cost_usd=cost,
                usage=usage,
                error_type=error_type,
                error_message=str(error_message)[:4000],
                add_result_message=False,
            )
            return "failed"

        logger.info("turn.succeeded turn_id=%s cost=%s", turn_id, cost)
        self.repo_sessions.finish_turn(
            turn_id,
            session_id,
            "succeeded",
            result_text=result_text,
            cli_session_id=result_session_id,
            cost_usd=cost,
            usage=usage,
        )
        return "succeeded"

    def _notify_success(self, session_id: str) -> None:
        if self.memory is None:
            return
        try:
            self.memory.notify_turn_completed(session_id)
        except Exception:
            logger.exception("memory.notify_failed session_id=%s", session_id)

    def _on_timeout(self, turn_id: str) -> None:
        with self._lock:
            process = self._processes.get(turn_id)
            if process is None:
                return
            self._cancel_reasons[turn_id] = "timeout"
            self.repo_sessions.set_turn_canceling(turn_id)
        logger.warning("turn.timeout turn_id=%s", turn_id)
        self.supervisor.terminate(process)

    def _cleanup(self, turn_id: str) -> None:
        with self._lock:
            self._processes.pop(turn_id, None)
            timer = self._timers.pop(turn_id, None)
            self._cancel_reasons.pop(turn_id, None)
            self._threads.pop(turn_id, None)
        if timer is not None:
            timer.cancel()
