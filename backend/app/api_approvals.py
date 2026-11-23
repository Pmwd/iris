from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .repository_sessions import SessionRepository
from .schemas import ApprovalDecide
from .services.approvals import ApprovalError, ApprovalManager

router = APIRouter()


def _approvals(request: Request) -> ApprovalManager:
    return request.app.state.approval_manager


def _sessions(request: Request) -> SessionRepository:
    return request.app.state.session_repo


@router.get("/turns/{turn_id}/approvals")
def list_turn_approvals(
    request: Request, turn_id: str
) -> list[dict[str, Any]]:
    if not _sessions(request).get_turn(turn_id):
        raise HTTPException(status_code=404, detail="turn not found")
    return _approvals(request).list_for_turn(turn_id)


@router.get("/approvals/{approval_id}")
def get_approval(request: Request, approval_id: str) -> dict[str, Any]:
    approval = _approvals(request).get(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="approval not found")
    return approval


@router.post("/approvals/{approval_id}/decide")
def decide_approval(
    request: Request, approval_id: str, body: ApprovalDecide
) -> dict[str, Any]:
    try:
        return _approvals(request).decide(
            approval_id, body.decision, body.message
        )
    except ApprovalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
