from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .repository import Repository
from .repository_facts import FactRepository
from .schemas import (
    FactConfirm,
    FactCreate,
    FactExtractRequest,
    FactMerge,
    FactRemember,
    FactUpdate,
)
from .services.facts import suggest_facts
from .services.memory import MemoryError, MemoryManager
from .services.relations import find_relations

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
    q: str | None = None,
    tag: str | None = None,
    origin: str | None = None,
    stale: bool | None = None,
) -> list[dict[str, Any]]:
    return _facts(request).list_facts(
        status=status,
        scope=scope,
        project_id=project_id,
        role=role,
        include_global=include_global,
        limit=min(max(limit, 1), 1000),
        q=q,
        tag=tag,
        origin=origin,
        stale=stale,
    )


@router.get("/facts/{fact_id}")
def get_fact(request: Request, fact_id: str) -> dict[str, Any]:
    fact = _facts(request).get_fact(fact_id)
    if not fact:
        raise HTTPException(status_code=404, detail="fact not found")
    return fact


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
        tags=body.tags,
        pinned=body.pinned,
        valid_until=body.valid_until,
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


@router.post("/facts/remember")
def remember_fact(
    request: Request, body: FactRemember
) -> dict[str, Any]:
    projects = _projects(request)
    _validate_scope(projects, body.scope, body.project_id)
    try:
        return _memory(request).remember(
            text=body.text,
            title=body.title,
            scope=body.scope,
            project_id=body.project_id,
            role=body.role,
            kind=body.kind,
            aliases=body.aliases,
            tags=body.tags,
            source_session_id=body.source_session_id,
            source_turn_id=body.source_turn_id,
            valid_until=body.valid_until,
            accept=body.accept,
        )
    except MemoryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/facts/{fact_id}/merge")
def merge_fact(
    request: Request, fact_id: str, body: FactMerge
) -> dict[str, Any]:
    facts = _facts(request)
    source = facts.get_fact(fact_id)
    target = facts.get_fact(body.target_fact_id)
    if not source:
        raise HTTPException(status_code=404, detail="fact not found")
    if not target:
        raise HTTPException(status_code=404, detail="target fact not found")
    if target["status"] != "accepted":
        raise HTTPException(status_code=409, detail="target fact must be accepted")
    if (
        source.get("scope") == "workspace"
        and target.get("scope") == "workspace"
        and source.get("project_id") != target.get("project_id")
    ):
        raise HTTPException(
            status_code=409, detail="cannot merge facts from different workspaces"
        )
    if source.get("role") != "both" and target.get("role") != "both" and source.get(
        "role"
    ) != target.get("role"):
        raise HTTPException(status_code=409, detail="cannot merge facts for different roles")

    if body.mode == "merge":
        merged_source, merged_target = facts.merge_fact(
            fact_id, body.target_fact_id, content_md=body.content_md
        )
        if not merged_source or not merged_target:
            raise HTTPException(status_code=409, detail="facts could not be merged")
        return {"mode": "merge", "fact": merged_source, "target": merged_target}
    if body.mode == "supersede":
        updated = facts.accept_fact(fact_id, body.target_fact_id)
        return {
            "mode": "supersede",
            "fact": updated,
            "target": facts.get_fact(body.target_fact_id),
        }
    updated = facts.accept_fact(fact_id) if source["status"] == "candidate" else source
    return {"mode": "keep_both", "fact": updated, "target": target}


@router.post("/facts/{fact_id}/confirm")
def confirm_fact(
    request: Request, fact_id: str, body: FactConfirm
) -> dict[str, Any]:
    fact = _facts(request).confirm_fact(fact_id, body.valid_until)
    if not fact:
        raise HTTPException(status_code=404, detail="fact not found")
    return fact


@router.get("/facts/{fact_id}/sources")
def fact_sources(request: Request, fact_id: str) -> dict[str, Any]:
    sources = _facts(request).fact_sources(fact_id)
    if not sources:
        raise HTTPException(status_code=404, detail="fact not found")
    return sources


@router.get("/memory/related")
def related_memories(
    request: Request,
    q: str,
    role: str = "both",
    project_id: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    if role not in {"coding", "scholar", "both"}:
        raise HTTPException(status_code=422, detail="invalid role")
    result = suggest_facts(
        _facts(request),
        role=role if role != "both" else "both",
        project_id=project_id,
        query=q,
        limit=min(max(limit, 1), 20),
        min_score=request.app.state.settings.fact_min_score,
    )
    return result


@router.get("/memory/inbox")
def memory_inbox(
    request: Request,
    role: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    facts = _facts(request)
    candidates = facts.list_facts(
        status="candidate",
        project_id=project_id,
        role=role,
        include_global=True,
        limit=200,
    )
    accepted = facts.list_facts(
        status="accepted",
        project_id=project_id,
        role=role,
        include_global=True,
        limit=500,
    )
    groups: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        relations = [
            item
            for item in find_relations(candidate, accepted, limit=3)
            if item["relation"] in {"duplicate", "near_duplicate", "conflict"}
        ]
        if relations:
            relation = relations[0]
            key = f"{relation['relation']}:{relation['target_fact_id']}"
            group = groups.setdefault(
                key,
                {
                    "key": key,
                    "kind": relation["relation"],
                    "suggested_action": (
                        "merge"
                        if relation["relation"] in {"duplicate", "near_duplicate"}
                        else "review"
                    ),
                    "score": relation["score"],
                    "target_fact": relation["target"],
                    "candidates": [],
                },
            )
            group["candidates"].append(candidate)
            group["score"] = max(group["score"], relation["score"])
        else:
            key = f"candidate:{candidate['id']}"
            groups[key] = {
                "key": key,
                "kind": "standalone",
                "suggested_action": "accept_or_reject",
                "score": 0,
                "target_fact": None,
                "candidates": [candidate],
            }
    stale = facts.list_facts(
        status="accepted",
        project_id=project_id,
        role=role,
        include_global=True,
        stale=True,
        limit=100,
    )
    return {
        "counts": {
            "candidates": len(candidates),
            "duplicates": sum(
                1
                for group in groups.values()
                if group["kind"] in {"duplicate", "near_duplicate"}
            ),
            "conflicts": sum(
                1 for group in groups.values() if group["kind"] == "conflict"
            ),
            "needs_confirmation": len(stale),
        },
        "groups": list(groups.values()),
        "stale": stale,
    }


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
