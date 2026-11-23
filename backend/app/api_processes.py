from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .repository import Repository
from .schemas import ProcessStart
from .services.processes import ProcessError, WorkspaceProcessManager

router = APIRouter()


def _repo(request: Request) -> Repository:
    return request.app.state.repo


def _processes(request: Request) -> WorkspaceProcessManager:
    return request.app.state.process_manager


@router.get("/workspaces/{project_id}/processes")
def list_processes(request: Request, project_id: str) -> list[dict[str, Any]]:
    if not _repo(request).get_project(project_id):
        raise HTTPException(status_code=404, detail="workspace not found")
    return _processes(request).list(project_id)


@router.post("/workspaces/{project_id}/processes")
def start_process(
    request: Request, project_id: str, body: ProcessStart
) -> dict[str, Any]:
    try:
        return _processes(request).start(
            project_id, body.command.strip(), body.label.strip()
        )
    except ProcessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/processes/{process_id}")
def get_process(request: Request, process_id: str) -> dict[str, Any]:
    record = _processes(request).get(process_id)
    if not record:
        raise HTTPException(status_code=404, detail="process not found")
    return record


@router.get("/processes/{process_id}/logs")
def process_logs(
    request: Request, process_id: str, after_seq: int = 0
) -> dict[str, Any]:
    result = _processes(request).logs(process_id, after_seq=max(0, after_seq))
    if not result:
        raise HTTPException(status_code=404, detail="process not found")
    return result


@router.post("/processes/{process_id}/stop")
def stop_process(request: Request, process_id: str) -> dict[str, Any]:
    try:
        return _processes(request).stop(process_id)
    except ProcessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
