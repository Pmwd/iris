from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .repository import Repository
from .repository_facts import FactRepository
from .schemas import FactCreate, FactExtractRequest, FactUpdate
from .services.memory import MemoryError, MemoryManager

router = APIRouter()


def _facts(request: Request) -> FactRepository:
    return request.app.state.fact_repo


def _projects(request: Request) -> Repository:
    return request.app.state.repo


def _memory(request: Request) -> MemoryManager:
    return request.app.state.memory_manager


def _validate_scope(
    projects: Repository, scope: str, project_id: str | None
) -> None:
    if scope == "workspace":
        if not project_id:
            raise HTTPException(
                status_code=422, detail="workspace facts require project_id"
            )
        if not projects.get_project(project_id):
            raise HTTPException(status_code=404, detail="workspace not found")


@router.get("/facts")
def list_facts(
    request: Request,
    status: str | None = None,
    scope: str | None = None,
    project_id: str | None = None,
    role: str | None = None,
    include_global: bool = True,
    limit: int = 500,
) -> list[dict[str, Any]]:
    return _facts(request).list_facts(
        status=status,
        scope=scope,
        project_id=project_id,
        role=role,
        include_global=include_global,
        limit=min(max(limit, 1), 1000),
    )


@router.post("/facts")
def create_fact(request: Request, body: FactCreate) -> dict[str, Any]:
    projects = _projects(request)
    _validate_scope(projects, body.scope, body.project_id)
    return _facts(request).create_fact(
        scope=body.scope,
        project_id=body.project_id if body.scope == "workspace" else None,
        role=body.role,
        kind=body.kind,
        status=body.status,
        title=body.title.strip(),
        content_md=body.content_md,
        aliases=body.aliases,
        pinned=body.pinned,
    )


@router.patch("/facts/{fact_id}")
def update_fact(request: Request, fact_id: str, body: FactUpdate) -> dict[str, Any]:
    facts = _facts(request)
    projects = _projects(request)
    fact = facts.get_fact(fact_id)
    if not fact:
        raise HTTPException(status_code=404, detail="fact not found")

    fields = body.model_dump(exclude_unset=True)
    scope = fields.get("scope", fact["scope"])
    project_id = fields.get("project_id", fact.get("project_id"))
    if scope == "workspace":
        _validate_scope(projects, scope, project_id)
    elif "scope" in fields:
        fields["project_id"] = None

    status = fields.pop("status", None)
    if fields:
        fact = facts.update_fact(fact_id, fields) or fact
    if status == "accepted":
        fact = facts.accept_fact(fact_id, fact.get("supersedes_id")) or fact
    elif status is not None:
        fact = facts.update_fact(fact_id, {"status": status}) or fact
    return fact


@router.delete("/facts/{fact_id}")
def archive_fact(request: Request, fact_id: str) -> dict[str, bool]:
    facts = _facts(request)
    if not facts.get_fact(fact_id):
        raise HTTPException(status_code=404, detail="fact not found")
    return {"archived": facts.archive_fact(fact_id)}


@router.post("/facts/extract")
def extract_facts(
    request: Request, body: FactExtractRequest
) -> dict[str, Any]:
    try:
        return _memory(request).start_extraction(
            role=body.role,
            project_id=body.project_id,
            session_ids=body.session_ids,
            max_sessions=body.max_sessions,
        )
    except MemoryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/fact-extractions")
def list_extractions(
    request: Request, limit: int = 50
) -> list[dict[str, Any]]:
    return _facts(request).list_extractions(limit=min(max(limit, 1), 200))


@router.get("/fact-extractions/{extraction_id}")
def get_extraction(request: Request, extraction_id: str) -> dict[str, Any]:
    extraction = _facts(request).get_extraction(extraction_id)
    if not extraction:
        raise HTTPException(status_code=404, detail="extraction not found")
    return extraction
