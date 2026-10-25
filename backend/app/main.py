from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from .api import router
from .config import PROJECT_ROOT, Settings, load_settings
from .db import Database
from .logging_setup import configure_logging
from .repository import Repository
from .services.research import ResearchManager
from .services.runs import RunManager

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    logger = configure_logging(settings.data_dir)
    database = Database(settings.db_path)
    database.init()
    repo = Repository(database)
    reconciled = repo.reconcile_interrupted_runs()
    logger.info(
        "Iris started data_dir=%s db=%s reconciled_runs=%s",
        settings.data_dir,
        settings.db_path,
        reconciled,
    )
    run_manager = RunManager(repo, settings)
    research_manager = ResearchManager(repo, settings)
    research_manager.reconcile_interrupted_jobs()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await asyncio.to_thread(research_manager.shutdown)
        await asyncio.to_thread(run_manager.shutdown)

    app = FastAPI(title="Iris", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.repo = repo
    app.state.run_manager = run_manager
    app.state.research_manager = research_manager

    def guarded_error(detail: str, status_code: int) -> JSONResponse:
        response = JSONResponse({"detail": detail}, status_code=status_code)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        host = request.headers.get("host", "")
        hostname = urlsplit(f"//{host}").hostname
        if hostname not in LOCAL_HOSTS:
            return guarded_error(
                "Iris only accepts requests addressed to a local host.", 403
            )

        origin = request.headers.get("origin")
        if origin:
            origin_host = urlsplit(origin).hostname
            if origin_host not in LOCAL_HOSTS:
                return guarded_error("Cross-origin requests are not allowed.", 403)

        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/"):
            if request.headers.get("x-iris-client") != "web":
                return guarded_error("Missing X-Iris-Client header.", 403)
            if request.method in {"POST", "PUT", "PATCH"}:
                content_type = (
                    request.headers.get("content-type", "")
                    .split(";")[0]
                    .strip()
                    .lower()
                )
                content_length = request.headers.get("content-length")
                if content_type and content_type != "application/json":
                    return guarded_error(
                        "Mutating API requests must use application/json.", 415
                    )
                if not content_type and content_length not in (None, "0"):
                    return guarded_error(
                        "Mutating API requests must use application/json.", 415
                    )

        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response

    app.include_router(router)

    frontend_dist = PROJECT_ROOT / "frontend" / "dist"
    if frontend_dist.is_dir():
        dist_root = frontend_dist.resolve()
        index_file = dist_root / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        async def frontend(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="not found")
            if not full_path:
                return FileResponse(index_file)
            candidate = (dist_root / full_path).resolve()
            if dist_root not in candidate.parents:
                raise HTTPException(status_code=404, detail="not found")
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index_file)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
