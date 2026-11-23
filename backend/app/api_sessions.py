from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from .config import Settings
from .repository import Repository
from .repository_sessions import SessionRepository
from .schemas import MessageCreate, SessionCreate, SessionUpdate
from .services.memory import MemoryError, MemoryManager
from .services.sessions import SessionManager, TurnError

router = APIRouter()

ACTIVE = {"starting", "running", "canceling"}


def _sessions(request: Request) -> SessionRepository:
    return request.app.state.session_repo


def _projects(request: Request) -> Repository:
    return request.app.state.repo


def _manager(request: Request) -> SessionManager:
    return request.app.state.session_manager


def _memory(request: Request) -> MemoryManager:
    return request.app.state.memory_manager


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _require_session(request: Request, session_id: str) -> dict[str, Any]:
    session = _sessions(request).get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@router.get("/sessions")
def list_sessions(
    request: Request,
    role: str | None = None,
    project_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    return _sessions(request).list_sessions(
        role=role,
        project_id=project_id,
        status=status,
        limit=min(max(limit, 1), 500),
    )


@router.post("/sessions")
def create_session(request: Request, body: SessionCreate) -> dict[str, Any]:
    try:
        return _manager(request).create_session(
            body.role, title=body.title, project_id=body.project_id
        )
    except TurnError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/sessions/{session_id}")
def get_session(request: Request, session_id: str) -> dict[str, Any]:
    sessions = _sessions(request)
    session = _require_session(request, session_id)
    workspace = (
        _projects(request).get_project(session["project_id"])
        if session.get("project_id")
        else None
    )
    session["workspace"] = workspace
    session["latest_summary"] = sessions.latest_summary(session_id, "succeeded")
    session["active_turn"] = sessions.active_turn_for_session(session_id)
    session["turn_count"] = len(sessions.list_turns(session_id))
    session["execution_backend"] = _settings(request).execution_backend
    return session


@router.patch("/sessions/{session_id}")
def update_session(
    request: Request, session_id: str, body: SessionUpdate
) -> dict[str, Any]:
    sessions = _sessions(request)
    _require_session(request, session_id)
    fields = body.model_dump(exclude_unset=True)
    if fields.get("status") == "ended":
        try:
            return _manager(request).end_session(session_id)
        except TurnError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    if fields.get("status") in {"active", "archived"}:
        if sessions.active_turn_for_session(session_id):
            raise HTTPException(
                status_code=409, detail="cannot change status while a turn is active"
            )
    session = sessions.update_session(session_id, fields)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@router.delete("/sessions/{session_id}")
def delete_session(request: Request, session_id: str) -> dict[str, bool]:
    sessions = _sessions(request)
    _require_session(request, session_id)
    if sessions.active_turn_for_session(session_id):
        raise HTTPException(status_code=409, detail="session has an active turn")
    deleted = sessions.delete_session(session_id)
    if deleted:
        shutil.rmtree(
            _settings(request).data_dir / "session_logs" / session_id,
            ignore_errors=True,
        )
    return {"deleted": deleted}


@router.post("/sessions/{session_id}/end")
def end_session(request: Request, session_id: str) -> dict[str, Any]:
    try:
        return _manager(request).end_session(session_id)
    except TurnError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/sessions/{session_id}/compact")
def compact_session(request: Request, session_id: str) -> dict[str, Any]:
    try:
        return _manager(request).compact_session(session_id)
    except TurnError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/sessions/{session_id}/messages")
def list_messages(
    request: Request,
    session_id: str,
    after_seq: int = 0,
    limit: int = 500,
) -> list[dict[str, Any]]:
    sessions = _sessions(request)
    _require_session(request, session_id)
    return sessions.list_messages(
        session_id,
        after_seq=max(0, after_seq),
        limit=min(max(limit, 1), 1000),
    )


@router.post("/sessions/{session_id}/messages")
def send_message(
    request: Request, session_id: str, body: MessageCreate
) -> dict[str, Any]:
    try:
        return _manager(request).send_message(
            session_id,
            body.content,
            permission_profile=body.permission_profile,
            fact_ids=body.fact_ids,
        )
    except TurnError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/sessions/{session_id}/turns")
def list_turns(
    request: Request, session_id: str, limit: int = 200
) -> list[dict[str, Any]]:
    sessions = _sessions(request)
    _require_session(request, session_id)
    return sessions.list_turns(session_id, limit=min(max(limit, 1), 500))


@router.get("/sessions/{session_id}/summary")
def get_summary(request: Request, session_id: str) -> dict[str, Any]:
    sessions = _sessions(request)
    _require_session(request, session_id)
    # Read the rows once and derive state from the same snapshot; separate
    # queries can straddle a worker's status transition and disagree.
    items = sessions.list_summaries(session_id)
    latest = next(
        (item for item in items if item["status"] == "succeeded"), None
    )
    active = next(
        (item for item in items if item["status"] in {"pending", "running"}),
        None,
    )
    return {"summary": latest, "active": active, "items": items}


@router.post("/sessions/{session_id}/summary")
def request_summary(request: Request, session_id: str) -> dict[str, Any]:
    _require_session(request, session_id)
    try:
        return _memory(request).request_summary(session_id, "manual")
    except MemoryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/turns/{turn_id}")
def get_turn(request: Request, turn_id: str) -> dict[str, Any]:
    turn = _sessions(request).get_turn(turn_id)
    if not turn:
        raise HTTPException(status_code=404, detail="turn not found")
    return turn


@router.post("/turns/{turn_id}/cancel")
def cancel_turn(request: Request, turn_id: str) -> dict[str, Any]:
    try:
        return _manager(request).cancel_turn(turn_id)
    except TurnError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/turns/{turn_id}/events")
def list_turn_events(
    request: Request, turn_id: str, after_seq: int = 0, limit: int = 500
) -> list[dict[str, Any]]:
    sessions = _sessions(request)
    if not sessions.get_turn(turn_id):
        raise HTTPException(status_code=404, detail="turn not found")
    return sessions.list_turn_events(
        turn_id, after_seq=max(0, after_seq), limit=min(limit, 1000)
    )


@router.get("/turns/{turn_id}/events/stream")
async def stream_turn_events(
    request: Request, turn_id: str, after_seq: int = 0
):
    sessions = _sessions(request)
    settings = _settings(request)
    if not sessions.get_turn(turn_id):
        raise HTTPException(status_code=404, detail="turn not found")

    async def generator():
        seq = max(0, after_seq)
        while True:
            if await request.is_disconnected():
                break
            events = await asyncio.to_thread(
                sessions.list_turn_events, turn_id, seq, 200
            )
            if events:
                for event in events:
                    seq = event["seq"]
                    data = json.dumps(event, ensure_ascii=False)
                    yield f"id: {seq}\nevent: turn_event\ndata: {data}\n\n"
            turn = await asyncio.to_thread(sessions.get_turn, turn_id)
            if turn and turn["status"] not in ACTIVE:
                if not events:
                    yield "event: done\ndata: {}\n\n"
                    break
                continue
            if not events:
                yield ": keep-alive\n\n"
            await asyncio.sleep(settings.sse_poll_seconds)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/turns/{turn_id}/raw")
def get_turn_raw(request: Request, turn_id: str) -> FileResponse:
    turn = _sessions(request).get_turn(turn_id)
    if not turn:
        raise HTTPException(status_code=404, detail="turn not found")
    raw_path = turn.get("raw_log_path")
    if not raw_path:
        raise HTTPException(status_code=404, detail="raw log not available")
    path = Path(raw_path).resolve()
    log_root = (_settings(request).data_dir / "session_logs").resolve()
    if not path.is_relative_to(log_root) or not path.is_file():
        raise HTTPException(status_code=404, detail="raw log not found")
    return FileResponse(path, media_type="application/x-ndjson")
