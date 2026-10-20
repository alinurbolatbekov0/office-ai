"""FastAPI app factory for the loopback-only desktop backend."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Final

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from office_ai import __version__
from office_ai.application.agent_catalog import list_agents

API_PREFIX: Final = "/api/v1"
TOKEN_HEADER: Final = "x-officeai-token"
_ALLOWED_METHODS: Final = {"GET"}


def create_app(
    *,
    expected_host: str,
    expected_origin: str,
    session_token: str,
    frontend_dist: Path | None = None,
) -> FastAPI:
    """Build an app whose API accepts only the current desktop session."""
    app = FastAPI(
        title="Office AI Local API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def guard_local_requests(request: Request, call_next):
        # Host validation also blocks DNS-rebinding hostnames. Uvicorn is bound
        # separately to 127.0.0.1; this check is an additional browser boundary.
        if request.headers.get("host") != expected_host:
            return JSONResponse({"detail": "Недопустимый локальный адрес."}, status_code=400)

        if not request.url.path.startswith(API_PREFIX):
            return await call_next(request)

        origin = request.headers.get("origin")
        if origin != expected_origin:
            return JSONResponse({"detail": "Источник запроса не разрешён."}, status_code=403)

        if request.method == "OPTIONS":
            requested_method = request.headers.get("access-control-request-method", "")
            requested_headers = {
                header.strip().lower()
                for header in request.headers.get("access-control-request-headers", "").split(",")
                if header.strip()
            }
            if requested_method not in _ALLOWED_METHODS or not requested_headers.issubset({TOKEN_HEADER}):
                return JSONResponse({"detail": "Недопустимый preflight-запрос."}, status_code=403)
            return Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": expected_origin,
                    "Access-Control-Allow-Methods": ", ".join(sorted(_ALLOWED_METHODS)),
                    "Access-Control-Allow-Headers": TOKEN_HEADER,
                    "Access-Control-Max-Age": "300",
                    "Vary": "Origin",
                },
            )

        if request.method not in _ALLOWED_METHODS:
            return JSONResponse({"detail": "Метод не поддерживается."}, status_code=405)

        supplied_token = request.headers.get(TOKEN_HEADER, "")
        if not secrets.compare_digest(supplied_token, session_token):
            return JSONResponse({"detail": "Сессия приложения не подтверждена."}, status_code=403)

        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = expected_origin
        response.headers["Vary"] = "Origin"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get(f"{API_PREFIX}/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "application": "Office AI", "version": __version__}

    @app.get(f"{API_PREFIX}/agents")
    async def agents() -> dict[str, list[dict[str, str]]]:
        return {"agents": list_agents()}

    if frontend_dist is not None and (frontend_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app
