from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..cli.oneshot import OneShotError, run_oneshot
from ..config import Settings
from ..db import utcnow
from ..repository import Repository
from ..repository_facts import FactRepository
from ..repository_sessions import SessionRepository
from .facts import ExtractionParseError, parse_extraction
from .prompts import (
    EXTRACTION_SYSTEM,
    SUMMARY_SYSTEM,
    build_extraction_prompt,
    build_summary_prompt,
)

logger = logging.getLogger("iris.memory")

TERMINAL_TURN_STATUSES = {"succeeded", "failed", "canceled", "interrupted"}


class MemoryError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class MemoryManager:
    """Runs summarization and fact extraction on a single ordered worker."""

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
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, settings.memory_concurrency),
            thread_name_prefix="iris-memory",
        )

    # ------------------------------------------------------------------
    # Summaries (L2)
    # ------------------------------------------------------------------
    def notify_turn_completed(self, session_id: str) -> None:
        session = self.repo_sessions.get_session(session_id)
        if not session:
            return
        covers = int(session.get("summary_covers_turn_seq") or 0)
        turns, chars = self.repo_sessions.summary_progress(session_id, covers)
        if (
            turns >= self.settings.summary_trigger_turns
            or chars >= self.settings.summary_trigger_chars
        ):
            self.request_summary(session_id, "auto")

    def request_summary(self, session_id: str, kind: str = "auto") -> dict[str, Any]:
        session = self.repo_sessions.get_session(session_id)
        if not session:
            raise MemoryError("session not found", 404)
        with self._lock:
            if self.repo_sessions.active_summary(session_id):
                return {
                    "queued": False,
                    "reason": "a summary is already pending or running",
                }
            summary = self.repo_sessions.create_summary(
                session_id,
                kind,
                int(session.get("summary_covers_turn_seq") or 0),
            )
        self._executor.submit(self._run_summary, summary["id"], session_id, kind)
        logger.info("memory.summary_queued summary_id=%s kind=%s", summary["id"], kind)
        return {"queued": True, "summary": summary}

    def _run_summary(self, summary_id: str, session_id: str, kind: str) -> None:
        self.repo_sessions.update_summary(summary_id, {"status": "running"})
        try:
            session = self.repo_sessions.get_session(session_id)
            if not session:
                raise MemoryError("session not found", 404)
            prior = self.repo_sessions.latest_summary(session_id, "succeeded")
            covers = int(session.get("summary_covers_turn_seq") or 0)
            turns = [
                turn
                for turn in self.repo_sessions.list_turns_since(session_id, covers)
                if turn["status"] in TERMINAL_TURN_STATUSES
            ]
            if not turns:
                content = (prior or {}).get("content_md") or ""
                self.repo_sessions.update_summary(
                    summary_id,
                    {
                        "status": "succeeded",
                        "content_md": content,
                        "covers_through_turn_seq": covers,
                        "completed_at": utcnow(),
                    },
                )
                if kind == "compact":
                    self.repo_sessions.clear_session_cli(session_id)
                return

            messages = self.repo_sessions.list_messages(session_id)
            messages_by_turn: dict[str, list[dict[str, Any]]] = {}
            for message in messages:
                turn_id = message.get("turn_id")
                if turn_id:
                    messages_by_turn.setdefault(turn_id, []).append(message)
            tool_names_by_turn: dict[str, list[str]] = {}
            for turn in turns:
                names = [
                    use.get("name")
                    for use in self.repo_sessions.tool_uses(turn["id"])
                    if use.get("name")
                ]
                tool_names_by_turn[turn["id"]] = list(dict.fromkeys(names))

            prompt = build_summary_prompt(
                session=session,
                prior_summary=(prior or {}).get("content_md"),
                turns=turns,
                messages_by_turn=messages_by_turn,
                tool_names_by_turn=tool_names_by_turn,
                max_chars=self.settings.summary_input_max_chars,
            )
            result = run_oneshot(
                self.settings,
                SUMMARY_SYSTEM,
                prompt,
                cwd=self.settings.data_dir,
                max_turns=self.settings.summary_max_turns,
                timeout=self.settings.summary_timeout_seconds,
            )
            last_seq = max(int(turn["seq"]) for turn in turns)
            self.repo_sessions.update_summary(
                summary_id,
                {
                    "status": "succeeded",
                    "content_md": result.text,
                    "covers_through_turn_seq": last_seq,
                    "cost_usd": result.cost_usd,
                    "completed_at": utcnow(),
                },
            )
            self.repo_sessions.set_summary_checkpoint(session_id, last_seq)
            if kind == "compact":
                self.repo_sessions.clear_session_cli(session_id)
            logger.info(
                "memory.summary_succeeded summary_id=%s covers=%s chars=%s",
                summary_id,
                last_seq,
                len(result.text),
            )
        except OneShotError as exc:
            logger.warning("memory.summary_failed summary_id=%s %s", summary_id, exc)
            self.repo_sessions.update_summary(
                summary_id,
                {
                    "status": "failed",
                    "error": exc.message,
                    "completed_at": utcnow(),
                },
            )
        except Exception as exc:  # noqa: BLE001 - job must not take the worker down
            logger.exception("memory.summary_crashed summary_id=%s", summary_id)
            self.repo_sessions.update_summary(
                summary_id,
                {
                    "status": "failed",
                    "error": str(exc)[:4000],
                    "completed_at": utcnow(),
                },
            )

    # ------------------------------------------------------------------
    # Fact extraction (L3)
    # ------------------------------------------------------------------
    def start_extraction(
        self,
        *,
        role: str | None = None,
        project_id: str | None = None,
        session_ids: list[str] | None = None,
        max_sessions: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self.repo_facts.active_extraction():
                raise MemoryError("another fact extraction is already running", 409)

            sessions: list[dict[str, Any]] = []
            if session_ids:
                for session_id in list(dict.fromkeys(session_ids)):
                    session = self.repo_sessions.get_session(session_id)
                    if not session:
                        raise MemoryError("session not found", 404)
                    sessions.append(session)
            else:
                sessions = self.repo_sessions.list_sessions_with_summaries(
                    role=role,
                    project_id=project_id,
                    limit=max_sessions or self.settings.extraction_max_sessions,
                )
            selected_ids = [session["id"] for session in sessions]
            if not selected_ids:
                raise MemoryError(
                    "no summarized sessions match this scope; end a session first",
                    422,
                )
            if not self.repo_sessions.latest_summaries_for_sessions(selected_ids):
                raise MemoryError(
                    "the selected sessions have no successful summaries; "
                    "end a session first",
                    422,
                )
            scope = {
                "role": role,
                "project_id": project_id,
                "session_ids": selected_ids,
                "max_sessions": max_sessions or self.settings.extraction_max_sessions,
            }
            extraction = self.repo_facts.create_extraction(scope)
        self._executor.submit(
            self._run_extraction, extraction["id"], selected_ids, project_id
        )
        logger.info(
            "memory.extraction_queued extraction_id=%s sessions=%s",
            extraction["id"],
            len(selected_ids),
        )
        return extraction

    def _run_extraction(
        self,
        extraction_id: str,
        session_ids: list[str],
        project_id: str | None,
    ) -> None:
        try:
            summaries_map = self.repo_sessions.latest_summaries_for_sessions(session_ids)
            summaries: list[dict[str, Any]] = []
            for session_id in session_ids:
                session = self.repo_sessions.get_session(session_id)
                summary = summaries_map.get(session_id)
                if session and summary:
                    summaries.append(
                        {
                            **summary,
                            "session_id": session_id,
                            "role": session["role"],
                            "title": session["title"],
                        }
                    )
            if not summaries:
                raise MemoryError("the selected sessions have no successful summaries", 422)

            existing_facts = self.repo_facts.list_facts(status="accepted", limit=1000)
            workspace = (
                self.repo_projects.get_project(project_id) if project_id else None
            )
            extraction = self.repo_facts.get_extraction(extraction_id) or {}
            role = (extraction.get("scope") or {}).get("role") or "both"
            prompt = build_extraction_prompt(
                role=role,
                workspace=workspace,
                summaries=summaries,
                existing_facts=existing_facts,
                max_chars=self.settings.extraction_input_max_chars,
            )
            result = run_oneshot(
                self.settings,
                EXTRACTION_SYSTEM,
                prompt,
                cwd=self.settings.data_dir,
                max_turns=self.settings.extraction_max_turns,
                timeout=self.settings.extraction_timeout_seconds,
            )
            candidates, dropped = parse_extraction(
                result.text,
                allowed_session_ids=session_ids,
                project_id=project_id,
                existing_facts=existing_facts,
            )
            created: list[str] = []
            for candidate in candidates:
                fact = self.repo_facts.create_fact(
                    scope=candidate["scope"],
                    project_id=candidate["project_id"],
                    role=candidate["role"],
                    kind=candidate["kind"],
                    status="candidate",
                    title=candidate["title"],
                    content_md=candidate["content_md"],
                    source_session_ids=candidate["source_session_ids"],
                    evidence_md=candidate["evidence_md"],
                    confidence=candidate["confidence"],
                    supersedes_id=(
                        candidate["target_fact_id"]
                        if candidate["action"] == "update"
                        else None
                    ),
                    extracted_at=utcnow(),
                )
                created.append(fact["id"])
            if dropped:
                logger.info(
                    "memory.extraction_dropped extraction_id=%s reasons=%s",
                    extraction_id,
                    dropped[:20],
                )
            self.repo_facts.update_extraction(
                extraction_id,
                {
                    "status": "succeeded",
                    "candidate_count": len(created),
                    "ended_at": utcnow(),
                },
            )
            logger.info(
                "memory.extraction_succeeded extraction_id=%s candidates=%s",
                extraction_id,
                len(created),
            )
        except (OneShotError, ExtractionParseError, MemoryError) as exc:
            message = getattr(exc, "message", str(exc))
            logger.warning("memory.extraction_failed extraction_id=%s %s", extraction_id, message)
            self.repo_facts.update_extraction(
                extraction_id,
                {
                    "status": "failed",
                    "error": message[:4000],
                    "ended_at": utcnow(),
                },
            )
        except Exception as exc:  # noqa: BLE001 - job must not take the worker down
            logger.exception("memory.extraction_crashed extraction_id=%s", extraction_id)
            self.repo_facts.update_extraction(
                extraction_id,
                {
                    "status": "failed",
                    "error": str(exc)[:4000],
                    "ended_at": utcnow(),
                },
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def reconcile(self) -> None:
        self.repo_sessions.reconcile_summaries()
        self.repo_facts.reconcile_extractions()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
