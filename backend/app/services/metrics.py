from __future__ import annotations

import json
import math
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..config import Settings, resolve_claude_executable
from ..db import Database, utcnow
from .health import probe_cli

RANGES = {"24h": 24 * 3600, "7d": 7 * 24 * 3600, "30d": 30 * 24 * 3600}
ACTIVE_STATUSES = ("starting", "running", "canceling")
TERMINAL_STATUSES = ("succeeded", "failed", "canceled", "interrupted")


def _iso_since(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(
        timespec="seconds"
    )


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _delta_seconds(start: str | None, end: str | None) -> float | None:
    begin = _parse_time(start)
    finish = _parse_time(end)
    if begin is None or finish is None:
        return None
    return max(0.0, (finish - begin).total_seconds())


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 2)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (
        position - lower
    )
    return round(value, 2)


def _clauses(alias: str, role: str | None, project_id: str | None) -> tuple[list[str], list[Any]]:
    parts: list[str] = []
    params: list[Any] = []
    if role:
        parts.append(f"{alias}.role = ?")
        params.append(role)
    if project_id:
        parts.append(f"{alias}.project_id = ?")
        params.append(project_id)
    return parts, params


def _fact_clauses(role: str | None, project_id: str | None) -> tuple[list[str], list[Any]]:
    parts: list[str] = []
    params: list[Any] = []
    if role:
        parts.append("(f.role = ? OR f.role = 'both')")
        params.append(role)
    if project_id:
        parts.append("(f.scope = 'global' OR f.project_id = ?)")
        params.append(project_id)
    return parts, params


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


