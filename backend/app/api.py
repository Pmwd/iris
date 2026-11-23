from __future__ import annotations

import asyncio
import json
import subprocess
from typing import Any

from fastapi import APIRouter, Request

from .api_memory import router as memory_router
from .api_sessions import router as sessions_router
from .api_workspaces import router as workspaces_router
from .config import Settings
from .maintenance import backup_database, list_backups as list_backup_files
from .repository import Repository
from .roles import list_roles

router = APIRouter(prefix="/api")


def _repo(request: Request) -> Repository:
    return request.app.state.repo


def _settings(request: Request) -> Settings:
    return request.app.state.settings


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
        workspace_count = len(repo.list_projects())
    except Exception:
        workspace_count = 0
    result["workspace_count"] = workspace_count
    if cli_info.get("installed"):
        result["status"] = "ok" if cli_info.get("auth_ok") is not False else "degraded"
    return result


@router.post("/maintenance/backup")
def create_backup(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    return backup_database(settings.db_path, settings.data_dir / "backups")


@router.get("/maintenance/backups")
def list_backups(request: Request) -> list[dict[str, Any]]:
    return list_backup_files(_settings(request).data_dir / "backups")


@router.get("/roles")
def roles() -> list[dict[str, Any]]:
    return list_roles()


router.include_router(workspaces_router)
router.include_router(sessions_router)
router.include_router(memory_router)
