from __future__ import annotations

import json
from typing import Any, Iterable
from uuid import uuid4

from .db import Database, utcnow


def _json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _session(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["cli_session_confirmed"] = bool(data.get("cli_session_confirmed"))
    return data


def _turn(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["prompt_manifest"] = _json_load(data.pop("prompt_manifest_json", None), {})
    data["usage"] = _json_load(data.pop("usage_json", None), {})
    return data


def _message(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["payload"] = _json_load(data.pop("payload_json", None), {})
    return data


class SessionRepository:
    """SQL for sessions, turns, raw messages, events, and summaries."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def create_session(
        self, role: str, title: str, project_id: str | None = None
    ) -> dict[str, Any]:
        session_id = str(uuid4())
        now = utcnow()
        self.db.execute(
            """
            INSERT INTO sessions
                (id, role, title, project_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?)
            """,
            (session_id, role, title, project_id, now, now),
        )
        session = self.get_session(session_id)
        assert session is not None
        return session

    def list_sessions(
        self,
        role: str | None = None,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if role:
            clauses.append("role = ?")
            params.append(role)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self.db.query_all(
            f"""
            SELECT * FROM sessions {where}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return [s for s in (_session(row) for row in rows) if s is not None]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return _session(
            self.db.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
        )

    def update_session(
        self, session_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {"title", "status"}
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            assignments.append(f"{key} = ?")
            params.append(value)
            if key == "status":
                if value == "ended":
                    assignments.append("ended_at = COALESCE(ended_at, ?)")
                    params.append(utcnow())
                elif value == "active":
                    assignments.append("ended_at = NULL")
        if not assignments:
            return self.get_session(session_id)
        assignments.append("updated_at = ?")
        params.append(utcnow())
        params.append(session_id)
        self.db.execute(
            f"UPDATE sessions SET {', '.join(assignments)} WHERE id = ?",
            tuple(params),
        )
        return self.get_session(session_id)

    def delete_session(self, session_id: str) -> bool:
        return bool(
            self.db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        )

    def count_sessions_for_project(self, project_id: str) -> int:
        row = self.db.query_one(
            "SELECT COUNT(*) AS n FROM sessions WHERE project_id = ?",
            (project_id,),
        )
        return int(row["n"]) if row else 0

    def touch_session(self, session_id: str) -> None:
        self.db.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (utcnow(), session_id),
        )

    def set_session_cli(self, session_id: str, cli_session_id: str) -> None:
        self.db.execute(
            """
            UPDATE sessions
            SET cli_session_id = ?, cli_session_confirmed = 1, updated_at = ?
            WHERE id = ?
            """,
            (cli_session_id, utcnow(), session_id),
        )

    def clear_session_cli(self, session_id: str) -> None:
        self.db.execute(
            """
            UPDATE sessions
            SET cli_session_id = NULL, cli_session_confirmed = 0, updated_at = ?
            WHERE id = ?
            """,
            (utcnow(), session_id),
        )

    def set_summary_checkpoint(self, session_id: str, turn_seq: int) -> None:
        self.db.execute(
            """
            UPDATE sessions
            SET summary_covers_turn_seq = ?, updated_at = ?
            WHERE id = ?
            """,
            (turn_seq, utcnow(), session_id),
        )

    def list_sessions_with_summaries(
        self,
        role: str | None = None,
        project_id: str | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        clauses = [
            "EXISTS (SELECT 1 FROM session_summaries ss "
            "WHERE ss.session_id = sessions.id AND ss.status = 'succeeded')"
        ]
        params: list[Any] = []
        if role:
            clauses.append("role = ?")
            params.append(role)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        params.append(limit)
        rows = self.db.query_all(
            f"""
            SELECT * FROM sessions
            WHERE {' AND '.join(clauses)}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return [s for s in (_session(row) for row in rows) if s is not None]

    # ------------------------------------------------------------------
    # Turns
    # ------------------------------------------------------------------
    def active_turn_for_session(self, session_id: str) -> dict[str, Any] | None:
        return _turn(
            self.db.query_one(
                """
                SELECT * FROM turns
                WHERE session_id = ?
                  AND status IN ('starting', 'running', 'canceling')
                ORDER BY seq DESC
                LIMIT 1
                """,
                (session_id,),
            )
        )

    def active_coding_turn_for_project(
        self, project_id: str
    ) -> dict[str, Any] | None:
        return _turn(
            self.db.query_one(
                """
                SELECT * FROM turns
                WHERE project_id = ?
                  AND role = 'coding'
                  AND status IN ('starting', 'running', 'canceling')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (project_id,),
            )
        )

    def create_turn(
        self,
        *,
        turn_id: str,
        session_id: str,
        role: str,
        project_id: str | None,
        mode: str,
        permission_profile: str,
        cli_session_id: str,
        context_manifest: dict[str, Any],
        raw_log_path: str,
    ) -> dict[str, Any]:
        now = utcnow()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS n FROM turns WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            seq = int(row["n"]) + 1
            conn.execute(
                """
                INSERT INTO turns
                    (id, session_id, seq, role, project_id, status, mode,
                     permission_profile, cli_session_id, prompt_manifest_json,
                     raw_log_path, created_at)
                VALUES (?, ?, ?, ?, ?, 'starting', ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id,
                    session_id,
                    seq,
                    role,
                    project_id,
                    mode,
                    permission_profile,
                    cli_session_id,
                    json.dumps(context_manifest, ensure_ascii=False),
                    raw_log_path,
                    now,
                ),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
        turn = self.get_turn(turn_id)
        assert turn is not None
        return turn

    def get_turn(self, turn_id: str) -> dict[str, Any] | None:
        return _turn(
            self.db.query_one("SELECT * FROM turns WHERE id = ?", (turn_id,))
        )

    def list_turns(
        self, session_id: str, limit: int = 500
    ) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """
            SELECT * FROM turns
            WHERE session_id = ?
            ORDER BY seq ASC
            LIMIT ?
            """,
            (session_id, limit),
        )
        return [t for t in (_turn(row) for row in rows) if t is not None]

    def list_turns_since(
        self, session_id: str, after_seq: int, limit: int = 200
    ) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """
            SELECT * FROM turns
            WHERE session_id = ? AND seq > ?
            ORDER BY seq ASC
            LIMIT ?
            """,
            (session_id, after_seq, limit),
        )
        return [t for t in (_turn(row) for row in rows) if t is not None]

    def set_turn_running(self, turn_id: str, pid: int) -> None:
        self.db.execute(
            """
            UPDATE turns
            SET status = 'running', pid = ?, started_at = COALESCE(started_at, ?)
            WHERE id = ?
            """,
            (pid, utcnow(), turn_id),
        )

    def set_turn_canceling(self, turn_id: str) -> None:
        self.db.execute(
            "UPDATE turns SET status = 'canceling' WHERE id = ?", (turn_id,)
        )

    def set_turn_exit_code(self, turn_id: str, exit_code: int | None) -> None:
        self.db.execute(
            "UPDATE turns SET exit_code = ? WHERE id = ?", (exit_code, turn_id)
        )

    def finish_turn(
        self,
        turn_id: str,
        session_id: str,
        status: str,
        *,
        result_text: str | None = None,
        cli_session_id: str | None = None,
        cost_usd: float | None = None,
        usage: dict[str, Any] | None = None,
        exit_code: int | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        add_result_message: bool = True,
    ) -> None:
        now = utcnow()
        usage_json = json.dumps(usage, ensure_ascii=False) if usage is not None else None
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE turns
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
                    cli_session_id,
                    cost_usd,
                    usage_json,
                    exit_code,
                    error_type,
                    error_message,
                    turn_id,
                ),
            )
            if status == "succeeded" and cli_session_id:
                conn.execute(
                    """
                    UPDATE sessions
                    SET cli_session_id = ?, cli_session_confirmed = 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (cli_session_id, now, session_id),
                )
            else:
                conn.execute(
                    "UPDATE sessions SET updated_at = ? WHERE id = ?",
                    (now, session_id),
                )
            if status == "succeeded" and result_text is not None and add_result_message:
                row = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) AS n FROM messages WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                seq = int(row["n"]) + 1
                conn.execute(
                    """
                    INSERT INTO messages
                        (id, session_id, turn_id, seq, role, kind, content,
                         payload_json, created_at)
                    VALUES (?, ?, ?, ?, 'assistant', 'result', ?, '{}', ?)
                    """,
                    (str(uuid4()), session_id, turn_id, seq, result_text, now),
                )

    def reconcile_interrupted_turns(self) -> int:
        now = utcnow()
        with self.db.transaction() as conn:
            result = conn.execute(
                """
                UPDATE turns
                SET status = 'interrupted',
                    ended_at = ?,
                    error_type = 'service_restart',
                    error_message = 'Iris stopped while this turn was active.'
                WHERE status IN ('starting', 'running', 'canceling')
                """,
                (now,),
            )
            return result.rowcount

    def add_turn_event(
        self,
        turn_id: str,
        seq: int,
        kind: str,
        payload: Any,
        truncated: bool = False,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO turn_events
                (turn_id, seq, kind, payload_json, truncated, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                turn_id,
                seq,
                kind,
                json.dumps(payload, ensure_ascii=False),
                1 if truncated else 0,
                utcnow(),
            ),
        )

    def list_turn_events(
        self, turn_id: str, after_seq: int = 0, limit: int = 500
    ) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """
            SELECT * FROM turn_events
            WHERE turn_id = ? AND seq > ?
            ORDER BY seq ASC
            LIMIT ?
            """,
            (turn_id, after_seq, limit),
        )
        events: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["payload"] = _json_load(data.pop("payload_json", None), {})
            events.append(data)
        return events

    def tool_uses(self, turn_id: str) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """
            SELECT payload_json FROM turn_events
            WHERE turn_id = ? AND kind = 'tool.use'
            ORDER BY seq ASC
            """,
            (turn_id,),
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            payload = _json_load(row["payload_json"], {})
            if isinstance(payload, dict):
                result.append(payload)
        return result

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------
    def add_message(
        self,
        *,
        session_id: str,
        role: str,
        kind: str,
        content: str,
        turn_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message_id = str(uuid4())
        now = utcnow()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS n FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            seq = int(row["n"]) + 1
            conn.execute(
                """
                INSERT INTO messages
                    (id, session_id, turn_id, seq, role, kind, content,
                     payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    session_id,
                    turn_id,
                    seq,
                    role,
                    kind,
                    content,
                    json.dumps(payload or {}, ensure_ascii=False),
                    now,
                ),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
        message = _message(
            self.db.query_one("SELECT * FROM messages WHERE id = ?", (message_id,))
        )
        assert message is not None
        return message

    def list_messages(
        self, session_id: str, after_seq: int = 0, limit: int = 500
    ) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """
            SELECT * FROM messages
            WHERE session_id = ? AND seq > ?
            ORDER BY seq ASC
            LIMIT ?
            """,
            (session_id, after_seq, limit),
        )
        return [m for m in (_message(row) for row in rows) if m is not None]

    def summary_progress(
        self, session_id: str, covers_turn_seq: int
    ) -> tuple[int, int]:
        row = self.db.query_one(
            """
            SELECT COUNT(DISTINCT t.id) AS turns,
                   COALESCE(SUM(LENGTH(m.content)), 0) AS chars
            FROM turns t
            LEFT JOIN messages m ON m.turn_id = t.id
            WHERE t.session_id = ?
              AND t.status = 'succeeded'
              AND t.seq > ?
            """,
            (session_id, covers_turn_seq),
        )
        if not row:
            return 0, 0
        return int(row["turns"] or 0), int(row["chars"] or 0)

    # ------------------------------------------------------------------
    # Summaries
    # ------------------------------------------------------------------
    def create_summary(
        self, session_id: str, kind: str, covers_through_turn_seq: int = 0
    ) -> dict[str, Any]:
        summary_id = str(uuid4())
        now = utcnow()
        self.db.execute(
            """
            INSERT INTO session_summaries
                (id, session_id, kind, status, covers_through_turn_seq,
                 created_at, updated_at)
            VALUES (?, ?, ?, 'pending', ?, ?, ?)
            """,
            (summary_id, session_id, kind, covers_through_turn_seq, now, now),
        )
        summary = self.get_summary(summary_id)
        assert summary is not None
        return summary

    def get_summary(self, summary_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM session_summaries WHERE id = ?", (summary_id,)
        )
        return dict(row) if row else None

    def update_summary(
        self, summary_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {
            "status",
            "content_md",
            "covers_through_turn_seq",
            "model",
            "cost_usd",
            "error",
            "completed_at",
        }
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            assignments.append(f"{key} = ?")
            params.append(value)
        if not assignments:
            return self.get_summary(summary_id)
        assignments.append("updated_at = ?")
        params.append(utcnow())
        params.append(summary_id)
        self.db.execute(
            f"UPDATE session_summaries SET {', '.join(assignments)} WHERE id = ?",
            tuple(params),
        )
        return self.get_summary(summary_id)

    def list_summaries(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """
            SELECT * FROM session_summaries
            WHERE session_id = ?
            ORDER BY created_at DESC
            """,
            (session_id,),
        )
        return [dict(row) for row in rows]

    def latest_summary(
        self, session_id: str, status: str | None = "succeeded"
    ) -> dict[str, Any] | None:
        if status:
            row = self.db.query_one(
                """
                SELECT * FROM session_summaries
                WHERE session_id = ? AND status = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id, status),
            )
        else:
            row = self.db.query_one(
                """
                SELECT * FROM session_summaries
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id,),
            )
        return dict(row) if row else None

    def active_summary(self, session_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            """
            SELECT * FROM session_summaries
            WHERE session_id = ? AND status IN ('pending', 'running')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (session_id,),
        )
        return dict(row) if row else None

    def latest_summaries_for_sessions(
        self, session_ids: Iterable[str]
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for session_id in session_ids:
            summary = self.latest_summary(session_id, "succeeded")
            if summary:
                result[session_id] = summary
        return result

    def reconcile_summaries(self) -> int:
        now = utcnow()
        result = self.db.execute(
            """
            UPDATE session_summaries
            SET status = 'failed',
                error = 'Iris stopped while the summary was running.',
                completed_at = ?
            WHERE status IN ('pending', 'running')
            """,
            (now,),
        )
        return int(result or 0)
