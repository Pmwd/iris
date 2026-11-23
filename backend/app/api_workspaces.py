from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .repository import Repository
from .repository_sessions import SessionRepository
from .schemas import WorkspaceCreate, WorkspaceUpdate
from .security import workspace_warnings
from .services.processes import WorkspaceProcessManager

router = APIRouter()


def _repo(request: Request) -> Repository:
    return request.app.state.repo


def _sessions(request: Request) -> SessionRepository:
    return request.app.state.session_repo


def _processes(request: Request) -> WorkspaceProcessManager:
    return request.app.state.process_manager


def _require_project(repo: Repository, project_id: str) -> dict[str, Any]:
    project = repo.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="workspace not found")
    return project


@router.get("/workspaces")
def list_workspaces(
    request: Request, include_archived: bool = False
) -> list[dict[str, Any]]:
    return _repo(request).list_projects(include_archived=include_archived)


@router.post("/workspaces")
def create_workspace(request: Request, body: WorkspaceCreate) -> dict[str, Any]:
    workspace = Path(body.workspace_path).expanduser().resolve()
    if not workspace.is_dir():
        raise HTTPException(
            status_code=422, detail=f"workspace is not a directory: {workspace}"
        )
    return _repo(request).create_project(
        name=body.name.strip(),
        workspace_path=str(workspace),
        brief_md=body.brief_md,
        allowed_tools=body.allowed_tools,
    )


@router.get("/workspaces/{project_id}")
def get_workspace(request: Request, project_id: str) -> dict[str, Any]:
    repo = _repo(request)
    project = _require_project(repo, project_id)
    project["security_warnings"] = workspace_warnings(
        Path(project["workspace_path"])
    )
    project["session_count"] = _sessions(request).count_sessions_for_project(
        project_id
    )
    return project


@router.patch("/workspaces/{project_id}")
def update_workspace(
    request: Request, project_id: str, body: WorkspaceUpdate
) -> dict[str, Any]:
    repo = _repo(request)
    _require_project(repo, project_id)
    fields = body.model_dump(exclude_unset=True)
    if "workspace_path" in fields and fields["workspace_path"]:
        workspace = Path(fields["workspace_path"]).expanduser().resolve()
        if not workspace.is_dir():
            raise HTTPException(
                status_code=422,
                detail=f"workspace is not a directory: {workspace}",
            )
        fields["workspace_path"] = str(workspace)
    project = repo.update_project(project_id, fields)
    if not project:
        raise HTTPException(status_code=404, detail="workspace not found")
    return project


@router.delete("/workspaces/{project_id}")
def delete_workspace(request: Request, project_id: str) -> dict[str, bool]:
    repo = _repo(request)
    _require_project(repo, project_id)
    count = _sessions(request).count_sessions_for_project(project_id)
    if count:
        raise HTTPException(
            status_code=409,
            detail=(
                f"workspace still has {count} session(s); delete or move them first"
            ),
        )
    _processes(request).stop_for_project(project_id)
    return {"deleted": repo.delete_project(project_id)}
