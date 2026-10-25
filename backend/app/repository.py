from __future__ import annotations

import json
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


def _note(row: Any | None, scope: str) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    aliases = _json_load(data.pop("aliases_json", None), [])
    data["aliases"] = (
        [str(alias) for alias in aliases] if isinstance(aliases, list) else []
    )
    data["scope"] = scope
    data["pinned"] = bool(data.get("pinned", 0))
    data["use_count"] = int(data.get("use_count", 0) or 0)
    return data


def _project(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["allowed_tools"] = _json_load(data.pop("allowed_tools_json", None), [])
    return data


def _run(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["context_manifest"] = _json_load(data.pop("context_manifest_json", None), {})
    data["usage"] = _json_load(data.pop("usage_json", None), {})
    return data


def _event(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["payload"] = _json_load(data.pop("payload_json", None), {})
    return data


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------
    def create_project(
        self,
        name: str,
        workspace_path: str,
        brief_md: str = "",
        allowed_tools: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        project_id = str(uuid4())
        now = utcnow()
        self.db.execute(
            """
            INSERT INTO projects
                (id, name, workspace_path, brief_md, allowed_tools_json,
                 trusted_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                name,
                workspace_path,
                brief_md,
                json.dumps(list(allowed_tools or []), ensure_ascii=False),
                now,
                now,
                now,
            ),
        )
        project = self.get_project(project_id)
        assert project is not None
        return project

    def list_projects(self, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE archived_at IS NULL"
        rows = self.db.query_all(
            f"SELECT * FROM projects {where} ORDER BY created_at DESC"
        )
        return [p for p in (_project(row) for row in rows) if p is not None]

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        return _project(
            self.db.query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        )

    def update_project(self, project_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"name", "workspace_path", "brief_md", "allowed_tools", "archived"}
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            if key == "allowed_tools":
                assignments.append("allowed_tools_json = ?")
                params.append(json.dumps(list(value), ensure_ascii=False))
            elif key == "archived":
                assignments.append("archived_at = ?")
                params.append(utcnow() if value else None)
            else:
                assignments.append(f"{key} = ?")
                params.append(value)
        if not assignments:
            return self.get_project(project_id)
        assignments.append("updated_at = ?")
        params.append(utcnow())
        params.append(project_id)
        self.db.execute(
            f"UPDATE projects SET {', '.join(assignments)} WHERE id = ?",
            tuple(params),
        )
        return self.get_project(project_id)

    def delete_project(self, project_id: str) -> bool:
        if self.db.fts_enabled:
            self.db.execute(
                "DELETE FROM notes_fts WHERE project_id = ?", (project_id,)
            )
        return bool(
            self.db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        )

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------
    def create_task(
        self,
        project_id: str,
        title: str,
        goal_md: str = "",
        role: str = "coding",
        source_task_id: str | None = None,
    ) -> dict[str, Any]:
        task_id = str(uuid4())
        now = utcnow()
        self.db.execute(
            """
            INSERT INTO tasks
                (id, project_id, title, goal_md, role, source_task_id,
                 status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'ready', ?, ?)
            """,
            (task_id, project_id, title, goal_md, role, source_task_id, now, now),
        )
        task = self.get_task(task_id)
        assert task is not None
        return task

    def list_tasks(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            "SELECT * FROM tasks WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        )
        return [dict(row) for row in rows]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return dict(row) if row else None

    def update_task(self, task_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"title", "goal_md"}
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            if key in allowed and value is not None:
                assignments.append(f"{key} = ?")
                params.append(value)
        if not assignments:
            return self.get_task(task_id)
        assignments.append("updated_at = ?")
        params.append(utcnow())
        params.append(task_id)
        self.db.execute(
            f"UPDATE tasks SET {', '.join(assignments)} WHERE id = ?",
            tuple(params),
        )
        return self.get_task(task_id)

    def set_task_status(
        self, task_id: str, status: str, session_id: str | None = None
    ) -> None:
        now = utcnow()
        if session_id is None:
            self.db.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, task_id),
            )
        else:
            self.db.execute(
                """
                UPDATE tasks
                SET status = ?, current_session_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, session_id, now, task_id),
            )

    def delete_task(self, task_id: str) -> bool:
        return bool(self.db.execute("DELETE FROM tasks WHERE id = ?", (task_id,)))

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------
    def create_run(
        self,
        task_id: str,
        session_id: str,
        permission_profile: str,
        workspace_path: str,
        context_manifest: dict[str, Any],
        prompt_version: str,
    ) -> dict[str, Any]:
        run_id = str(uuid4())
        now = utcnow()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(attempt_no), 0) AS n FROM runs WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            attempt_no = int(row["n"]) + 1
            conn.execute(
                """
                INSERT INTO runs
                    (id, task_id, attempt_no, status, cli_session_id,
                     permission_profile, prompt_version, workspace_path,
                     context_manifest_json, created_at)
                VALUES (?, ?, ?, 'starting', ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    task_id,
                    attempt_no,
                    session_id,
                    permission_profile,
                    prompt_version,
                    workspace_path,
                    json.dumps(context_manifest, ensure_ascii=False),
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE tasks
                SET status = 'running', current_session_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (session_id, now, task_id),
            )
        run = self.get_run(run_id)
        assert run is not None
        return run

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return _run(
            self.db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,))
        )

    def list_runs(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            "SELECT * FROM runs WHERE task_id = ? ORDER BY attempt_no DESC",
            (task_id,),
        )
        return [r for r in (_run(row) for row in rows) if r is not None]

    def active_run_for_project(self, project_id: str) -> dict[str, Any] | None:
        return _run(
            self.db.query_one(
                """
                SELECT r.*
                FROM runs r
                JOIN tasks t ON t.id = r.task_id
                WHERE t.project_id = ?
                  AND r.status IN ('starting', 'running', 'canceling')
                ORDER BY r.created_at DESC
                LIMIT 1
                """,
                (project_id,),
            )
        )

    def set_run_running(self, run_id: str, pid: int) -> None:
        self.db.execute(
            """
            UPDATE runs
            SET status = 'running', pid = ?, started_at = COALESCE(started_at, ?)
            WHERE id = ?
            """,
            (pid, utcnow(), run_id),
        )

    def set_run_canceling(self, run_id: str) -> None:
        self.db.execute(
            "UPDATE runs SET status = 'canceling' WHERE id = ?", (run_id,)
        )

    def finish_run(
        self,
        run_id: str,
        task_id: str,
        status: str,
        *,
        result_text: str | None = None,
        session_id: str | None = None,
        cost_usd: float | None = None,
        usage: dict[str, Any] | None = None,
        exit_code: int | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        task_status = {
            "succeeded": "needs_review",
            "failed": "failed",
            "canceled": "canceled",
            "interrupted": "interrupted",
        }.get(status, "failed")
        now = utcnow()
        usage_json = json.dumps(usage, ensure_ascii=False) if usage is not None else None
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE runs
                SET status = ?,
                    ended_at = ?,
                    result_text = COALESCE(?, result_text),
                    cli_session_id = COALESCE(?, cli_session_id),
                    cost_usd = COALESCE(?, cost_usd),
                    usage_json = COALESCE(?, usage_json),
                    exit_code = COALESCE(?, exit_code),
                    error_type = ?,
                    error_message = ?
                WHERE id = ?
                """,
                (
                    status,
                    now,
                    result_text,
                    session_id,
                    cost_usd,
                    usage_json,
                    exit_code,
                    error_type,
                    error_message,
                    run_id,
                ),
            )
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?,
                    current_session_id = COALESCE(?, current_session_id)
                WHERE id = ?
                """,
                (task_status, now, session_id, task_id),
            )

    def reconcile_interrupted_runs(self) -> int:
        now = utcnow()
        with self.db.transaction() as conn:
            result = conn.execute(
                """
                UPDATE runs
                SET status = 'interrupted',
                    ended_at = ?,
                    error_type = 'service_restart',
                    error_message = 'Iris stopped while this run was active.'
                WHERE status IN ('starting', 'running', 'canceling')
                """,
                (now,),
            )
            conn.execute(
                """
                UPDATE tasks
                SET status = 'interrupted', updated_at = ?
                WHERE status = 'running'
                """,
                (now,),
            )
            return result.rowcount

    def add_event(
        self,
        run_id: str,
        seq: int,
        kind: str,
        payload: Any,
        truncated: bool = False,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO run_events
                (run_id, seq, kind, created_at, payload_json, truncated)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                seq,
                kind,
                utcnow(),
                json.dumps(payload, ensure_ascii=False),
                1 if truncated else 0,
            ),
        )

    def list_events(
        self, run_id: str, after_seq: int = 0, limit: int = 500
    ) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """
            SELECT * FROM run_events
            WHERE run_id = ? AND seq > ?
            ORDER BY seq ASC
            LIMIT ?
            """,
            (run_id, after_seq, limit),
        )
        return [_event(row) for row in rows]

    # ------------------------------------------------------------------
    # Notes and context search
    # ------------------------------------------------------------------
    def _index_note(self, note: dict[str, Any]) -> None:
        if not self.db.fts_enabled:
            return
        aliases = " ".join(str(alias) for alias in note.get("aliases") or [])
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM notes_fts WHERE note_id = ?", (note["id"],))
            conn.execute(
                """
                INSERT INTO notes_fts(note_id, project_id, title, content)
                VALUES (?, ?, ?, ?)
                """,
                (
                    note["id"],
                    note["project_id"],
                    note["title"],
                    note["content_md"] + ("\n" + aliases if aliases else ""),
                ),
            )

    def _unindex_note(self, note_id: str) -> None:
        if self.db.fts_enabled:
            self.db.execute("DELETE FROM notes_fts WHERE note_id = ?", (note_id,))

    def _index_global_note(self, note: dict[str, Any]) -> None:
        if not self.db.fts_enabled:
            return
        aliases = " ".join(str(alias) for alias in note.get("aliases") or [])
        with self.db.transaction() as conn:
            conn.execute(
                "DELETE FROM global_notes_fts WHERE note_id = ?", (note["id"],)
            )
            conn.execute(
                """
                INSERT INTO global_notes_fts(note_id, title, content)
                VALUES (?, ?, ?)
                """,
                (
                    note["id"],
                    note["title"],
                    note["content_md"] + ("\n" + aliases if aliases else ""),
                ),
            )

    def _unindex_global_note(self, note_id: str) -> None:
        if self.db.fts_enabled:
            self.db.execute(
                "DELETE FROM global_notes_fts WHERE note_id = ?", (note_id,)
            )

    def create_note(
        self,
        project_id: str,
        title: str,
        content_md: str,
        kind: str = "outcome",
        status: str = "accepted",
        task_id: str | None = None,
        source_run_id: str | None = None,
        pinned: bool = False,
        aliases: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        note_id = str(uuid4())
        now = utcnow()
        accepted_at = now if status == "accepted" else None
        self.db.execute(
            """
            INSERT INTO notes
                (id, project_id, task_id, source_run_id, kind, status,
                 title, content_md, aliases_json, pinned,
                 created_at, updated_at, accepted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                note_id,
                project_id,
                task_id,
                source_run_id,
                kind,
                status,
                title,
                content_md,
                json.dumps(list(aliases or []), ensure_ascii=False),
                1 if pinned else 0,
                now,
                now,
                accepted_at,
            ),
        )
        note = self.get_note(note_id)
        assert note is not None
        self._index_note(note)
        return note

    def list_notes(
        self, project_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        if status:
            rows = self.db.query_all(
                """
                SELECT * FROM notes
                WHERE project_id = ? AND status = ?
                ORDER BY pinned DESC, created_at DESC
                """,
                (project_id, status),
            )
        else:
            rows = self.db.query_all(
                """
                SELECT * FROM notes
                WHERE project_id = ?
                ORDER BY pinned DESC, created_at DESC
                """,
                (project_id,),
            )
        return [n for n in (_note(row, "project") for row in rows) if n is not None]

    def accepted_notes(self, project_id: str) -> list[dict[str, Any]]:
        return self.list_notes(project_id, status="accepted")

    def accepted_notes_for_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """
            SELECT * FROM notes
            WHERE task_id = ? AND status = 'accepted'
            ORDER BY created_at DESC
            """,
            (task_id,),
        )
        return [n for n in (_note(row, "project") for row in rows) if n is not None]

    def get_note(self, note_id: str) -> dict[str, Any] | None:
        return _note(
            self.db.query_one("SELECT * FROM notes WHERE id = ?", (note_id,)),
            "project",
        )

    def update_note(self, note_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"title", "content_md", "status", "pinned", "aliases"}
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            if key == "pinned":
                assignments.append("pinned = ?")
                params.append(1 if value else 0)
                continue
            if key == "aliases":
                assignments.append("aliases_json = ?")
                params.append(json.dumps(list(value), ensure_ascii=False))
                continue
            assignments.append(f"{key} = ?")
            params.append(value)
            if key == "status" and value == "accepted":
                assignments.append("accepted_at = COALESCE(accepted_at, ?)")
                params.append(utcnow())
        if not assignments:
            return self.get_note(note_id)
        assignments.append("updated_at = ?")
        params.append(utcnow())
        params.append(note_id)
        self.db.execute(
            f"UPDATE notes SET {', '.join(assignments)} WHERE id = ?",
            tuple(params),
        )
        note = self.get_note(note_id)
        if note:
            self._index_note(note)
        return note

    def delete_note(self, note_id: str) -> bool:
        self._unindex_note(note_id)
        return bool(self.db.execute("DELETE FROM notes WHERE id = ?", (note_id,)))

    # ------------------------------------------------------------------
    # Global notes
    # ------------------------------------------------------------------
    def create_global_note(
        self,
        title: str,
        content_md: str,
        kind: str = "note",
        status: str = "accepted",
        pinned: bool = False,
        aliases: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        note_id = str(uuid4())
        now = utcnow()
        accepted_at = now if status == "accepted" else None
        self.db.execute(
            """
            INSERT INTO global_notes
                (id, kind, status, title, content_md, aliases_json, pinned,
                 created_at, updated_at, accepted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                note_id,
                kind,
                status,
                title,
                content_md,
                json.dumps(list(aliases or []), ensure_ascii=False),
                1 if pinned else 0,
                now,
                now,
                accepted_at,
            ),
        )
        note = self.get_global_note(note_id)
        assert note is not None
        self._index_global_note(note)
        return note

    def list_global_notes(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            rows = self.db.query_all(
                """
                SELECT * FROM global_notes
                WHERE status = ?
                ORDER BY pinned DESC, created_at DESC
                """,
                (status,),
            )
        else:
            rows = self.db.query_all(
                "SELECT * FROM global_notes ORDER BY pinned DESC, created_at DESC"
            )
        return [n for n in (_note(row, "global") for row in rows) if n is not None]

    def accepted_global_notes(self) -> list[dict[str, Any]]:
        return self.list_global_notes(status="accepted")

    def get_global_note(self, note_id: str) -> dict[str, Any] | None:
        return _note(
            self.db.query_one("SELECT * FROM global_notes WHERE id = ?", (note_id,)),
            "global",
        )

    def update_global_note(
        self, note_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {"title", "content_md", "status", "pinned", "aliases"}
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            if key == "pinned":
                assignments.append("pinned = ?")
                params.append(1 if value else 0)
                continue
            if key == "aliases":
                assignments.append("aliases_json = ?")
                params.append(json.dumps(list(value), ensure_ascii=False))
                continue
            assignments.append(f"{key} = ?")
            params.append(value)
            if key == "status" and value == "accepted":
                assignments.append("accepted_at = COALESCE(accepted_at, ?)")
                params.append(utcnow())
        if not assignments:
            return self.get_global_note(note_id)
        assignments.append("updated_at = ?")
        params.append(utcnow())
        params.append(note_id)
        self.db.execute(
            f"UPDATE global_notes SET {', '.join(assignments)} WHERE id = ?",
            tuple(params),
        )
        note = self.get_global_note(note_id)
        if note:
            self._index_global_note(note)
        return note

    def delete_global_note(self, note_id: str) -> bool:
        self._unindex_global_note(note_id)
        return bool(
            self.db.execute("DELETE FROM global_notes WHERE id = ?", (note_id,))
        )

    def mark_notes_used(self, notes: Iterable[dict[str, Any]]) -> None:
        now = utcnow()
        with self.db.transaction() as conn:
            for note in notes:
                scope = note.get("scope")
                if scope not in {"project", "global"}:
                    continue
                table = "notes" if scope == "project" else "global_notes"
                conn.execute(
                    f"""
                    UPDATE {table}
                    SET use_count = use_count + 1, last_used_at = ?
                    WHERE id = ?
                    """,
                    (now, note["id"]),
                )

    # ------------------------------------------------------------------
    # Context search
    # ------------------------------------------------------------------
    def search_project_notes(
        self, project_id: str, query: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        terms = query_terms(query)
        if not terms:
            return []
        if self.db.fts_enabled:
            fts_query = " OR ".join(f'"{term}"' for term in terms)
            try:
                rows = self.db.query_all(
                    """
                    SELECT n.*, bm25(notes_fts) AS search_rank
                    FROM notes_fts
                    JOIN notes n ON n.id = notes_fts.note_id
                    WHERE notes_fts MATCH ?
                      AND n.project_id = ?
                      AND n.status = 'accepted'
                    ORDER BY search_rank
                    LIMIT ?
                    """,
                    (fts_query, project_id, limit),
                )
                if rows:
                    return [
                        {
                            **(_note(row, "project") or {}),
                            "search_rank": float(row["search_rank"] or 0),
                        }
                        for row in rows
                    ]
            except sqlite3.OperationalError:
                pass

        where = " OR ".join(
            "(LOWER(title) LIKE ? OR LOWER(content_md) LIKE ? "
            "OR LOWER(COALESCE(aliases_json, '')) LIKE ?)"
            for _ in terms
        )
        params: list[Any] = [project_id]
        for term in terms:
            pattern = f"%{term}%"
            params.extend([pattern, pattern, pattern])
        params.append(limit)
        rows = self.db.query_all(
            f"""
            SELECT * FROM notes
            WHERE project_id = ? AND status = 'accepted'
              AND ({where})
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return [
            {**(_note(row, "project") or {}), "search_rank": 0.0}
            for row in rows
        ]

    def search_global_notes(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        terms = query_terms(query)
        if not terms:
            return []
        if self.db.fts_enabled:
            fts_query = " OR ".join(f'"{term}"' for term in terms)
            try:
                rows = self.db.query_all(
                    """
                    SELECT g.*, bm25(global_notes_fts) AS search_rank
                    FROM global_notes_fts
                    JOIN global_notes g ON g.id = global_notes_fts.note_id
                    WHERE global_notes_fts MATCH ?
                      AND g.status = 'accepted'
                    ORDER BY search_rank
                    LIMIT ?
                    """,
                    (fts_query, limit),
                )
                if rows:
                    return [
                        {
                            **(_note(row, "global") or {}),
                            "search_rank": float(row["search_rank"] or 0),
                        }
                        for row in rows
                    ]
            except sqlite3.OperationalError:
                pass

        where = " OR ".join(
            "(LOWER(title) LIKE ? OR LOWER(content_md) LIKE ? "
            "OR LOWER(COALESCE(aliases_json, '')) LIKE ?)"
            for _ in terms
        )
        params: list[Any] = []
        for term in terms:
            pattern = f"%{term}%"
            params.extend([pattern, pattern, pattern])
        params.append(limit)
        rows = self.db.query_all(
            f"""
            SELECT * FROM global_notes
            WHERE status = 'accepted' AND ({where})
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return [
            {**(_note(row, "global") or {}), "search_rank": 0.0}
            for row in rows
        ]
