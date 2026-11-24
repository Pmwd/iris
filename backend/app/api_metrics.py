from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from .services.metrics import MetricsService

router = APIRouter()

RoleFilter = Literal["coding", "scholar"]
RangeFilter = Literal["24h", "7d", "30d"]


def _metrics(request: Request) -> MetricsService:
    return request.app.state.metrics


@router.get("/metrics/overview")
def metrics_overview(
    request: Request,
    role: RoleFilter | None = None,
    project_id: str | None = None,
    window: RangeFilter = Query("24h", alias="range"),
) -> dict:
    try:
        return _metrics(request).overview(
            role=role, project_id=project_id, window=window
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/metrics/health")
def metrics_health(request: Request) -> dict:
    return _metrics(request).health()


@router.get("/metrics/errors")
def metrics_errors(
    request: Request,
    role: RoleFilter | None = None,
    project_id: str | None = None,
    window: RangeFilter = Query("24h", alias="range"),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict]:
    try:
        return _metrics(request).recent_errors(
            role=role, project_id=project_id, window=window, limit=limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
