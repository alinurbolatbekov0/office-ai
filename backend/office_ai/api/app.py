"""FastAPI app factory for the loopback-only desktop backend."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any, Final

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from office_ai import __version__
from office_ai.application.agent_catalog import list_agents
from office_ai.application.operation_journal import read_recent_operations
from office_ai.application.settings import read_settings, update_setting
from office_ai.domain.settings import InvalidSetting
from office_ai.infrastructure.database import LocalDatabase
from office_ai.infrastructure.storage_paths import get_user_data_directory

API_PREFIX: Final = "/api/v1"
TOKEN_HEADER: Final = "x-officeai-token"
_ALLOWED_METHODS: Final = {"GET", "PUT"}
_ALLOWED_HEADERS: Final = {TOKEN_HEADER, "content-type"}


class SettingUpdateRequest(BaseModel):
    value: Any


def create_app(
    *,
    expected_host: str,
    expected_origin: str,
    session_token: str,
    frontend_dist: Path | None = None,
    data_directory: Path | None = None,
) -> FastAPI:
    """Build an app whose API accepts only the current desktop session."""
    app = FastAPI(
        title="Office AI Local API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    database = LocalDatabase(data_directory or get_user_data_directory())
    database.initialize()
    database.record_operation("app_started", message_code="app_started")
    app.state.database = database

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
            if requested_method not in _ALLOWED_METHODS or not requested_headers.issubset(_ALLOWED_HEADERS):
                return JSONResponse({"detail": "Недопустимый preflight-запрос."}, status_code=403)
            return Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": expected_origin,
                    "Access-Control-Allow-Methods": ", ".join(sorted(_ALLOWED_METHODS)),
                    "Access-Control-Allow-Headers": ", ".join(sorted(_ALLOWED_HEADERS)),
                    "Access-Control-Max-Age": "300",
                    "Vary": "Origin",
                },
            )

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

    @app.get(f"{API_PREFIX}/settings")
    async def settings() -> dict[str, dict[str, Any]]:
        return {"settings": read_settings(app.state.database)}

    @app.put(f"{API_PREFIX}/settings/{{setting_key}}")
    async def save_setting(setting_key: str, payload: SettingUpdateRequest) -> dict[str, dict[str, Any]]:
        try:
            values = update_setting(app.state.database, setting_key, payload.value)
        except InvalidSetting as error:
            raise HTTPException(status_code=422, detail="Неизвестная настройка или недопустимое значение.") from error
        return {"settings": values}

    @app.get(f"{API_PREFIX}/operations")
    async def operations(limit: int = Query(default=50, ge=1, le=100)) -> dict[str, list[dict[str, object]]]:
        return {"operations": read_recent_operations(app.state.database, limit)}

    if frontend_dist is not None and (frontend_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app