class MetricsService:
    """Minimal SQL-backed metrics for the M1 observability layer.

    Deliberately excludes timeseries, rollups, alerts, and content fields.
    """

    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------
    def overview(
        self,
        *,
        role: str | None = None,
        project_id: str | None = None,
        window: str = "24h",
    ) -> dict[str, Any]:
        if window not in RANGES:
            raise ValueError("range must be 24h, 7d, or 30d")
        since = _iso_since(RANGES[window])

        clauses, params = _clauses("t", role, project_id)
        where = ["t.created_at >= ?", *clauses]
        turns = [
            dict(row)
            for row in self.db.query_all(
                f"""
                SELECT t.id, t.session_id, t.status, t.mode, t.created_at,
                       t.started_at, t.ended_at, t.cost_usd, t.error_type,
                       t.prompt_manifest_json
                FROM turns t
                WHERE {' AND '.join(where)}
                """,
                (since, *params),
            )
        ]

        active_clauses, active_params = _clauses("t", role, project_id)
        active_where = [
            "t.status IN ('starting','running','canceling')",
            *active_clauses,
        ]
        active_rows = [
            dict(row)
            for row in self.db.query_all(
                f"""
                SELECT t.id, t.status, t.started_at
                FROM turns t
                WHERE {' AND '.join(active_where)}
                """,
                tuple(active_params),
            )
        ]
        stuck_before = (
            datetime.now(timezone.utc)
            - timedelta(seconds=self.settings.run_timeout_seconds)
        ).isoformat(timespec="seconds")
        stuck = sum(
            1
            for row in active_rows
            if row.get("started_at") and row["started_at"] < stuck_before
        )

        terminal = [row for row in turns if row["status"] in TERMINAL_STATUSES]
        succeeded = [row for row in terminal if row["status"] == "succeeded"]
        failed = [row for row in terminal if row["status"] == "failed"]
        canceled = [row for row in terminal if row["status"] == "canceled"]
        interrupted = [row for row in terminal if row["status"] == "interrupted"]
        resumes = [row for row in turns if row["mode"] == "resume"]
        resume_failed = [row for row in resumes if row["status"] == "failed"]

        durations = [
            value
            for row in terminal
            if (value := _delta_seconds(row["started_at"], row["ended_at"]))
            is not None
        ]
        queue_waits = [
            value
            for row in turns
            if (value := _delta_seconds(row["created_at"], row["started_at"]))
            is not None
        ]

        total_cost = sum(float(row.get("cost_usd") or 0) for row in turns)
        cost_by_session = [
            dict(row)
            for row in self.db.query_all(
                f"""
                SELECT t.session_id, s.title, SUM(t.cost_usd) AS cost_usd,
                       COUNT(*) AS turns
                FROM turns t
                JOIN sessions s ON s.id = t.session_id
                WHERE {' AND '.join(where)} AND t.cost_usd IS NOT NULL
                GROUP BY t.session_id
                ORDER BY cost_usd DESC
                LIMIT 5
                """,
                (since, *params),
            )
        ]

        tool_clauses, tool_params = _clauses("t", role, project_id)
        tool_rows = self.db.query_all(
            f"""
            SELECT e.payload_json
            FROM turn_events e
            JOIN turns t ON t.id = e.turn_id
            WHERE e.kind = 'tool.use' AND t.created_at >= ?
              {"AND " + " AND ".join(tool_clauses) if tool_clauses else ""}
            """,
            (since, *tool_params),
        )
        tool_names: dict[str, int] = {}
        for row in tool_rows:
            try:
                name = json.loads(row["payload_json"]).get("name") or "tool"
            except (json.JSONDecodeError, TypeError, AttributeError):
                name = "tool"
            tool_names[name] = tool_names.get(name, 0) + 1

        denial_clauses, denial_params = _clauses("t", role, project_id)
        approval_denials = self.db.query_one(
            f"""
            SELECT COUNT(*) AS total
            FROM turn_approvals a
            JOIN turns t ON t.id = a.turn_id
            WHERE t.created_at >= ? AND a.status IN ('denied','expired')
              {"AND " + " AND ".join(denial_clauses) if denial_clauses else ""}
            """,
            (since, *denial_params),
        )
        permission_denials = self.db.query_one(
            f"""
            SELECT COUNT(*) AS total
            FROM turn_events e
            JOIN turns t ON t.id = e.turn_id
            WHERE e.kind = 'permission.denied' AND t.created_at >= ?
              {"AND " + " AND ".join(denial_clauses) if denial_clauses else ""}
            """,
            (since, *denial_params),
        )
        denials = int(approval_denials["total"] or 0) + int(
            permission_denials["total"] or 0
        )

        injected_turns = 0
        for row in turns:
            try:
                manifest = json.loads(row.get("prompt_manifest_json") or "{}")
            except json.JSONDecodeError:
                continue
            if manifest.get("included_facts"):
                injected_turns += 1

        error_counts: dict[str, int] = {}
        for row in turns:
            if row.get("error_type"):
                error_counts[row["error_type"]] = (
                    error_counts.get(row["error_type"], 0) + 1
                )

        summary_clauses, summary_params = _clauses("sess", role, project_id)
        summary_where = [
            "s.created_at >= ?",
            "s.status IN ('succeeded','failed')",
            *summary_clauses,
        ]
        summary_rows = self.db.query_all(
            f"""
            SELECT s.status
            FROM session_summaries s
            JOIN sessions sess ON sess.id = s.session_id
            WHERE {' AND '.join(summary_where)}
            """,
            (since, *summary_params),
        )
        summary_succeeded = sum(1 for row in summary_rows if row["status"] == "succeeded")
        summary_failed = sum(1 for row in summary_rows if row["status"] == "failed")
        summary_total = len(summary_rows)

        session_clauses, session_params = _clauses("sess", role, project_id)
        session_where = [
            "EXISTS (SELECT 1 FROM turns t WHERE t.session_id = sess.id "
            "AND t.status IN ('succeeded','failed','canceled','interrupted'))",
            *session_clauses,
        ]
        sessions_with_turns = int(
            self.db.query_one(
                f"SELECT COUNT(*) AS total FROM sessions sess "
                f"WHERE {' AND '.join(session_where)}",
                tuple(session_params),
            )["total"]
            or 0
        )
        sessions_with_summary = int(
            self.db.query_one(
                f"SELECT COUNT(*) AS total FROM sessions sess "
                f"WHERE {' AND '.join(session_where)} "
                "AND EXISTS (SELECT 1 FROM session_summaries ss "
                "WHERE ss.session_id = sess.id AND ss.status = 'succeeded')",
                tuple(session_params),
            )["total"]
            or 0
        )
        summary_lag_row = self.db.query_one(
            f"""
            SELECT MAX(
                COALESCE((SELECT MAX(t.seq) FROM turns t WHERE t.session_id = sess.id), 0)
                - sess.summary_covers_turn_seq
            ) AS lag
            FROM sessions sess
            WHERE {' AND '.join(session_clauses) if session_clauses else '1=1'}
            """,
            tuple(session_params),
        )

        fact_clauses, fact_params = _fact_clauses(role, project_id)
        fact_where = " AND ".join(fact_clauses) if fact_clauses else "1=1"
        pending_candidates = int(
            self.db.query_one(
                f"SELECT COUNT(*) AS total FROM facts f "
                f"WHERE f.status = 'candidate' AND {fact_where}",
                tuple(fact_params),
            )["total"]
            or 0
        )
        reviewed = self.db.query_one(
            f"""
            SELECT
              SUM(CASE WHEN f.status = 'accepted' THEN 1 ELSE 0 END) AS accepted,
              SUM(CASE WHEN f.status = 'rejected' THEN 1 ELSE 0 END) AS rejected
            FROM facts f
            WHERE f.status IN ('accepted','rejected')
              AND COALESCE(f.reviewed_at, f.updated_at) >= ?
              AND {fact_where}
            """,
            (since, *fact_params),
        )
        accepted = int(reviewed["accepted"] or 0)
        rejected = int(reviewed["rejected"] or 0)

        fact_top = [
            dict(row)
            for row in self.db.query_all(
                f"""
                SELECT f.id, f.title, f.scope, f.role, f.use_count, f.last_used_at
                FROM facts f
                WHERE f.status = 'accepted' AND {fact_where}
                ORDER BY f.use_count DESC, f.updated_at DESC
                LIMIT 5
                """,
                tuple(fact_params),
            )
        ]

        extraction_row = self.db.query_one(
            """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded,
              SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
            FROM fact_extractions
            WHERE created_at >= ? AND status IN ('succeeded','failed')
            """,
            (since,),
        )

        return {
            "generated_at": utcnow(),
            "range": window,
            "since": since,
            "filters": {"role": role, "project_id": project_id},
            "turns": {
                "total": len(turns),
                "active": len(active_rows),
                "stuck": stuck,
                "succeeded": len(succeeded),
                "failed": len(failed),
                "canceled": len(canceled),
                "interrupted": len(interrupted),
                "success_rate": _round(
                    len(succeeded) / len(terminal) if terminal else None
                ),
                "duration_p50_seconds": _percentile(durations, 0.5),
                "duration_p95_seconds": _percentile(durations, 0.95),
                "queue_wait_p95_seconds": _percentile(queue_waits, 0.95),
                "resume_rate": _round(len(resumes) / len(turns) if turns else None),
                "resume_failure_rate": _round(
                    len(resume_failed) / len(resumes) if resumes else None
                ),
                "cancel_rate": _round(
                    len(canceled) / len(terminal) if terminal else None
                ),
            },
            "cost": {
                "total_usd": _round(total_cost),
                "per_success_usd": _round(
                    total_cost / len(succeeded) if succeeded else None
                ),
                "by_session": [
                    {
                        "session_id": row["session_id"],
                        "title": row["title"],
                        "cost_usd": _round(float(row["cost_usd"] or 0)),
                        "turns": int(row["turns"] or 0),
                    }
                    for row in cost_by_session
                ],
            },
            "tools": {
                "calls": len(tool_rows),
                "denials": denials,
                "calls_per_turn": _round(
                    len(tool_rows) / len(turns) if turns else None
                ),
                "top": [
                    {"name": name, "calls": calls}
                    for name, calls in sorted(
                        tool_names.items(), key=lambda item: item[1], reverse=True
                    )[:5]
                ],
            },
            "memory": {
                "summary_lag": int(summary_lag_row["lag"] or 0)
                if summary_lag_row
                else 0,
                "summary_failure_rate": _round(
                    summary_failed / summary_total if summary_total else None
                ),
                "summary_coverage": _round(
                    sessions_with_summary / sessions_with_turns
                    if sessions_with_turns
                    else None
                ),
                "fact_candidates_pending": pending_candidates,
                "fact_accept_rate": _round(
                    accepted / (accepted + rejected)
                    if accepted + rejected
                    else None
                ),
                "fact_injection_rate": _round(
                    injected_turns / len(turns) if turns else None
                ),
                "fact_use_top": fact_top,
                "extraction_success_rate": _round(
                    int(extraction_row["succeeded"] or 0)
                    / (int(extraction_row["succeeded"] or 0) + int(extraction_row["failed"] or 0))
                    if (int(extraction_row["succeeded"] or 0) + int(extraction_row["failed"] or 0))
                    else None
                ),
            },
            "errors": {
                "top": [
                    {"error_type": kind, "count": count}
                    for kind, count in sorted(
                        error_counts.items(), key=lambda item: item[1], reverse=True
                    )[:5]
                ],
                "failed_turns": len(failed),
            },
            "storage": self._storage(),
        }

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        db_ok = True
        try:
            with self.db.transaction() as conn:
                conn.execute("SELECT 1")
        except Exception:  # noqa: BLE001 - health must never raise
            db_ok = False

        stuck_before = (
            datetime.now(timezone.utc)
            - timedelta(seconds=self.settings.run_timeout_seconds)
        ).isoformat(timespec="seconds")
        active = int(
            self.db.query_one(
                "SELECT COUNT(*) AS total FROM turns "
                "WHERE status IN ('starting','running','canceling')"
            )["total"]
            or 0
        )
        stuck = int(
            self.db.query_one(
                "SELECT COUNT(*) AS total FROM turns "
                "WHERE status IN ('starting','running','canceling') "
                "AND started_at IS NOT NULL AND started_at < ?",
                (stuck_before,),
            )["total"]
            or 0
        )
        summaries_pending = int(
            self.db.query_one(
                "SELECT COUNT(*) AS total FROM session_summaries "
                "WHERE status = 'pending'"
            )["total"]
            or 0
        )
        summaries_running = int(
            self.db.query_one(
                "SELECT COUNT(*) AS total FROM session_summaries "
                "WHERE status = 'running'"
            )["total"]
            or 0
        )
        extractions_running = int(
            self.db.query_one(
                "SELECT COUNT(*) AS total FROM fact_extractions "
                "WHERE status = 'running'"
            )["total"]
            or 0
        )
        cli = probe_cli(self.settings)
        sdk_path = resolve_claude_executable(self.settings)
        status = "ok" if db_ok and cli["installed"] and cli["auth_ok"] is not False else "degraded"
        return {
            "generated_at": utcnow(),
            "status": status,
            "db_ok": db_ok,
            "execution_backend": self.settings.execution_backend,
            "sdk_cli_path": str(sdk_path) if sdk_path else None,
            "turns": {"active": active, "stuck": stuck},
            "queues": {
                "summaries_pending": summaries_pending,
                "summaries_running": summaries_running,
                "extractions_running": extractions_running,
            },
            "cli": cli,
        }

    # ------------------------------------------------------------------
    # Recent errors
    # ------------------------------------------------------------------
    def recent_errors(
        self,
        *,
        role: str | None = None,
        project_id: str | None = None,
        window: str = "24h",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if window not in RANGES:
            raise ValueError("range must be 24h, 7d, or 30d")
        since = _iso_since(RANGES[window])
        clauses, params = _clauses("t", role, project_id)
        where = ["t.created_at >= ?", "t.error_type IS NOT NULL", *clauses]
        rows = self.db.query_all(
            f"""
            SELECT t.id AS turn_id, t.session_id, t.role, t.project_id,
                   t.error_type, t.error_message, t.created_at, t.ended_at,
                   t.cost_usd
            FROM turns t
            WHERE {' AND '.join(where)}
            ORDER BY t.created_at DESC
            LIMIT ?
            """,
            (since, *params, min(max(limit, 1), 100)),
        )
        return [
            {
                **dict(row),
                "error_message": (row["error_message"] or "")[:300],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------
    def _storage(self) -> dict[str, Any]:
        data_dir = self.settings.data_dir
        db_bytes = 0
        for suffix in ("", "-wal", "-shm"):
            path = Path(f"{self.settings.db_path}{suffix}")
            try:
                db_bytes += path.stat().st_size
            except OSError:
                pass
        backups = data_dir / "backups"
        backup_age = None
        try:
            files = [item for item in backups.glob("*") if item.is_file()]
            if files:
                latest = max(item.stat().st_mtime for item in files)
                backup_age = int(
                    datetime.now(timezone.utc).timestamp() - latest
                )
        except OSError:
            pass
        try:
            disk_free = shutil.disk_usage(data_dir).free
        except OSError:
            disk_free = None
        return {
            "db_bytes": db_bytes,
            "raw_log_bytes": _dir_size(data_dir / "session_logs"),
            "workspace_log_bytes": _dir_size(data_dir / "workspace_processes"),
            "backup_age_seconds": backup_age,
            "disk_free_bytes": disk_free,
        }
