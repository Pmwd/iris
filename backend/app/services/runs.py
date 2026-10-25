from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..cli.adapter import build_command, normalize_event
from ..cli.supervisor import ProcessSupervisor
from ..config import Settings
from ..repository import Repository
from ..roles import get_role
from .context import PROMPT_VERSION, build_context
from .retrieval import collect_candidates

logger = logging.getLogger("iris.runs")


class RunError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class RunManager:
    def __init__(self, repo: Repository, settings: Settings) -> None:
        self.repo = repo
        self.settings = settings
        self.supervisor = ProcessSupervisor()
        self._lock = threading.Lock()
        self._processes: dict[str, Any] = {}
        self._cancel_reasons: dict[str, str] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._shutting_down = False

    def start_run(
        self,
        task_id: str,
        *,
        mode: str = "new",
        profile: str | None = None,
        context_note_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if mode not in {"new", "resume"}:
            raise RunError("mode must be 'new' or 'resume'", 422)

        with self._lock:
            task = self.repo.get_task(task_id)
            if not task:
                raise RunError("task not found", 404)
            role = get_role(task.get("role"))
            profile = profile or role.default_profile
            if profile not in role.allowed_profiles:
                raise RunError(
                    f"permission profile '{profile}' is not allowed for "
                    f"the {role.name} role",
                    422,
                )
            project = self.repo.get_project(task["project_id"])
            if not project:
                raise RunError("project not found", 404)
            if project.get("archived_at"):
                raise RunError("project is archived", 409)

            if self.repo.active_run_for_project(project["id"]):
                raise RunError("another run is active in this project", 409)

            if task["status"] == "running":
                raise RunError("task is already running", 409)
            if task["status"] == "done":
                raise RunError("task is done; create a follow-up task", 409)

            if mode == "resume":
                if task["status"] not in {"interrupted", "failed", "canceled"}:
                    raise RunError(
                        "only interrupted, failed, or canceled tasks can be resumed", 409
                    )
                session_id = task.get("current_session_id")
                if not session_id:
                    raise RunError("task has no CLI session to resume", 409)
            else:
                if task["status"] not in {"ready", "interrupted", "failed", "canceled"}:
                    raise RunError("task cannot be started from its current status", 409)
                session_id = str(uuid4())

            workspace = Path(project["workspace_path"]).expanduser().resolve()
            if not workspace.is_dir():
                raise RunError(f"workspace does not exist: {workspace}", 422)

            if profile == "execute" and not project.get("allowed_tools"):
                raise RunError(
                    "execute profile requires at least one allowed PowerShell pattern", 422
                )

            candidates = collect_candidates(
                self.repo,
                project,
                task,
                self.settings.max_context_chars,
            )
            notes = candidates["notes"]
            by_id = {note["id"]: note for note in notes}

            if context_note_ids is None:
                selected_ids = list(candidates["selected_note_ids"])
                selection_mode = "auto"
            else:
                selected_ids = list(dict.fromkeys(context_note_ids))
                invalid = [nid for nid in selected_ids if nid not in by_id]
                if invalid:
                    raise RunError(
                        "context contains notes that are not accepted for this task",
                        422,
                    )
                selection_mode = "manual"

            selected_notes = [
                by_id[nid] for nid in selected_ids if nid in by_id
            ]
            pack = build_context(
                project,
                task,
                notes,
                selected_ids,
                self.settings.max_context_chars,
            )
            pack.manifest["selection_mode"] = selection_mode
            pack.manifest["recommended_note_ids"] = candidates["selected_note_ids"]
            pack.manifest["recommended_tokens"] = candidates["estimated_tokens"]
            pack.manifest["role"] = role.id
            command = build_command(
                self.settings,
                session_id,
                mode,
                profile,
                list(project.get("allowed_tools") or []),
                role_instruction=role.system_instruction,
            )
            run = self.repo.create_run(
                task_id=task_id,
                session_id=session_id,
                permission_profile=profile,
                workspace_path=str(workspace),
                context_manifest=pack.manifest,
                prompt_version=PROMPT_VERSION,
            )
            try:
                used_ids = {
                    note["id"]
                    for note in pack.manifest.get("included_notes", [])
                }
                self.repo.mark_notes_used(
                    [note for note in selected_notes if note["id"] in used_ids]
                )
            except Exception:
                logger.exception("context.mark_used_failed run_id=%s", run["id"])
            thread = threading.Thread(
                target=self._monitor,
                args=(
                    run["id"],
                    task_id,
                    command,
                    workspace,
                    pack.prompt,
                ),
                daemon=True,
            )
            self._threads[run["id"]] = thread
            thread.start()
            logger.info(
                "run.started run_id=%s task_id=%s role=%s profile=%s mode=%s attempt=%s",
                run["id"],
                task_id,
                role.id,
                profile,
                mode,
                run["attempt_no"],
            )
            return run

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        run = self.repo.get_run(run_id)
        if not run:
            raise RunError("run not found", 404)
        if run["status"] not in {"starting", "running", "canceling"}:
            raise RunError("run is not active", 409)

        with self._lock:
            process = self._processes.get(run_id)
            self._cancel_reasons[run_id] = "user"
            self.repo.set_run_canceling(run_id)
        logger.info("run.cancel_requested run_id=%s", run_id)

        if process is None:
            self.repo.finish_run(
                run_id,
                run["task_id"],
                "canceled",
                error_type="canceled",
                error_message="Run was canceled by the user.",
            )
        else:
            self.supervisor.terminate(process)
        return self.repo.get_run(run_id) or run

    def shutdown(self) -> None:
        self._shutting_down = True
        with self._lock:
            active = list(self._processes.items())
            for run_id, _ in active:
                self._cancel_reasons[run_id] = "shutdown"
            threads = list(self._threads.values())
        if active:
            logger.info("iris.shutdown active_runs=%s", len(active))
        for _, process in active:
            self.supervisor.terminate(process)
        for thread in threads:
            thread.join(timeout=3)
        self.supervisor.close()

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------
    def _monitor(
        self,
        run_id: str,
        task_id: str,
        command: list[str],
        workspace: Path,
        prompt: str,
    ) -> None:
        seq = 0
        final_status: str | None = None
        process = None
        timer: threading.Timer | None = None
        stderr_thread: threading.Thread | None = None
        stderr_lines: list[str] = []

        try:
            process = self.supervisor.start(command, workspace, prompt)
        except Exception as exc:  # noqa: BLE001 - surfaced as a run error
            logger.error("run.spawn_failed run_id=%s error=%s", run_id, exc)
            self.repo.finish_run(
                run_id,
                task_id,
                "failed",
                error_type="cli_spawn_failed",
                error_message=str(exc)[:4000],
            )
            self._cleanup(run_id)
            return

        with self._lock:
            self._processes[run_id] = process

        self.repo.set_run_running(run_id, process.pid)
        timer = threading.Timer(
            self.settings.run_timeout_seconds,
            self._on_timeout,
            args=(run_id,),
        )
        timer.daemon = True
        timer.start()
        with self._lock:
            self._timers[run_id] = timer

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
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    seq += 1
                    self.repo.add_event(
                        run_id,
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
                    self.repo.add_event(run_id, seq, kind, payload, truncated)
                    if kind == "run.result":
                        final_status = self._finish_from_result(
                            run_id, task_id, payload
                        )
                        for denial in payload.get("permission_denials") or []:
                            seq += 1
                            self.repo.add_event(
                                run_id, seq, "permission.denied", denial, False
                            )
        except Exception as exc:  # noqa: BLE001 - keep the run state consistent
            logger.exception("run.monitor_failed run_id=%s", run_id)
            final_status = final_status or "failed"
            self.repo.finish_run(
                run_id,
                task_id,
                "failed",
                error_type="cli_monitor_failed",
                error_message=str(exc)[:4000],
            )
        finally:
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
                self.repo.add_event(
                    run_id,
                    seq,
                    "cli.stderr",
                    {"lines": stderr_lines},
                    truncated=len(stderr_lines) >= 50,
                )
            seq += 1
            self.repo.add_event(run_id, seq, "process.exit", {"exit_code": exit_code})

            current = self.repo.get_run(run_id)
            if current and current["status"] in {
                "starting",
                "running",
                "canceling",
            }:
                reason = self._cancel_reasons.get(run_id)
                logger.info(
                    "run.ended_without_result run_id=%s reason=%s exit_code=%s",
                    run_id,
                    reason or "none",
                    exit_code,
                )
                if self._shutting_down:
                    self.repo.finish_run(
                        run_id,
                        task_id,
                        "interrupted",
                        exit_code=exit_code,
                        error_type="service_stopped",
                        error_message="Iris stopped while the run was active.",
                    )
                elif reason == "timeout":
                    self.repo.finish_run(
                        run_id,
                        task_id,
                        "failed",
                        exit_code=exit_code,
                        error_type="timeout",
                        error_message="Run exceeded the configured time limit.",
                    )
                elif reason == "user":
                    self.repo.finish_run(
                        run_id,
                        task_id,
                        "canceled",
                        exit_code=exit_code,
                        error_type="canceled",
                        error_message="Run was canceled by the user.",
                    )
                else:
                    message = "\n".join(stderr_lines).strip()
                    self.repo.finish_run(
                        run_id,
                        task_id,
                        "failed",
                        exit_code=exit_code,
                        error_type=(
                            "cli_nonzero_exit"
                            if exit_code
                            else "cli_no_result"
                        ),
                        error_message=(
                            message[:4000]
                            if message
                            else "The CLI exited without a result event."
                        ),
                    )
            elif current and current["status"] == "succeeded" and exit_code not in (0, None):
                self.repo.finish_run(
                    run_id,
                    task_id,
                    "failed",
                    exit_code=exit_code,
                    error_type="cli_nonzero_exit",
                    error_message="The CLI reported success but exited with a non-zero code.",
                )
            else:
                self.repo.db.execute(
                    "UPDATE runs SET exit_code = ? WHERE id = ?", (exit_code, run_id)
                )

            self._cleanup(run_id)

    def _finish_from_result(
        self, run_id: str, task_id: str, payload: dict[str, Any]
    ) -> str:
        terminal_reason = payload.get("terminal_reason")
        subtype = payload.get("subtype")
        is_error = bool(payload.get("is_error"))
        result_text = payload.get("result")
        session_id = payload.get("session_id")
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
                "run.failed run_id=%s error_type=%s terminal=%s",
                run_id,
                error_type,
                terminal_reason or subtype,
            )
            self.repo.finish_run(
                run_id,
                task_id,
                "failed",
                result_text=result_text,
                session_id=session_id,
                cost_usd=cost,
                usage=usage,
                error_type=error_type,
                error_message=str(error_message)[:4000],
            )
            return "failed"

        logger.info("run.succeeded run_id=%s cost=%s", run_id, cost)
        self.repo.finish_run(
            run_id,
            task_id,
            "succeeded",
            result_text=result_text,
            session_id=session_id,
            cost_usd=cost,
            usage=usage,
        )
        return "succeeded"

    def _on_timeout(self, run_id: str) -> None:
        with self._lock:
            process = self._processes.get(run_id)
            if process is None:
                return
            self._cancel_reasons[run_id] = "timeout"
            self.repo.set_run_canceling(run_id)
        logger.warning("run.timeout run_id=%s", run_id)
        self.supervisor.terminate(process)

    def _cleanup(self, run_id: str) -> None:
        with self._lock:
            self._processes.pop(run_id, None)
            timer = self._timers.pop(run_id, None)
            self._cancel_reasons.pop(run_id, None)
            self._threads.pop(run_id, None)
        if timer is not None:
            timer.cancel()
