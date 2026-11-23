from __future__ import annotations

import json
import os
from typing import Any
from uuid import uuid4

from .db import Database, utcnow

MAX_INPUT_CHARS = 200_000
WRITE_TOOLS = {"write", "edit", "multiedit", "notebookedit"}
SHELL_TOOLS = {"powershell", "bash"}


def _json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _dump_input(input_data: Any) -> str:
    text = json.dumps(input_data, ensure_ascii=False, sort_keys=True)
    if len(text) <= MAX_INPUT_CHARS:
        return text
    return json.dumps(
        {"truncated": True, "preview": text[:MAX_INPUT_CHARS]},
        ensure_ascii=False,
    )


def _approval(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["input"] = _json_load(data.pop("input_json", None), {})
    return data


def _rule(row: Any | None) -> dict[str, Any] | None:
    return dict(row) if row else None


class ApprovalRepository:
    """SQL for tool approval requests and session-scoped permission rules."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Approvals
    # ------------------------------------------------------------------
    def create_approval(
        self,
        *,
        turn_id: str,
        session_id: str,
        tool_name: str,
        input_data: Any,
        status: str = "pending",
        decision: str | None = None,
        message: str = "",
        decided_by: str | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        approval_id = str(uuid4())
        now = utcnow()
        decided_at = now if status != "pending" else None
        self.db.execute(
            """
            INSERT INTO turn_approvals
                (id, turn_id, session_id, tool_name, input_json, status,
                 decision, message, decided_by, created_at, decided_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                approval_id,
                turn_id,
                session_id,
                tool_name,
                _dump_input(input_data),
                status,
                decision,
                message,
                decided_by,
                now,
                decided_at,
            ),
        )
        approval = self.get_approval(approval_id)
        assert approval is not None
        approval["title"] = title
        approval["description"] = description
        return approval

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        return _approval(
            self.db.query_one(
                "SELECT * FROM turn_approvals WHERE id = ?", (approval_id,)
            )
        )

    def list_for_turn(self, turn_id: str) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """
            SELECT * FROM turn_approvals
            WHERE turn_id = ?
            ORDER BY created_at ASC
            """,
            (turn_id,),
        )
        return [a for a in (_approval(row) for row in rows) if a is not None]

    def list_pending_for_turn(self, turn_id: str) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """
            SELECT * FROM turn_approvals
            WHERE turn_id = ? AND status = 'pending'
            ORDER BY created_at ASC
            """,
            (turn_id,),
        )
        return [a for a in (_approval(row) for row in rows) if a is not None]

    def list_pending_for_session(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """
            SELECT * FROM turn_approvals
            WHERE session_id = ? AND status = 'pending'
            ORDER BY created_at ASC
            """,
            (session_id,),
        )
        return [a for a in (_approval(row) for row in rows) if a is not None]

    def decide_approval(
        self,
        approval_id: str,
        *,
        status: str,
        decision: str,
        message: str = "",
        decided_by: str = "user",
    ) -> dict[str, Any] | None:
        self.db.execute(
            """
            UPDATE turn_approvals
            SET status = ?, decision = ?, message = ?, decided_by = ?,
                decided_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (status, decision, message, decided_by, utcnow(), approval_id),
        )
        return self.get_approval(approval_id)

    def expire_pending(self, message: str = "service_restart") -> int:
        now = utcnow()
        result = self.db.execute(
            """
            UPDATE turn_approvals
            SET status = 'expired', message = ?, decided_by = 'system',
                decided_at = ?
            WHERE status = 'pending'
            """,
            (message, now),
        )
        return int(result or 0)

    # ------------------------------------------------------------------
    # Permission rules (session-scoped "always allow")
    # ------------------------------------------------------------------
    def add_rule(
        self,
        session_id: str,
        tool_name: str,
        match_type: str,
        match_value: str,
    ) -> dict[str, Any]:
        rule_id = str(uuid4())
        self.db.execute(
            """
            INSERT OR IGNORE INTO permission_rules
                (id, session_id, tool_name, match_type, match_value, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                rule_id,
                session_id,
                tool_name,
                match_type,
                match_value,
                utcnow(),
            ),
        )
        row = self.db.query_one(
            """
            SELECT * FROM permission_rules
            WHERE session_id = ? AND tool_name = ? AND match_type = ?
              AND match_value = ?
            """,
            (session_id, tool_name, match_type, match_value),
        )
        rule = _rule(row)
        assert rule is not None
        return rule

    def list_rules(
        self, session_id: str, tool_name: str | None = None
    ) -> list[dict[str, Any]]:
        if tool_name:
            rows = self.db.query_all(
                """
                SELECT * FROM permission_rules
                WHERE session_id = ? AND tool_name = ?
                ORDER BY created_at ASC
                """,
                (session_id, tool_name),
            )
        else:
            rows = self.db.query_all(
                """
                SELECT * FROM permission_rules
                WHERE session_id = ?
                ORDER BY created_at ASC
                """,
                (session_id,),
            )
        return [r for r in (_rule(row) for row in rows) if r is not None]

    @staticmethod
    def rule_for_input(
        tool_name: str, input_data: dict[str, Any]
    ) -> tuple[str, str]:
        tool = (tool_name or "").strip().lower()
        command = input_data.get("command") if isinstance(input_data, dict) else None
        if tool in SHELL_TOOLS and isinstance(command, str) and command.strip():
            prefix = command.strip().split()[0]
            return ("prefix", prefix)
        path = (
            input_data.get("file_path") or input_data.get("notebook_path")
            if isinstance(input_data, dict)
            else None
        )
        if tool in WRITE_TOOLS and path:
            return ("path", str(path))
        exact = json.dumps(input_data, ensure_ascii=False, sort_keys=True)
        return ("exact", exact)

    def add_rule_for_input(
        self, session_id: str, tool_name: str, input_data: dict[str, Any]
    ) -> dict[str, Any]:
        match_type, match_value = self.rule_for_input(tool_name, input_data)
        return self.add_rule(session_id, tool_name, match_type, match_value)

    def match_rule(
        self, session_id: str, tool_name: str, input_data: dict[str, Any]
    ) -> dict[str, Any] | None:
        command = input_data.get("command") if isinstance(input_data, dict) else None
        path = (
            input_data.get("file_path") or input_data.get("notebook_path")
            if isinstance(input_data, dict)
            else None
        )
        exact = json.dumps(input_data, ensure_ascii=False, sort_keys=True)
        for rule in self.list_rules(session_id, tool_name):
            match_type = rule["match_type"]
            match_value = rule["match_value"]
            if (
                match_type == "prefix"
                and isinstance(command, str)
                and command.strip().lower().startswith(match_value.strip().lower())
            ):
                return rule
            if (
                match_type == "path"
                and path
                and os.path.normcase(str(path)) == os.path.normcase(match_value)
            ):
                return rule
            if match_type == "exact" and exact == match_value:
                return rule
        return None
