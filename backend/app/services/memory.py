from __future__ import annotations

import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..cli.oneshot import OneShotError, run_oneshot
from ..config import Settings
from ..db import utcnow
from ..repository import Repository
from ..repository_facts import FactRepository, normalize_fingerprint
from ..repository_sessions import SessionRepository
from .facts import (
    FACT_KINDS,
    FACT_ROLES,
    FACT_SCOPES,
    ExtractionParseError,
    parse_extraction,
)
from .prompts import (
    EXTRACTION_SYSTEM,
    SUMMARY_SYSTEM,
    build_extraction_prompt,
    build_summary_prompt,
)
from .relations import find_relations

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
    # Quick capture (human-triggered)
    # ------------------------------------------------------------------
    def remember(
        self,
        *,
        text: str,
        title: str,
        scope: str,
        project_id: str | None,
        role: str,
        kind: str,
        aliases: list[str] | None = None,
        tags: list[str] | None = None,
        source_session_id: str | None = None,
        source_turn_id: str | None = None,
        valid_until: str | None = None,
        accept: bool = True,
    ) -> dict[str, Any]:
        clean_text = (text or "").strip()
        clean_title = (title or "").strip()
        if not clean_title:
            first = next(
                (line.strip(" #-*>") for line in clean_text.splitlines() if line.strip()),
                "",
            )
            clean_title = first[:200] or "一条记忆"
        if not clean_text:
            clean_text = clean_title
        if scope not in FACT_SCOPES:
            raise MemoryError("invalid fact scope", 422)
        if scope == "workspace" and not project_id:
            raise MemoryError("workspace facts require project_id", 422)
        if role not in FACT_ROLES:
            raise MemoryError("invalid fact role", 422)
        if kind not in FACT_KINDS:
            raise MemoryError("invalid fact kind", 422)

        fingerprint = normalize_fingerprint(
            clean_title, kind, scope, project_id if scope == "workspace" else None
        )
        existing = self.repo_facts.find_by_fingerprint(fingerprint)
        if existing:
            return {
                "fact": existing,
                "created": False,
                "accepted": existing["status"] == "accepted",
                "needs_review": False,
                "relation": None,
            }

        if project_id:
            targets = self.repo_facts.list_facts(
                status="accepted",
                project_id=project_id,
                role=role if role in {"coding", "scholar"} else None,
                include_global=True,
                limit=500,
            )
        else:
            targets = self.repo_facts.list_facts(
                status="accepted",
                scope="global",
                role=role if role in {"coding", "scholar"} else None,
                limit=500,
            )
        candidate = {
            "id": None,
            "title": clean_title,
            "content_md": clean_text,
            "kind": kind,
            "scope": scope,
            "project_id": project_id if scope == "workspace" else None,
            "role": role,
        }
        relations = find_relations(candidate, targets, limit=3)
        blocking = [
            item
            for item in relations
            if item["relation"] in {"duplicate", "near_duplicate", "conflict"}
        ]
        needs_review = bool(blocking)
        status = "candidate" if needs_review or not accept else "accepted"
        source_ids = [source_session_id] if source_session_id else []
        fact = self.repo_facts.create_fact(
            scope=scope,
            project_id=project_id if scope == "workspace" else None,
            role=role,
            kind=kind,
            status=status,
            title=clean_title,
            content_md=clean_text,
            aliases=aliases or [],
            tags=tags or [],
            origin="quick_capture",
            source_turn_id=source_turn_id,
            source_session_ids=source_ids,
            evidence_md=(clean_text[:2000] if clean_text else ""),
            valid_until=valid_until,
        )
        return {
            "fact": fact,
            "created": True,
            "accepted": status == "accepted",
            "needs_review": needs_review,
            "relation": blocking[0] if blocking else None,
        }

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
            if kind == "final" and self.settings.memory_auto_capture == "session_end":
                self._auto_capture(session_id, summary_id, session, last_seq)
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
    def _auto_capture(
        self,
        session_id: str,
        summary_id: str,
        session: dict[str, Any],
        last_seq: int,
    ) -> None:
        if last_seq <= 0:
            return
        if self.repo_facts.active_extraction():
            logger.info("memory.auto_capture_skipped session_id=%s busy", session_id)
            return
        try:
            extraction = self.repo_facts.create_extraction(
                {
                    "role": session.get("role"),
                    "project_id": session.get("project_id"),
                    "session_ids": [session_id],
                    "max_sessions": 1,
                },
                trigger="session_end",
                source_session_id=session_id,
                source_summary_id=summary_id,
            )
        except sqlite3.IntegrityError:
            logger.info(
                "memory.auto_capture_duplicate session_id=%s summary_id=%s",
                session_id,
                summary_id,
            )
            return
        logger.info(
            "memory.auto_capture_started extraction_id=%s session_id=%s",
            extraction["id"],
            session_id,
        )
        self._run_extraction(
            extraction["id"],
            [session_id],
            session.get("project_id"),
            max_candidates=self.settings.auto_capture_max_candidates,
        )
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
        *,
        max_candidates: int | None = None,
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

            workspace = (
                self.repo_projects.get_project(project_id) if project_id else None
            )
            extraction = self.repo_facts.get_extraction(extraction_id) or {}
            role = (extraction.get("scope") or {}).get("role") or "both"
            existing_facts = self._accepted_facts_for_extraction(role, project_id)
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
            candidates.sort(
                key=lambda item: float(item.get("confidence") or 0.0),
                reverse=True,
            )
            if max_candidates is not None:
                candidates = candidates[:max_candidates]
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
                    aliases=candidate.get("aliases") or [],
                    tags=candidate.get("tags") or [],
                    origin="extraction",
                    extraction_id=extraction_id,
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

    def _accepted_facts_for_extraction(
        self, role: str, project_id: str | None
    ) -> list[dict[str, Any]]:
        """Accepted facts the extractor may target for dedupe/update.

        Scope the list to global + the current workspace; otherwise a
        workspace extraction can target a fact from another workspace.
        """
        fact_role = role if role in {"coding", "scholar"} else "both"
        if project_id:
            return self.repo_facts.list_facts(
                status="accepted",
                project_id=project_id,
                role=fact_role,
                include_global=True,
                limit=1000,
            )
        return self.repo_facts.list_facts(
            status="accepted",
            scope="global",
            role=fact_role,
            limit=1000,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def reconcile(self) -> None:
        self.repo_sessions.reconcile_summaries()
        self.repo_facts.reconcile_extractions()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
