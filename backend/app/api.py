from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .config import Settings
from .maintenance import backup_database, list_backups as list_backup_files
from .repository import Repository
from .roles import list_roles
from .security import workspace_warnings
from .schemas import (
    GlobalNoteCreate,
    GlobalNoteUpdate,
    NoteCreate,
    NoteUpdate,
    ProjectCreate,
    ProjectUpdate,
    ResearchPlanCreate,
    ResearchPlanUpdate,
    RunStart,
    TaskCreate,
    TaskUpdate,
)
from .services.research import ResearchError, ResearchManager
from .services.retrieval import collect_candidates
from .services.runs import RunError, RunManager

router = APIRouter(prefix="/api")


def _repo(request: Request) -> Repository:
    return request.app.state.repo


def _manager(request: Request) -> RunManager:
    return request.app.state.run_manager


def _research(request: Request) -> ResearchManager:
    return request.app.state.research_manager


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _require_project(repo: Repository, project_id: str) -> dict[str, Any]:
    project = repo.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _require_task(repo: Repository, task_id: str) -> dict[str, Any]:
    task = repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    repo = _repo(request)
    result: dict[str, Any] = {
        "status": "degraded",
        "data_dir": str(settings.data_dir),
        "db_path": str(settings.db_path),
        "host": settings.host,
        "cli": {
            "installed": False,
            "version": None,
            "auth_ok": None,
            "auth_method": None,
            "api_provider": None,
        },
    }

    def probe() -> dict[str, Any]:
        cli_info = result["cli"]
        try:
            version = subprocess.run(
                [*settings.claude_command, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if version.returncode == 0:
                cli_info["installed"] = True
                cli_info["version"] = (version.stdout or "").strip().splitlines()[0][:200]
        except (OSError, subprocess.SubprocessError):
            pass

        try:
            auth = subprocess.run(
                [*settings.claude_command, "auth", "status"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if auth.returncode == 0 and auth.stdout.strip():
                try:
                    payload = json.loads(auth.stdout)
                    cli_info["auth_ok"] = bool(payload.get("loggedIn"))
                    cli_info["auth_method"] = payload.get("authMethod")
                    cli_info["api_provider"] = payload.get("apiProvider")
                except json.JSONDecodeError:
                    pass
        except (OSError, subprocess.SubprocessError):
            pass
        return cli_info

    cli_info = await asyncio.to_thread(probe)
    try:
        project_count = len(repo.list_projects())
    except Exception:
        project_count = 0
    result["project_count"] = project_count
    if cli_info.get("installed"):
        result["status"] = "ok" if cli_info.get("auth_ok") is not False else "degraded"
    return result


# ----------------------------------------------------------------------
# Maintenance
# ----------------------------------------------------------------------
@router.post("/maintenance/backup")
def create_backup(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    return backup_database(settings.db_path, settings.data_dir / "backups")


@router.get("/maintenance/backups")
def list_backups(request: Request) -> list[dict[str, Any]]:
    return list_backup_files(_settings(request).data_dir / "backups")


# ----------------------------------------------------------------------
# Projects
# ----------------------------------------------------------------------
@router.get("/roles")
def roles() -> list[dict[str, Any]]:
    return list_roles()


@router.get("/projects")
def list_projects(request: Request, include_archived: bool = False) -> list[dict[str, Any]]:
    return _repo(request).list_projects(include_archived=include_archived)


@router.post("/projects")
def create_project(request: Request, body: ProjectCreate) -> dict[str, Any]:
    workspace = Path(body.workspace_path).expanduser().resolve()
    if not workspace.is_dir():
        raise HTTPException(status_code=422, detail=f"workspace is not a directory: {workspace}")
    project = _repo(request).create_project(
        name=body.name.strip(),
        workspace_path=str(workspace),
        brief_md=body.brief_md,
        allowed_tools=body.allowed_tools,
    )
    return project


@router.get("/projects/{project_id}")
def get_project(request: Request, project_id: str) -> dict[str, Any]:
    return _require_project(_repo(request), project_id)


@router.patch("/projects/{project_id}")
def update_project(
    request: Request, project_id: str, body: ProjectUpdate
) -> dict[str, Any]:
    repo = _repo(request)
    _require_project(repo, project_id)
    fields = body.model_dump(exclude_unset=True)
    if "workspace_path" in fields and fields["workspace_path"]:
        workspace = Path(fields["workspace_path"]).expanduser().resolve()
        if not workspace.is_dir():
            raise HTTPException(
                status_code=422, detail=f"workspace is not a directory: {workspace}"
            )
        fields["workspace_path"] = str(workspace)
    project = repo.update_project(project_id, fields)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.delete("/projects/{project_id}")
def delete_project(request: Request, project_id: str) -> dict[str, bool]:
    repo = _repo(request)
    _require_project(repo, project_id)
    if repo.active_run_for_project(project_id):
        raise HTTPException(status_code=409, detail="project has an active run")
    return {"deleted": repo.delete_project(project_id)}


# ----------------------------------------------------------------------
# Tasks
# ----------------------------------------------------------------------
@router.get("/projects/{project_id}/tasks")
def list_tasks(request: Request, project_id: str) -> list[dict[str, Any]]:
    repo = _repo(request)
    _require_project(repo, project_id)
    return repo.list_tasks(project_id)


@router.post("/projects/{project_id}/tasks")
def create_task(request: Request, project_id: str, body: TaskCreate) -> dict[str, Any]:
    repo = _repo(request)
    _require_project(repo, project_id)
    if body.role == "testing" and not body.source_task_id:
        raise HTTPException(
            status_code=422,
            detail="Testing tasks require source_task_id",
        )
    if body.source_task_id:
        source = repo.get_task(body.source_task_id)
        if not source or source["project_id"] != project_id:
            raise HTTPException(
                status_code=422,
                detail="source task does not belong to this project",
            )
    task = repo.create_task(
        project_id,
        body.title.strip(),
        body.goal_md,
        role=body.role,
        source_task_id=body.source_task_id,
    )
    return task


@router.get("/tasks/{task_id}")
def get_task(request: Request, task_id: str) -> dict[str, Any]:
    return _require_task(_repo(request), task_id)


@router.patch("/tasks/{task_id}")
def update_task(request: Request, task_id: str, body: TaskUpdate) -> dict[str, Any]:
    repo = _repo(request)
    _require_task(repo, task_id)
    task = repo.update_task(task_id, body.model_dump(exclude_unset=True))
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.delete("/tasks/{task_id}")
def delete_task(request: Request, task_id: str) -> dict[str, bool]:
    repo = _repo(request)
    _require_task(repo, task_id)
    task = repo.get_task(task_id)
    active = repo.active_run_for_project(task["project_id"]) if task else None
    if active and active["task_id"] == task_id:
        raise HTTPException(status_code=409, detail="task has an active run")
    return {"deleted": repo.delete_task(task_id)}


@router.post("/tasks/{task_id}/complete")
def complete_task(request: Request, task_id: str) -> dict[str, Any]:
    repo = _repo(request)
    task = _require_task(repo, task_id)
    if task["status"] in {"starting", "running", "canceling"}:
        raise HTTPException(status_code=409, detail="task is currently running")
    repo.set_task_status(task_id, "done")
    return _require_task(repo, task_id)


@router.get("/tasks/{task_id}/context-preview")
def context_preview(request: Request, task_id: str) -> dict[str, Any]:
    repo = _repo(request)
    task = _require_task(repo, task_id)
    project = _require_project(repo, task["project_id"])
    candidates = collect_candidates(
        repo,
        project,
        task,
        _settings(request).max_context_chars,
    )
    return {
        "task_id": task_id,
        "project_id": project["id"],
        "role": task.get("role", "coding"),
        "source_task_id": task.get("source_task_id"),
        "project_brief": project["brief_md"],
        "budget_chars": candidates["budget_chars"],
        "budget_tokens": candidates["budget_tokens"],
        "estimated_tokens": candidates["estimated_tokens"],
        "selected_chars": candidates["selected_chars"],
        "query_terms": candidates["query_terms"],
        "notes": candidates["notes"],
        "selected_note_ids": candidates["selected_note_ids"],
        "execute_allowed": bool(project["allowed_tools"]),
        "security_warnings": workspace_warnings(Path(project["workspace_path"])),
    }


# ----------------------------------------------------------------------
# Runs
# ----------------------------------------------------------------------
@router.post("/tasks/{task_id}/runs")
def start_run(request: Request, task_id: str, body: RunStart) -> dict[str, Any]:
    try:
        return _manager(request).start_run(
            task_id,
            mode=body.mode,
            profile=body.permission_profile,
            context_note_ids=body.context_note_ids,
        )
    except RunError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


# ----------------------------------------------------------------------
# Scholar research orchestration
# ----------------------------------------------------------------------
@router.get("/tasks/{task_id}/research")
def list_research_jobs(request: Request, task_id: str) -> list[dict[str, Any]]:
    repo = _repo(request)
    _require_task(repo, task_id)
    return _research(request).list_jobs(task_id)


@router.post("/tasks/{task_id}/research/plan")
def create_research_plan(
    request: Request, task_id: str, body: ResearchPlanCreate
) -> dict[str, Any]:
    try:
        return _research(request).create_plan(task_id, allow_web=body.allow_web)
    except ResearchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/research/{job_id}")
def get_research_job(request: Request, job_id: str) -> dict[str, Any]:
    try:
        return _research(request).get_job(job_id)
    except ResearchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.patch("/research/{job_id}/plan")
def update_research_plan(
    request: Request, job_id: str, body: ResearchPlanUpdate
) -> dict[str, Any]:
    try:
        return _research(request).update_plan(job_id, body.questions)
    except ResearchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/research/{job_id}/start")
def start_research_job(request: Request, job_id: str) -> dict[str, Any]:
    try:
        return _research(request).start_job(job_id)
    except ResearchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/research/{job_id}/cancel")
def cancel_research_job(request: Request, job_id: str) -> dict[str, Any]:
    try:
        return _research(request).cancel_job(job_id)
    except ResearchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/tasks/{task_id}/runs")
def list_runs(request: Request, task_id: str) -> list[dict[str, Any]]:
    repo = _repo(request)
    _require_task(repo, task_id)
    return repo.list_runs(task_id)


@router.get("/runs/{run_id}")
def get_run(request: Request, run_id: str) -> dict[str, Any]:
    run = _repo(request).get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.post("/runs/{run_id}/cancel")
def cancel_run(request: Request, run_id: str) -> dict[str, Any]:
    try:
        return _manager(request).cancel_run(run_id)
    except RunError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/runs/{run_id}/events")
def list_run_events(
    request: Request, run_id: str, after_seq: int = 0, limit: int = 500
) -> list[dict[str, Any]]:
    repo = _repo(request)
    if not repo.get_run(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    return repo.list_events(run_id, after_seq=max(0, after_seq), limit=min(limit, 1000))


@router.get("/runs/{run_id}/events/stream")
async def stream_run_events(request: Request, run_id: str, after_seq: int = 0):
    repo = _repo(request)
    settings = _settings(request)
    if not repo.get_run(run_id):
        raise HTTPException(status_code=404, detail="run not found")

    async def generator():
        seq = max(0, after_seq)
        while True:
            if await request.is_disconnected():
                break
            events = await asyncio.to_thread(repo.list_events, run_id, seq, 200)
            if events:
                for event in events:
                    seq = event["seq"]
                    data = json.dumps(event, ensure_ascii=False)
                    yield f"id: {seq}\nevent: run_event\ndata: {data}\n\n"
            run = await asyncio.to_thread(repo.get_run, run_id)
            if run and run["status"] not in {"starting", "running", "canceling"}:
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


# ----------------------------------------------------------------------
# Notes
# ----------------------------------------------------------------------
@router.get("/projects/{project_id}/notes")
def list_notes(
    request: Request, project_id: str, status: str | None = None
) -> list[dict[str, Any]]:
    repo = _repo(request)
    _require_project(repo, project_id)
    return repo.list_notes(project_id, status=status)


@router.post("/projects/{project_id}/notes")
def create_note(
    request: Request, project_id: str, body: NoteCreate
) -> dict[str, Any]:
    repo = _repo(request)
    _require_project(repo, project_id)

    task_id = body.task_id
    source_run_id = body.source_run_id
    if source_run_id:
        run = repo.get_run(source_run_id)
        if not run:
            raise HTTPException(status_code=404, detail="source run not found")
        run_task = repo.get_task(run["task_id"])
        if not run_task or run_task["project_id"] != project_id:
            raise HTTPException(
                status_code=422, detail="source run does not belong to this project"
            )
        if task_id and task_id != run["task_id"]:
            raise HTTPException(
                status_code=422, detail="task_id does not match the source run"
            )
        task_id = task_id or run["task_id"]
    if task_id:
        task = repo.get_task(task_id)
        if not task or task["project_id"] != project_id:
            raise HTTPException(
                status_code=422, detail="task does not belong to this project"
            )

    return repo.create_note(
        project_id=project_id,
        title=body.title.strip(),
        content_md=body.content_md,
        aliases=body.aliases,
        kind=body.kind,
        status=body.status,
        pinned=body.pinned,
        task_id=task_id,
        source_run_id=source_run_id,
    )


@router.patch("/notes/{note_id}")
def update_note(request: Request, note_id: str, body: NoteUpdate) -> dict[str, Any]:
    repo = _repo(request)
    if not repo.get_note(note_id):
        raise HTTPException(status_code=404, detail="note not found")
    note = repo.update_note(note_id, body.model_dump(exclude_unset=True))
    if not note:
        raise HTTPException(status_code=404, detail="note not found")
    return note


@router.delete("/notes/{note_id}")
def delete_note(request: Request, note_id: str) -> dict[str, bool]:
    repo = _repo(request)
    if not repo.get_note(note_id):
        raise HTTPException(status_code=404, detail="note not found")
    return {"deleted": repo.delete_note(note_id)}


# ----------------------------------------------------------------------
# Global notes
# ----------------------------------------------------------------------
@router.get("/global-notes")
def list_global_notes(
    request: Request, status: str | None = None
) -> list[dict[str, Any]]:
    return _repo(request).list_global_notes(status=status)


@router.post("/global-notes")
def create_global_note(
    request: Request, body: GlobalNoteCreate
) -> dict[str, Any]:
    return _repo(request).create_global_note(
        title=body.title.strip(),
        content_md=body.content_md,
        aliases=body.aliases,
        kind=body.kind,
        status=body.status,
        pinned=body.pinned,
    )


@router.patch("/global-notes/{note_id}")
def update_global_note(
    request: Request, note_id: str, body: GlobalNoteUpdate
) -> dict[str, Any]:
    repo = _repo(request)
    if not repo.get_global_note(note_id):
        raise HTTPException(status_code=404, detail="global note not found")
    note = repo.update_global_note(
        note_id, body.model_dump(exclude_unset=True)
    )
    if not note:
        raise HTTPException(status_code=404, detail="global note not found")
    return note


@router.delete("/global-notes/{note_id}")
def delete_global_note(request: Request, note_id: str) -> dict[str, bool]:
    repo = _repo(request)
    if not repo.get_global_note(note_id):
        raise HTTPException(status_code=404, detail="global note not found")
    return {"deleted": repo.delete_global_note(note_id)}
