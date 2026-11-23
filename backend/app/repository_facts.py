from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Iterable
from uuid import uuid4

from .db import Database, utcnow
from .text import query_terms


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
    sources = _json_load(data.pop("source_session_ids_json", None), [])
    data["aliases"] = [str(a) for a in aliases] if isinstance(aliases, list) else []
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


def normalize_fingerprint(title: str, kind: str, scope: str, project_id: str | None) -> str:
    text = re.sub(r"\s+", " ", (title or "").strip().lower())
    return f"{kind}|{scope}|{project_id or ''}|{text}"


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
        aliases = " ".join(str(a) for a in fact.get("aliases") or [])
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM facts_fts WHERE fact_id = ?", (fact["id"],))
            conn.execute(
                """
                INSERT INTO facts_fts(fact_id, title, content)
                VALUES (?, ?, ?)
                """,
                (
                    fact["id"],
                    fact["title"],
                    fact["content_md"]
                    + ("\n" + aliases if aliases else ""),
                ),
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
        pinned: bool = False,
        source_session_ids: Iterable[str] | None = None,
        evidence_md: str = "",
        confidence: float | None = None,
        supersedes_id: str | None = None,
        extracted_at: str | None = None,
        reviewed_at: str | None = None,
    ) -> dict[str, Any]:
        fact_id = str(uuid4())
        now = utcnow()
        if reviewed_at is None and status in {"accepted", "rejected"}:
            reviewed_at = now
        self.db.execute(
            """
            INSERT INTO facts
                (id, scope, project_id, role, kind, status, title, content_md,
                 aliases_json, pinned, source_session_ids_json, evidence_md,
                 confidence, supersedes_id, extracted_at, reviewed_at,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json.dumps(list(aliases or []), ensure_ascii=False),
                1 if pinned else 0,
                json.dumps(list(source_session_ids or []), ensure_ascii=False),
                evidence_md,
                confidence,
                supersedes_id,
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
            "pinned",
        }
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            if key == "aliases":
                assignments.append("aliases_json = ?")
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
        if not assignments:
            return self.get_fact(fact_id)
        assignments.append("updated_at = ?")
        params.append(utcnow())
        params.append(fact_id)
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
                    SET status = 'archived', updated_at = ?
                    WHERE id = ?
                    """,
                    (now, supersedes_id),
                )
            assignments = "status = 'accepted', reviewed_at = COALESCE(reviewed_at, ?), updated_at = ?"
            params: list[Any] = [now, now]
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
                if rows:
                    result = []
                    for row in rows:
                        fact = _fact(row) or {}
                        fact["search_rank"] = float(row["search_rank"] or 0)
                        result.append(fact)
                    return result
            except sqlite3.OperationalError:
                pass

        like_groups = " OR ".join(
            "(LOWER(title) LIKE ? OR LOWER(content_md) LIKE ? "
            "OR LOWER(COALESCE(aliases_json, '')) LIKE ?)"
            for _ in terms
        )
        params = [role]
        if project_id:
            params.append(project_id)
        for term in terms:
            params.extend([f"%{term}%", f"%{term}%", f"%{term}%"])
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
        result = []
        for row in rows:
            fact = _fact(row) or {}
            fact["search_rank"] = 0.0
            result.append(fact)
        return result

    # ------------------------------------------------------------------
    # Extraction jobs
    # ------------------------------------------------------------------
    def create_extraction(self, scope: dict[str, Any]) -> dict[str, Any]:
        extraction_id = str(uuid4())
        now = utcnow()
        self.db.execute(
            """
            INSERT INTO fact_extractions
                (id, status, scope_json, created_at, started_at)
            VALUES (?, 'running', ?, ?, ?)
            """,
            (extraction_id, json.dumps(scope, ensure_ascii=False), now, now),
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
