from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable

from ..config import Settings
from ..db import utcnow
from ..repository_approvals import ApprovalRepository

logger = logging.getLogger("iris.approvals")


class ApprovalError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class PendingApproval:
    id: str
    turn_id: str
    session_id: str
    tool_name: str
    input_data: dict[str, Any]
    loop: asyncio.AbstractEventLoop
    future: asyncio.Future
    emit: Callable[[str, Any], None]
    title: str | None = None
    description: str | None = None


class ApprovalManager:
    """Bridges SDK ``can_use_tool`` callbacks to the web approval endpoints."""

    def __init__(self, repo: ApprovalRepository, settings: Settings) -> None:
        self.repo = repo
        self.settings = settings
        self._lock = threading.Lock()
        self._pending: dict[str, PendingApproval] = {}

    # ------------------------------------------------------------------
    # SDK callback bridge
    # ------------------------------------------------------------------
    async def request(
        self,
        *,
        turn_id: str,
        session_id: str,
        tool_name: str,
        input_data: dict[str, Any],
        context: Any,
        emit: Callable[[str, Any], None],
    ) -> dict[str, Any]:
        rule = self.repo.match_rule(session_id, tool_name, input_data)
        if rule:
            approval = self.repo.create_approval(
                turn_id=turn_id,
                session_id=session_id,
                tool_name=tool_name,
                input_data=input_data,
                status="allowed",
                decision="always",
                message=f"Auto-allowed by session rule: {rule['match_type']} {rule['match_value']}",
                decided_by="auto",
            )
            logger.info(
                "approval.auto session_id=%s tool=%s rule=%s",
                session_id,
                tool_name,
                rule["match_value"],
            )
            return {"behavior": "allow", "message": "", "approval": approval, "rule": rule}

        title = getattr(context, "title", None)
        description = getattr(context, "description", None)
        approval = self.repo.create_approval(
            turn_id=turn_id,
            session_id=session_id,
            tool_name=tool_name,
            input_data=input_data,
            status="pending",
            title=title,
            description=description,
        )
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        pending = PendingApproval(
            id=approval["id"],
            turn_id=turn_id,
            session_id=session_id,
            tool_name=tool_name,
            input_data=input_data,
            loop=loop,
            future=future,
            emit=emit,
            title=title,
            description=description,
        )
        with self._lock:
            self._pending[pending.id] = pending
        emit("approval.requested", self._payload(approval, pending))
        logger.info(
            "approval.requested approval_id=%s tool=%s",
            approval["id"],
            tool_name,
        )

        try:
            result = await asyncio.wait_for(
                future, timeout=self.settings.approval_timeout_seconds
            )
            return result
        except asyncio.TimeoutError:
            updated = self._expire(
                pending,
                message="Approval timed out; the tool was not run.",
                decided_by="timeout",
            )
            return {
                "behavior": "deny",
                "message": "Approval timed out; the tool was not run.",
                "approval": updated,
            }
        except asyncio.CancelledError:
            self._expire(
                pending,
                message="Approval canceled because the turn stopped.",
                decided_by="system",
            )
            raise
        finally:
            with self._lock:
                self._pending.pop(pending.id, None)

    # ------------------------------------------------------------------
    # HTTP decisions
    # ------------------------------------------------------------------
    def decide(
        self, approval_id: str, decision: str, message: str = ""
    ) -> dict[str, Any]:
        if decision not in {"allow", "deny", "always"}:
            raise ApprovalError("decision must be allow, deny, or always", 422)
        with self._lock:
            pending = self._pending.get(approval_id)
            approval = self.repo.get_approval(approval_id)
            if not approval:
                raise ApprovalError("approval not found", 404)
            if approval["status"] != "pending":
                raise ApprovalError("approval is no longer pending", 409)
            if pending is None:
                raise ApprovalError("approval is not active in this process", 409)

            status = "denied" if decision == "deny" else "allowed"
            rule = None
            if decision == "always":
                try:
                    rule = self.repo.add_rule_for_input(
                        pending.session_id,
                        pending.tool_name,
                        pending.input_data,
                    )
                except Exception:
                    logger.exception(
                        "approval.rule_failed approval_id=%s", approval_id
                    )
            updated = self.repo.decide_approval(
                approval_id,
                status=status,
                decision=decision,
                message=message,
                decided_by="user",
            )
            if not updated:
                raise ApprovalError("approval could not be updated", 409)

            payload = self._payload(updated, pending)
            if rule:
                payload["rule"] = rule
            pending.emit("approval.decided", payload)
            result = {
                "behavior": "deny" if decision == "deny" else "allow",
                "message": (
                    message
                    or (
                        "User denied this action."
                        if decision == "deny"
                        else ""
                    )
                ),
                "approval": updated,
                "rule": rule,
            }
            if not pending.future.done():
                pending.loop.call_soon_threadsafe(
                    self._resolve_future, pending.future, result
                )
            self._pending.pop(approval_id, None)
        logger.info(
            "approval.decided approval_id=%s decision=%s",
            approval_id,
            decision,
        )
        assert updated is not None
        return updated

    def cancel_turn(self, turn_id: str, message: str = "Turn was canceled.") -> None:
        with self._lock:
            pending_ids = [
                approval_id
                for approval_id, pending in self._pending.items()
                if pending.turn_id == turn_id
            ]
        for approval_id in pending_ids:
            with self._lock:
                pending = self._pending.pop(approval_id, None)
            if pending is None:
                continue
            updated = self.repo.decide_approval(
                approval_id,
                status="expired",
                decision="deny",
                message=message,
                decided_by="system",
            )
            if updated:
                pending.emit("approval.decided", self._payload(updated, pending))
            if not pending.future.done():
                pending.loop.call_soon_threadsafe(
                    self._resolve_future,
                    pending.future,
                    {"behavior": "deny", "message": message, "approval": updated},
                )

    # ------------------------------------------------------------------
    # Queries / lifecycle
    # ------------------------------------------------------------------
    def list_for_turn(self, turn_id: str) -> list[dict[str, Any]]:
        return self.repo.list_for_turn(turn_id)

    def is_pending(self, approval_id: str) -> bool:
        with self._lock:
            return approval_id in self._pending

    def get(self, approval_id: str) -> dict[str, Any] | None:
        return self.repo.get_approval(approval_id)

    def reconcile(self) -> int:
        return self.repo.expire_pending("service_restart")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _expire(
        self,
        pending: PendingApproval,
        *,
        message: str,
        decided_by: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            current = self._pending.get(pending.id)
            if current is None:
                return self.repo.get_approval(pending.id)
        updated = self.repo.decide_approval(
            pending.id,
            status="expired",
            decision="deny",
            message=message,
            decided_by=decided_by,
        )
        if updated:
            with self._lock:
                self._pending.pop(pending.id, None)
            pending.emit("approval.decided", self._payload(updated, pending))
        return updated

    @staticmethod
    def _resolve_future(future: asyncio.Future, value: Any) -> None:
        if not future.done():
            future.set_result(value)

    @staticmethod
    def _payload(
        approval: dict[str, Any], pending: PendingApproval | None = None
    ) -> dict[str, Any]:
        payload = {
            "approval_id": approval["id"],
            "turn_id": approval["turn_id"],
            "session_id": approval["session_id"],
            "tool_name": approval["tool_name"],
            "input": approval.get("input") or {},
            "status": approval["status"],
            "decision": approval.get("decision"),
            "message": approval.get("message") or "",
            "decided_by": approval.get("decided_by"),
            "created_at": approval["created_at"],
            "decided_at": approval.get("decided_at"),
        }
        if pending is not None:
            payload["title"] = pending.title
            payload["description"] = pending.description
        return payload
