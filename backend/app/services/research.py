from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..cli.adapter import build_command
from ..cli.supervisor import ProcessSupervisor
from ..config import Settings
from ..db import utcnow
from ..repository import Repository
from ..roles import get_role
from .retrieval import collect_candidates

logger = logging.getLogger("iris.research")
URL_RE = re.compile(r"https?://[^\s)\]\"'<>]+")
ACTIVE_JOB_STATUSES = {"planning", "planned", "running", "canceling"}


class ResearchError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


class ResearchManager:
    def __init__(self, repo: Repository, settings: Settings) -> None:
        self.repo = repo
        self.settings = settings
        self.supervisor = ProcessSupervisor()
        self._lock = threading.Lock()
        self._processes: dict[str, dict[str, Any]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _job(self, job_id: str) -> dict[str, Any] | None:
        row = self.repo.db.query_one(
            "SELECT * FROM research_jobs WHERE id = ?", (job_id,)
        )
        if not row:
            return None
        data = dict(row)
        data["plan"] = _json_load(data.pop("plan_json", None), [])
        data["allow_web"] = bool(data.get("allow_web"))
        data["subtasks"] = self._subtasks(job_id)
        return data

    def _subtasks(self, job_id: str) -> list[dict[str, Any]]:
        rows = self.repo.db.query_all(
            "SELECT * FROM research_subtasks WHERE job_id = ? ORDER BY seq",
            (job_id,),
        )
        result = []
        for row in rows:
            item = dict(row)
            item["sources"] = _json_load(item.pop("sources_json", None), [])
            result.append(item)
        return result

    def _add_event(
        self, job_id: str, kind: str, payload: Any, subtask_id: str | None = None
    ) -> None:
        self.repo.db.execute(
            """
            INSERT INTO research_events(job_id, subtask_id, kind, created_at, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                job_id,
                subtask_id,
                kind,
                utcnow(),
                json.dumps(payload, ensure_ascii=False),
            ),
        )

    def _set_job(
        self,
        job_id: str,
        status: str,
        *,
        error: str | None = None,
        started: bool = False,
        ended: bool = False,
        synthesis_note_id: str | None = None,
    ) -> None:
        now = utcnow()
        assignments = ["status = ?", "error = ?"]
        params: list[Any] = [status, error]
        if started:
            assignments.append("started_at = ?")
            params.append(now)
        if ended:
            assignments.append("ended_at = ?")
            params.append(now)
        if synthesis_note_id is not None:
            assignments.append("synthesis_note_id = ?")
            params.append(synthesis_note_id)
        params.append(job_id)
        self.repo.db.execute(
            f"UPDATE research_jobs SET {', '.join(assignments)} WHERE id = ?",
            tuple(params),
        )

    def _set_subtask(
        self,
        subtask_id: str,
        status: str,
        *,
        result_text: str | None = None,
        sources: list[str] | None = None,
        error: str | None = None,
        started: bool = False,
        ended: bool = False,
    ) -> None:
        now = utcnow()
        assignments = ["status = ?", "error = ?"]
        params: list[Any] = [status, error]
        if result_text is not None:
            assignments.append("result_text = ?")
            params.append(result_text)
        if sources is not None:
            assignments.append("sources_json = ?")
            params.append(json.dumps(sources, ensure_ascii=False))
        if started:
            assignments.append("started_at = ?")
            params.append(now)
        if ended:
            assignments.append("ended_at = ?")
            params.append(now)
        params.append(subtask_id)
        self.repo.db.execute(
            f"UPDATE research_subtasks SET {', '.join(assignments)} WHERE id = ?",
            tuple(params),
        )

    def get_job(self, job_id: str) -> dict[str, Any]:
        job = self._job(job_id)
        if not job:
            raise ResearchError("research job not found", 404)
        return job

    def list_jobs(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.repo.db.query_all(
            "SELECT id FROM research_jobs WHERE task_id = ? ORDER BY created_at DESC",
            (task_id,),
        )
        return [job for row in rows if (job := self._job(row["id"])) is not None]

    # ------------------------------------------------------------------
    # Planning and execution
    # ------------------------------------------------------------------
    def create_plan(self, task_id: str, allow_web: bool = False) -> dict[str, Any]:
        task = self._require_scholar_task(task_id)
        with self._lock:
            active = self.repo.db.query_one(
                """
                SELECT id FROM research_jobs
                WHERE task_id = ? AND status IN ('planning', 'planned', 'running', 'canceling')
                """,
                (task_id,),
            )
            if active:
                raise ResearchError("task already has an active research job", 409)
            job_id = str(uuid4())
            self.repo.db.execute(
                """
                INSERT INTO research_jobs
                    (id, task_id, status, allow_web, max_concurrency,
                     plan_json, created_at)
                VALUES (?, ?, 'planning', ?, ?, '[]', ?)
                """,
                (
                    job_id,
                    task_id,
                    1 if allow_web else 0,
                    self.settings.research_concurrency,
                    utcnow(),
                ),
            )
            self._add_event(job_id, "job.planning", {"allow_web": allow_web})

        project = self.repo.get_project(task["project_id"])
        assert project is not None
        try:
            questions = self._generate_questions(task, project, allow_web)
            plan_json = json.dumps(questions, ensure_ascii=False)
            self.repo.db.execute(
                """
                UPDATE research_jobs
                SET status = 'planned', plan_json = ?
                WHERE id = ?
                """,
                (plan_json, job_id),
            )
            self._add_event(job_id, "job.planned", {"questions": questions})
        except Exception as exc:  # noqa: BLE001
            logger.exception("research.planning_failed job_id=%s", job_id)
            self._set_job(job_id, "failed", error=str(exc)[:2000], ended=True)
            self._add_event(job_id, "job.failed", {"error": str(exc)[:2000]})
            raise ResearchError(f"research planning failed: {exc}", 502) from exc
        return self.get_job(job_id)

    def update_plan(self, job_id: str, questions: list[str]) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job["status"] != "planned":
            raise ResearchError("only a planned research job can be edited", 409)
        cleaned = self._clean_questions(questions)
        self.repo.db.execute(
            "UPDATE research_jobs SET plan_json = ? WHERE id = ?",
            (json.dumps(cleaned, ensure_ascii=False), job_id),
        )
        self._add_event(job_id, "job.plan_updated", {"questions": cleaned})
        return self.get_job(job_id)

    def start_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job["status"] != "planned":
            raise ResearchError("research job is not planned", 409)
        questions = self._clean_questions(job["plan"])
        if not questions:
            raise ResearchError("research plan has no questions", 422)
        with self._lock:
            now = utcnow()
            for index, question in enumerate(questions, start=1):
                self.repo.db.execute(
                    """
                    INSERT INTO research_subtasks
                        (id, job_id, seq, question, status)
                    VALUES (?, ?, ?, ?, 'queued')
                    """,
                    (str(uuid4()), job_id, index, question),
                )
            self.repo.db.execute(
                """
                UPDATE research_jobs
                SET status = 'running', started_at = ?, plan_json = ?
                WHERE id = ?
                """,
                (now, json.dumps(questions, ensure_ascii=False), job_id),
            )
            self.repo.set_task_status(job["task_id"], "running")
            self._cancel_events[job_id] = threading.Event()
            thread = threading.Thread(
                target=self._run_job, args=(job_id,), daemon=True
            )
            self._threads[job_id] = thread
            thread.start()
        self._add_event(job_id, "job.started", {"questions": questions})
        return self.get_job(job_id)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job["status"] not in {"planning", "planned", "running", "canceling"}:
            raise ResearchError("research job is not active", 409)
        event = self._cancel_events.get(job_id)
        with self._lock:
            if event is not None:
                event.set()
            self._set_job(job_id, "canceling")
            for subtask in job["subtasks"]:
                if subtask["status"] == "queued":
                    self._set_subtask(
                        subtask["id"], "canceled", error="Canceled before start."
                    )
            processes = list(self._processes.get(job_id, {}).values())
        for process in processes:
            self.supervisor.terminate(process)
        if event is None:
            self._set_job(job_id, "canceled", ended=True, error="Canceled.")
            self.repo.set_task_status(job["task_id"], "canceled")
            self._add_event(job_id, "job.canceled", {})
        return self.get_job(job_id)

    def shutdown(self) -> None:
        with self._lock:
            job_ids = list(self._cancel_events.keys())
            for job_id in job_ids:
                self._cancel_events[job_id].set()
            processes = [
                process
                for mapping in self._processes.values()
                for process in mapping.values()
            ]
        for process in processes:
            self.supervisor.terminate(process)
        self.supervisor.close()

    def reconcile_interrupted_jobs(self) -> None:
        now = utcnow()
        with self.repo.db.transaction() as conn:
            conn.execute(
                """
                UPDATE research_jobs
                SET status = 'interrupted', ended_at = ?,
                    error = 'Iris stopped while this research job was active.'
                WHERE status IN ('planning', 'running', 'canceling')
                """,
                (now,),
            )
            conn.execute(
                """
                UPDATE research_subtasks
                SET status = 'interrupted', ended_at = ?,
                    error = 'Iris stopped while this subtask was active.'
                WHERE status IN ('queued', 'running')
                """,
                (now,),
            )

    # ------------------------------------------------------------------
    # Execution internals
    # ------------------------------------------------------------------
    def _run_job(self, job_id: str) -> None:
        job = self._job(job_id)
        if not job:
            return
        task = self.repo.get_task(job["task_id"])
        project = self.repo.get_project(task["project_id"]) if task else None
        if not task or not project:
            self._set_job(job_id, "failed", error="Task or project disappeared.", ended=True)
            return
        cancel_event = self._cancel_events.get(job_id, threading.Event())
        subtasks = job["subtasks"]
        try:
            with ThreadPoolExecutor(max_workers=max(1, job["max_concurrency"])) as pool:
                futures = [
                    pool.submit(
                        self._run_subtask_with_retries,
                        job,
                        subtask,
                        task,
                        project,
                        cancel_event,
                    )
                    for subtask in subtasks
                ]
                for future in futures:
                    try:
                        future.result()
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("research.subtask_failed job_id=%s", job_id)
                        self._add_event(job_id, "subtask.exception", {"error": str(exc)[:1000]})

            if cancel_event.is_set():
                self._set_job(job_id, "canceled", ended=True, error="Canceled.")
                self.repo.set_task_status(job["task_id"], "canceled")
                self._add_event(job_id, "job.canceled", {})
                return

            current = self._subtasks(job_id)
            successful = [s for s in current if s["status"] == "succeeded"]
            if not successful:
                self._set_job(
                    job_id,
                    "failed",
                    ended=True,
                    error="All research subtasks failed.",
                )
                self.repo.set_task_status(job["task_id"], "failed")
                self._add_event(job_id, "job.failed", {"error": "All subtasks failed."})
                return

            self._add_event(
                job_id,
                "job.synthesizing",
                {"succeeded": len(successful), "total": len(current)},
            )
            note = self._synthesize(job, task, project, current)
            self._set_job(
                job_id,
                "completed",
                ended=True,
                synthesis_note_id=note["id"],
            )
            self.repo.set_task_status(job["task_id"], "needs_review")
            self._add_event(
                job_id, "job.completed", {"synthesis_note_id": note["id"]}
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("research.job_failed job_id=%s", job_id)
            self._set_job(job_id, "failed", ended=True, error=str(exc)[:2000])
            self.repo.set_task_status(job["task_id"], "failed")
            self._add_event(job_id, "job.failed", {"error": str(exc)[:2000]})
        finally:
            with self._lock:
                self._cancel_events.pop(job_id, None)
                self._processes.pop(job_id, None)
                self._threads.pop(job_id, None)

    def _run_subtask_with_retries(
        self,
        job: dict[str, Any],
        subtask: dict[str, Any],
        task: dict[str, Any],
        project: dict[str, Any],
        cancel_event: threading.Event,
    ) -> None:
        max_attempts = max(1, self.settings.research_subtask_max_attempts)
        for attempt in range(1, max_attempts + 1):
            if cancel_event.is_set():
                self._set_subtask(subtask["id"], "canceled", error="Canceled.")
                return
            self.repo.db.execute(
                "UPDATE research_subtasks SET attempts = ? WHERE id = ?",
                (attempt, subtask["id"]),
            )
            self._add_event(
                job["id"],
                "subtask.attempt",
                {"attempt": attempt, "max_attempts": max_attempts},
                subtask["id"],
            )
            self._run_subtask(job, subtask, task, project, cancel_event)
            row = self.repo.db.query_one(
                "SELECT status, error FROM research_subtasks WHERE id = ?",
                (subtask["id"],),
            )
            if not row or row["status"] in {"succeeded", "canceled"}:
                return
            if attempt >= max_attempts:
                return
            delay = self.settings.research_subtask_backoff_seconds * (
                2 ** (attempt - 1)
            )
            self._add_event(
                job["id"],
                "subtask.retry",
                {
                    "next_attempt": attempt + 1,
                    "backoff_seconds": delay,
                    "previous_error": row["error"],
                },
                subtask["id"],
            )
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline:
                if cancel_event.is_set():
                    self._set_subtask(
                        subtask["id"], "canceled", error="Canceled."
                    )
                    return
                time.sleep(0.2)
            self._set_subtask(subtask["id"], "queued", error=None)

    def _run_subtask(
        self,
        job: dict[str, Any],
        subtask: dict[str, Any],
        task: dict[str, Any],
        project: dict[str, Any],
        cancel_event: threading.Event,
    ) -> None:
        if cancel_event.is_set():
            self._set_subtask(subtask["id"], "canceled", error="Canceled.")
            return
        self._set_subtask(subtask["id"], "running", started=True)
        self._add_event(
            job["id"], "subtask.started", {"question": subtask["question"]}, subtask["id"]
        )
        session_id = str(uuid4())
        profile = "research" if job["allow_web"] else "read_only"
        prompt = self._subtask_prompt(job, subtask, task, project)
        role = get_role("scholar")
        command = build_command(
            self.settings,
            session_id,
            "new",
            profile,
            [],
            role_instruction=role.system_instruction,
            max_turns=self.settings.research_subtask_max_turns,
        )
        try:
            process = self.supervisor.start(command, Path(project["workspace_path"]), prompt)
        except Exception as exc:  # noqa: BLE001
            self._set_subtask(
                subtask["id"], "failed", error=f"spawn failed: {exc}", ended=True
            )
            self._add_event(
                job["id"], "subtask.failed", {"error": str(exc)}, subtask["id"]
            )
            return
        with self._lock:
            self._processes.setdefault(job["id"], {})[subtask["id"]] = process
        # Cancellation may arrive between the status update and process start.
        if cancel_event.is_set():
            self.supervisor.terminate(process)
        timed_out = {"value": False}

        def timeout() -> None:
            timed_out["value"] = True
            self.supervisor.terminate(process)

        timer = threading.Timer(
            self.settings.research_subtask_timeout_seconds, timeout
        )
        timer.daemon = True
        timer.start()
        stderr_lines: list[str] = []

        def read_stderr() -> None:
            try:
                for line in process.stderr:
                    if line.strip() and len(stderr_lines) < 30:
                        stderr_lines.append(line.rstrip())
            except Exception:
                pass

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()
        result_text = None
        result_session = session_id
        try:
            for raw in process.stdout:
                line = raw.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "result":
                    result_session = event.get("session_id") or session_id
                    if event.get("is_error"):
                        detail = (
                            event.get("result")
                            or event.get("error")
                            or "CLI returned an error"
                        )
                        reason = event.get("terminal_reason") or "error"
                        status = event.get("api_error_status")
                        if status:
                            reason = f"{reason} / HTTP {status}"
                        raise ResearchError(f"{reason}: {str(detail)[:1800]}")
                    result_text = str(event.get("result") or "")
            process.wait(timeout=10)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)[:2000]
            if timed_out["value"]:
                error = "Research subtask timed out."
            self._set_subtask(
                subtask["id"], "failed", error=error, ended=True
            )
            self._add_event(
                job["id"], "subtask.failed", {"error": error}, subtask["id"]
            )
            self.supervisor.terminate(process)
            return
        finally:
            timer.cancel()
            stderr_thread.join(timeout=2)
            with self._lock:
                self._processes.get(job["id"], {}).pop(subtask["id"], None)

        if cancel_event.is_set() or timed_out["value"]:
            self._set_subtask(
                subtask["id"],
                "canceled" if not timed_out["value"] else "failed",
                error="Canceled." if not timed_out["value"] else "Research subtask timed out.",
                ended=True,
            )
            self._add_event(
                job["id"],
                "subtask.canceled" if not timed_out["value"] else "subtask.failed",
                {},
                subtask["id"],
            )
            return
        if not result_text:
            error = "\n".join(stderr_lines) or "CLI exited without a result."
            self._set_subtask(subtask["id"], "failed", error=error[:3000], ended=True)
            self._add_event(
                job["id"], "subtask.failed", {"error": error[:1000]}, subtask["id"]
            )
            return
        sources = list(dict.fromkeys(URL_RE.findall(result_text)))[:20]
        self._set_subtask(
            subtask["id"],
            "succeeded",
            result_text=result_text[: self.settings.max_event_payload_chars],
            sources=sources,
            ended=True,
        )
        self._add_event(
            job["id"],
            "subtask.succeeded",
            {
                "sources": sources,
                "chars": len(result_text),
                "session_id": result_session,
            },
            subtask["id"],
        )

    def _subtask_prompt(
        self,
        job: dict[str, Any],
        subtask: dict[str, Any],
        task: dict[str, Any],
        project: dict[str, Any],
    ) -> str:
        candidates = collect_candidates(
            self.repo, project, task, self.settings.max_context_chars
        )
        selected = [
            note
            for note in candidates["notes"]
            if note["id"] in candidates["selected_note_ids"]
        ]
        context_parts = []
        used = 0
        for note in selected[:4]:
            # An explicit cross-task handoff gets most of the source note;
            # other selected notes stay intentionally narrow.
            limit = 12000 if note.get("handoff") else 2500
            content = (note.get("content_md") or "")[:limit]
            section = (
                f"### {note['title']} [{note.get('scope', 'project')}]\n{content}"
            )
            if used + len(section) > self.settings.max_context_chars:
                break
            context_parts.append(section)
            used += len(section)
        context = "\n\n".join(context_parts) or "(no accepted context notes)"
        return (
            "You are one bounded Scholar subtask in Iris. Research only the "
            "question below; do not continue into unrelated questions.\n\n"
            f"Parent research goal:\n{task.get('goal_md') or task.get('title')}\n\n"
            f"Project brief:\n{project.get('brief_md') or '(none)'}\n\n"
            f"Reusable accepted context:\n{context}\n\n"
            f"Research question:\n{subtask['question']}\n\n"
            "Sources: use the local workspace and, if allowed, native WebSearch/"
            "WebFetch. Do not invent sources.\n\n"
            "Return a concise result with these sections:\n"
            "## Facts\n"
            "## Opinions / interpretations\n"
            "## Hypotheses / uncertainty\n"
            "## Sources\n"
            "Do not modify files."
        )

    def _synthesize(
        self,
        job: dict[str, Any],
        task: dict[str, Any],
        project: dict[str, Any],
        subtasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        findings = []
        for subtask in subtasks:
            if subtask["status"] != "succeeded":
                findings.append(
                    f"### {subtask['question']}\n[FAILED] {subtask.get('error') or ''}"
                )
                continue
            findings.append(
                f"### {subtask['question']}\n{subtask.get('result_text') or ''}"
            )
        findings_text = "\n\n".join(findings)[:26000]
        prompt = (
            "Synthesize these bounded research findings for the parent goal. "
            "Clearly separate:\n"
            "## Known facts\n"
            "## Personal opinions / interpretations\n"
            "## Unverified hypotheses\n"
            "## Sources\n"
            "## Gaps / next questions\n"
            "Only include facts supported by the findings; preserve source URLs; "
            "do not invent sources. Be explicit about uncertainty.\n\n"
            f"Parent goal:\n{task.get('goal_md') or task.get('title')}\n\n"
            f"Findings:\n{findings_text}"
        )
        role = get_role("scholar")
        text = self._run_oneshot(
            prompt,
            Path(project["workspace_path"]),
            role.system_instruction,
            max_turns=2,
        )
        note = self.repo.create_note(
            project_id=project["id"],
            title=f"Research: {task['title']}",
            content_md=text,
            kind="research",
            status="draft",
            task_id=task["id"],
        )
        return note

    def _run_oneshot(
        self,
        prompt: str,
        cwd: Path,
        role_instruction: str,
        max_turns: int = 2,
    ) -> str:
        command = [
            *self.settings.claude_command,
            "-p",
            "--output-format",
            "json",
            "--safe-mode",
            "--append-system-prompt",
            role_instruction,
            "--max-turns",
            str(max_turns),
            "--tools",
            "",
            "--session-id",
            str(uuid4()),
        ]
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            out, err = process.communicate(prompt, timeout=180)
        except subprocess.TimeoutExpired:
            process.kill()
            raise ResearchError("research synthesis/planning timed out", 504)
        if process.returncode != 0 and not out.strip():
            raise ResearchError(
                (err or "CLI failed without output")[:2000], 502
            )
        try:
            payload = json.loads(out)
        except json.JSONDecodeError as exc:
            raise ResearchError(f"CLI returned non-JSON output: {out[:500]}", 502) from exc
        if payload.get("is_error"):
            raise ResearchError(str(payload.get("result") or "CLI error")[:2000], 502)
        result = str(payload.get("result") or "")
        if not result.strip():
            raise ResearchError("CLI returned no synthesis text", 502)
        return result

    def _generate_questions(
        self, task: dict[str, Any], project: dict[str, Any], allow_web: bool
    ) -> list[str]:
        role = get_role("scholar")
        prompt = (
            "Break the research goal into 3-5 independent, bounded questions. "
            "Return only a JSON object: {\"questions\": [\"...\"]}. "
            f"Maximum {self.settings.research_max_subtasks} questions.\n\n"
            f"Research goal:\n{task.get('goal_md') or task.get('title')}\n\n"
            f"Project brief:\n{project.get('brief_md') or '(none)'}\n\n"
            f"Web access allowed: {allow_web}. "
            "Questions should be answerable independently and should not overlap."
        )
        try:
            text = self._run_oneshot(
                prompt, Path(project["workspace_path"]), role.system_instruction, 2
            )
            questions = self._parse_questions(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("research.planning_fallback: %s", exc)
            questions = [
                "What are the key facts, definitions, and authoritative sources?",
                "What are the main competing views or interpretations?",
                "What is uncertain, missing, or still a hypothesis?",
            ]
        return self._clean_questions(questions)

    def _parse_questions(self, text: str) -> list[str]:
        candidate = text.strip()
        if "```" in candidate:
            blocks = re.findall(r"```(?:json)?\s*(.*?)```", candidate, re.S)
            if blocks:
                candidate = blocks[0].strip()
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                payload = json.loads(candidate[start : end + 1])
                values = payload.get("questions", [])
                if isinstance(values, list):
                    return [str(value).strip() for value in values if str(value).strip()]
            except json.JSONDecodeError:
                pass
        # Last-resort line parsing.
        lines = [
            line.strip(" -0123456789.\t")
            for line in candidate.splitlines()
            if line.strip()
        ]
        return [line for line in lines if len(line) > 8]

    def _clean_questions(self, questions: list[str]) -> list[str]:
        cleaned = list(
            dict.fromkeys(
                str(question).strip()
                for question in questions
                if str(question).strip()
            )
        )
        return cleaned[: self.settings.research_max_subtasks]

    def _require_scholar_task(self, task_id: str) -> dict[str, Any]:
        task = self.repo.get_task(task_id)
        if not task:
            raise ResearchError("task not found", 404)
        if task.get("role") != "scholar":
            raise ResearchError("research orchestration requires a Scholar task", 422)
        return task
