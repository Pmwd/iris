from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable
from uuid import uuid4

from .db import Database, utcnow
from .text import build_search_text, normalize_fingerprint, query_terms


def _json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _fact(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    aliases = _json_load(data.pop("aliases_json", None), [])
    tags = _json_load(data.pop("tags_json", None), [])
    sources = _json_load(data.pop("source_session_ids_json", None), [])
    data["aliases"] = [str(a) for a in aliases] if isinstance(aliases, list) else []
    data["tags"] = [str(t) for t in tags] if isinstance(tags, list) else []
    data["source_session_ids"] = (
        [str(s) for s in sources] if isinstance(sources, list) else []
    )
    data["pinned"] = bool(data.get("pinned", 0))
    data["use_count"] = int(data.get("use_count", 0) or 0)
    return data


def _extraction(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["scope"] = _json_load(data.pop("scope_json", None), {})
    return data


class FactRepository:
    """SQL for long-term facts, their FTS index, and extraction jobs."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Facts
    # ------------------------------------------------------------------
    def _index_fact(self, fact: dict[str, Any]) -> None:
        if not self.db.fts_enabled:
            return
        search_text = fact.get("search_text") or build_search_text(
            fact.get("title") or "",
            fact.get("content_md") or "",
            fact.get("aliases") or [],
            fact.get("tags") or [],
        )
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM facts_fts WHERE fact_id = ?", (fact["id"],))
            conn.execute(
                "INSERT INTO facts_fts(fact_id, search_text) VALUES (?, ?)",
                (fact["id"], search_text),
            )

    def _unindex_fact(self, fact_id: str) -> None:
        if self.db.fts_enabled:
            self.db.execute("DELETE FROM facts_fts WHERE fact_id = ?", (fact_id,))

    def create_fact(
        self,
        *,
        scope: str,
        project_id: str | None,
        role: str,
        kind: str,
        status: str,
        title: str,
        content_md: str = "",
        aliases: Iterable[str] | None = None,
        tags: Iterable[str] | None = None,
        origin: str = "manual",
        extraction_id: str | None = None,
        source_turn_id: str | None = None,
        pinned: bool = False,
        source_session_ids: Iterable[str] | None = None,
        evidence_md: str = "",
        confidence: float | None = None,
        valid_until: str | None = None,
        supersedes_id: str | None = None,
        superseded_by_id: str | None = None,
        merged_into_id: str | None = None,
        extracted_at: str | None = None,
        reviewed_at: str | None = None,
    ) -> dict[str, Any]:
        fact_id = str(uuid4())
        now = utcnow()
        if reviewed_at is None and status in {"accepted", "rejected"}:
            reviewed_at = now
        alias_list = list(aliases or [])
        tag_list = list(tags or [])
        source_list = list(source_session_ids or [])
        fingerprint = normalize_fingerprint(
            title, kind, scope, project_id if scope == "workspace" else None
        )
        search_text = build_search_text(
            title, content_md, alias_list, tag_list
        )
        last_confirmed_at = (
            now if status == "accepted" else None
        )
        self.db.execute(
            """
            INSERT INTO facts
                (id, scope, project_id, role, kind, status, title, content_md,
                 aliases_json, tags_json, origin, extraction_id, source_turn_id,
                 pinned, source_session_ids_json, evidence_md, confidence,
                 valid_until, last_confirmed_at, supersedes_id,
                 superseded_by_id, merged_into_id, fingerprint, search_text,
                 extracted_at, reviewed_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fact_id,
                scope,
                project_id if scope == "workspace" else None,
                role,
                kind,
                status,
                title,
                content_md,
                json.dumps(alias_list, ensure_ascii=False),
                json.dumps(tag_list, ensure_ascii=False),
                origin,
                extraction_id,
                source_turn_id,
                1 if pinned else 0,
                json.dumps(source_list, ensure_ascii=False),
                evidence_md,
                confidence,
                valid_until,
                last_confirmed_at,
                supersedes_id,
                superseded_by_id,
                merged_into_id,
                fingerprint,
                search_text,
                extracted_at,
                reviewed_at,
                now,
                now,
            ),
        )
        fact = self.get_fact(fact_id)
        assert fact is not None
        if fact["status"] == "accepted":
            self._index_fact(fact)
        return fact

    def get_fact(self, fact_id: str) -> dict[str, Any] | None:
        return _fact(
            self.db.query_one("SELECT * FROM facts WHERE id = ?", (fact_id,))
        )

    def list_facts(
        self,
        status: str | None = None,
        scope: str | None = None,
        project_id: str | None = None,
        role: str | None = None,
        include_global: bool = True,
        limit: int = 500,
        q: str | None = None,
        tag: str | None = None,
        origin: str | None = None,
        stale: bool | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        if project_id and include_global:
            clauses.append("(scope = 'global' OR project_id = ?)")
            params.append(project_id)
        elif project_id:
            clauses.append("scope = 'workspace' AND project_id = ?")
            params.append(project_id)
        if role:
            clauses.append("(role = ? OR role = 'both')")
            params.append(role)
        if origin:
            clauses.append("origin = ?")
            params.append(origin)
        if tag:
            clauses.append("LOWER(COALESCE(tags_json, '')) LIKE ?")
            params.append(f"%{tag.lower()}%")
        if stale is True:
            clauses.append("valid_until IS NOT NULL AND valid_until <= ?")
            params.append(utcnow())
        elif stale is False:
            clauses.append("(valid_until IS NULL OR valid_until > ?)")
            params.append(utcnow())
        if q:
            terms = query_terms(q, limit=12)
            if terms:
                like = " OR ".join(
                    "(LOWER(title) LIKE ? OR LOWER(content_md) LIKE ? "
                    "OR LOWER(COALESCE(aliases_json, '')) LIKE ? "
                    "OR LOWER(COALESCE(tags_json, '')) LIKE ?)"
                    for _ in terms
                )
                clauses.append(f"({like})")
                for term in terms:
                    params.extend([f"%{term}%"] * 4)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self.db.query_all(
            f"""
            SELECT * FROM facts {where}
            ORDER BY pinned DESC, updated_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return [f for f in (_fact(row) for row in rows) if f is not None]

    def update_fact(
        self, fact_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {
            "scope",
            "project_id",
            "role",
            "kind",
            "status",
            "title",
            "content_md",
            "aliases",
            "tags",
            "pinned",
            "valid_until",
            "origin",
            "superseded_by_id",
            "merged_into_id",
        }
        current = self.get_fact(fact_id)
        if not current:
            return None
        merged = dict(current)
        for key, value in fields.items():
            if key not in allowed:
                continue
            if value is None and key not in {"project_id", "valid_until"}:
                continue
            merged[key] = value
        if merged.get("scope") != "workspace":
            merged["project_id"] = None
        fingerprint = normalize_fingerprint(
            merged.get("title") or "",
            merged.get("kind") or "",
            merged.get("scope") or "",
            merged.get("project_id"),
        )
        search_text = build_search_text(
            merged.get("title") or "",
            merged.get("content_md") or "",
            merged.get("aliases") or [],
            merged.get("tags") or [],
        )
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            if value is None and key not in {"project_id", "valid_until"}:
                continue
            if key == "aliases":
                assignments.append("aliases_json = ?")
                params.append(json.dumps(list(value), ensure_ascii=False))
                continue
            if key == "tags":
                assignments.append("tags_json = ?")
                params.append(json.dumps(list(value), ensure_ascii=False))
                continue
            if key == "pinned":
                assignments.append("pinned = ?")
                params.append(1 if value else 0)
                continue
            if key == "scope":
                assignments.append("scope = ?")
                params.append(value)
                continue
            if key == "project_id":
                assignments.append("project_id = ?")
                params.append(value)
                continue
            assignments.append(f"{key} = ?")
            params.append(value)
            if key == "status" and value in {"accepted", "rejected"}:
                assignments.append("reviewed_at = COALESCE(reviewed_at, ?)")
                params.append(utcnow())
                if value == "accepted":
                    assignments.append("last_confirmed_at = COALESCE(last_confirmed_at, ?)")
                    params.append(utcnow())
        if not assignments:
            return self.get_fact(fact_id)
        assignments.extend(
            [
                "fingerprint = ?",
                "search_text = ?",
                "updated_at = ?",
            ]
        )
        params.extend([fingerprint, search_text, utcnow(), fact_id])
        self.db.execute(
            f"UPDATE facts SET {', '.join(assignments)} WHERE id = ?",
            tuple(params),
        )
        fact = self.get_fact(fact_id)
        if fact:
            if fact["status"] == "accepted":
                self._index_fact(fact)
            else:
                self._unindex_fact(fact_id)
        return fact

    def accept_fact(
        self, fact_id: str, supersedes_id: str | None = None
    ) -> dict[str, Any] | None:
        """Accept a fact; if it supersedes another, archive the old one atomically."""
        if supersedes_id and supersedes_id == fact_id:
            supersedes_id = None
        now = utcnow()
        with self.db.transaction() as conn:
            if supersedes_id:
                conn.execute(
                    """
                    UPDATE facts
                    SET status = 'archived', superseded_by_id = ?,
                        last_confirmed_at = COALESCE(last_confirmed_at, ?),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (fact_id, now, now, supersedes_id),
                )
            assignments = (
                "status = 'accepted', reviewed_at = COALESCE(reviewed_at, ?), "
                "last_confirmed_at = COALESCE(last_confirmed_at, ?), "
                "updated_at = ?"
            )
            params: list[Any] = [now, now, now]
            if supersedes_id:
                assignments += ", supersedes_id = ?"
                params.append(supersedes_id)
            params.append(fact_id)
            conn.execute(
                f"UPDATE facts SET {assignments} WHERE id = ?",
                tuple(params),
            )
        fact = self.get_fact(fact_id)
        if fact:
            self._index_fact(fact)
        if supersedes_id:
            self._unindex_fact(supersedes_id)
        return fact

    def archive_fact(self, fact_id: str) -> bool:
        fact = self.get_fact(fact_id)
        if not fact:
            return False
        self.update_fact(fact_id, {"status": "archived"})
        return True

    def delete_fact(self, fact_id: str) -> bool:
        self._unindex_fact(fact_id)
        return bool(self.db.execute("DELETE FROM facts WHERE id = ?", (fact_id,)))

    def find_by_fingerprint(
        self, fingerprint: str, status: str = "accepted"
    ) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM facts WHERE fingerprint = ? AND status = ? LIMIT 1",
            (fingerprint, status),
        )
        return _fact(row)

    def confirm_fact(
        self, fact_id: str, valid_until: str | None = None
    ) -> dict[str, Any] | None:
        fact = self.get_fact(fact_id)
        if not fact:
            return None
        now = utcnow()
        self.db.execute(
            """
            UPDATE facts
            SET last_confirmed_at = ?, valid_until = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, valid_until, now, fact_id),
        )
        fact = self.get_fact(fact_id)
        if fact and fact["status"] == "accepted":
            self._index_fact(fact)
        return fact

    def merge_fact(
        self,
        source_id: str,
        target_id: str,
        *,
        content_md: str | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        source = self.get_fact(source_id)
        target = self.get_fact(target_id)
        if not source or not target or source_id == target_id:
            return None, None
        aliases = list(dict.fromkeys([*(target.get("aliases") or []), *(source.get("aliases") or [])]))
        tags = list(dict.fromkeys([*(target.get("tags") or []), *(source.get("tags") or [])]))
        sources = list(
            dict.fromkeys(
                [
                    *(target.get("source_session_ids") or []),
                    *(source.get("source_session_ids") or []),
                ]
            )
        )
        evidences = [
            item
            for item in [target.get("evidence_md"), source.get("evidence_md")]
            if item
        ]
        evidence = "\n".join(dict.fromkeys(evidences))
        now = utcnow()
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE facts
                SET aliases_json = ?, tags_json = ?, source_session_ids_json = ?,
                    evidence_md = ?, content_md = COALESCE(?, content_md),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    json.dumps(aliases, ensure_ascii=False),
                    json.dumps(tags, ensure_ascii=False),
                    json.dumps(sources, ensure_ascii=False),
                    evidence,
                    content_md,
                    now,
                    target_id,
                ),
            )
            conn.execute(
                """
                UPDATE facts
                SET status = 'archived', merged_into_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (target_id, now, source_id),
            )
        target = self.get_fact(target_id)
        source = self.get_fact(source_id)
        if target:
            target = self.update_fact(target_id, {"title": target["title"]}) or target
        if source:
            self._unindex_fact(source_id)
        return source, target

    def fact_sources(self, fact_id: str) -> dict[str, Any] | None:
        fact = self.get_fact(fact_id)
        if not fact:
            return None
        session_ids = list(fact.get("source_session_ids") or [])
        sessions: list[dict[str, Any]] = []
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            rows = self.db.query_all(
                f"""
                SELECT id, title, role, project_id, status, updated_at
                FROM sessions WHERE id IN ({placeholders})
                """,
                tuple(session_ids),
            )
            sessions = [dict(row) for row in rows]
        turns: list[dict[str, Any]] = []
        if fact.get("source_turn_id"):
            row = self.db.query_one(
                "SELECT id, session_id, seq, created_at FROM turns WHERE id = ?",
                (fact["source_turn_id"],),
            )
            if row:
                turns.append(dict(row))
        return {
            "fact_id": fact_id,
            "sessions": sessions,
            "turns": turns,
            "extraction_id": fact.get("extraction_id"),
            "source_turn_id": fact.get("source_turn_id"),
        }

    def mark_facts_used(self, fact_ids: Iterable[str]) -> None:
        ids = list(dict.fromkeys(fact_ids))
        if not ids:
            return
        now = utcnow()
        with self.db.transaction() as conn:
            for fact_id in ids:
                conn.execute(
                    """
                    UPDATE facts
                    SET use_count = use_count + 1, last_used_at = ?
                    WHERE id = ?
                    """,
                    (now, fact_id),
                )

    def accepted_context_facts(
        self, role: str, project_id: str | None
    ) -> list[dict[str, Any]]:
        if project_id:
            rows = self.db.query_all(
                """
                SELECT * FROM facts
                WHERE status = 'accepted'
                  AND (role = ? OR role = 'both')
                  AND (scope = 'global' OR (scope = 'workspace' AND project_id = ?))
                ORDER BY pinned DESC, updated_at DESC
                """,
                (role, project_id),
            )
        else:
            rows = self.db.query_all(
                """
                SELECT * FROM facts
                WHERE status = 'accepted'
                  AND (role = ? OR role = 'both')
                  AND scope = 'global'
                ORDER BY pinned DESC, updated_at DESC
                """,
                (role,),
            )
        return [f for f in (_fact(row) for row in rows) if f is not None]

    def search_facts(
        self,
        query: str,
        role: str,
        project_id: str | None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        terms = query_terms(query)
        if not terms:
            return []
        scope_clause = (
            "(scope = 'global' OR (scope = 'workspace' AND project_id = ?))"
            if project_id
            else "scope = 'global'"
        )
        by_id: dict[str, dict[str, Any]] = {}
        if self.db.fts_enabled:
            fts_query = " OR ".join(f'"{term}"' for term in terms)
            params: list[Any] = [fts_query, role]
            if project_id:
                params.append(project_id)
            params.append(limit)
            try:
                rows = self.db.query_all(
                    f"""
                    SELECT f.*, bm25(facts_fts) AS search_rank
                    FROM facts_fts
                    JOIN facts f ON f.id = facts_fts.fact_id
                    WHERE facts_fts MATCH ?
                      AND f.status = 'accepted'
                      AND (f.role = ? OR f.role = 'both')
                      AND {scope_clause}
                    ORDER BY search_rank
                    LIMIT ?
                    """,
                    tuple(params),
                )
                for row in rows:
                    fact = _fact(row) or {}
                    fact["search_rank"] = float(row["search_rank"] or 0)
                    by_id[fact["id"]] = fact
            except sqlite3.OperationalError:
                pass

        like_groups = " OR ".join(
            "(LOWER(title) LIKE ? OR LOWER(content_md) LIKE ? "
            "OR LOWER(COALESCE(aliases_json, '')) LIKE ? "
            "OR LOWER(COALESCE(tags_json, '')) LIKE ?)"
            for _ in terms
        )
        params = [role]
        if project_id:
            params.append(project_id)
        for term in terms:
            params.extend([f"%{term}%"] * 4)
        params.append(limit)
        rows = self.db.query_all(
            f"""
            SELECT * FROM facts
            WHERE status = 'accepted'
              AND (role = ? OR role = 'both')
              AND {scope_clause}
              AND ({like_groups})
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        for row in rows:
            fact = _fact(row) or {}
            if fact["id"] not in by_id:
                fact["search_rank"] = float(limit + 1)
                by_id[fact["id"]] = fact
        result = list(by_id.values())
        result.sort(key=lambda item: (item.get("search_rank", 999), item.get("updated_at") or ""))
        return result[:limit]

    # ------------------------------------------------------------------
    # Extraction jobs
    # ------------------------------------------------------------------
    def create_extraction(
        self,
        scope: dict[str, Any],
        *,
        trigger: str = "manual",
        source_session_id: str | None = None,
        source_summary_id: str | None = None,
    ) -> dict[str, Any]:
        extraction_id = str(uuid4())
        now = utcnow()
        self.db.execute(
            """
            INSERT INTO fact_extractions
                (id, status, scope_json, trigger, source_session_id,
                 source_summary_id, created_at, started_at)
            VALUES (?, 'running', ?, ?, ?, ?, ?, ?)
            """,
            (
                extraction_id,
                json.dumps(scope, ensure_ascii=False),
                trigger,
                source_session_id,
                source_summary_id,
                now,
                now,
            ),
        )
        extraction = self.get_extraction(extraction_id)
        assert extraction is not None
        return extraction

    def get_extraction(self, extraction_id: str) -> dict[str, Any] | None:
        return _extraction(
            self.db.query_one(
                "SELECT * FROM fact_extractions WHERE id = ?", (extraction_id,)
            )
        )

    def list_extractions(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            "SELECT * FROM fact_extractions ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [e for e in (_extraction(row) for row in rows) if e is not None]

    def update_extraction(
        self, extraction_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {"status", "candidate_count", "error", "ended_at"}
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            assignments.append(f"{key} = ?")
            params.append(value)
        if not assignments:
            return self.get_extraction(extraction_id)
        params.append(extraction_id)
        self.db.execute(
            f"UPDATE fact_extractions SET {', '.join(assignments)} WHERE id = ?",
            tuple(params),
        )
        return self.get_extraction(extraction_id)

    def active_extraction(self) -> dict[str, Any] | None:
        return _extraction(
            self.db.query_one(
                "SELECT * FROM fact_extractions WHERE status = 'running' "
                "ORDER BY created_at DESC LIMIT 1"
            )
        )

    def reconcile_extractions(self) -> int:
        now = utcnow()
        result = self.db.execute(
            """
            UPDATE fact_extractions
            SET status = 'failed',
                ended_at = ?,
                error = 'Iris stopped while extraction was running.'
            WHERE status = 'running'
            """,
            (now,),
        )
        return int(result or 0)
