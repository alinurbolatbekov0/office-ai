"""FastAPI app factory for the loopback-only desktop backend."""

from __future__ import annotations

import asyncio
import secrets
from datetime import date
from pathlib import Path
from typing import Any, Final, Literal
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from office_ai import __version__
from office_ai.application.agent_catalog import list_agents
from office_ai.application.backups import BackupService, InvalidBackup, MAX_BACKUP_SIZE_BYTES
from office_ai.application.document_library import DocumentLibrary
from office_ai.application.document_preview import DocumentPreview, InvalidDocumentPreview
from office_ai.application.operation_journal import read_recent_operations
from office_ai.application.settings import read_settings, update_setting
from office_ai.domain.agents.task_catalog import serialize_agent_tasks
from office_ai.domain.settings import InvalidSetting
from office_ai.infrastructure.database import LocalDatabase
from office_ai.infrastructure.storage_paths import get_user_data_directory
from office_ai.domain.documents import InvalidDocument, MAX_DOCUMENT_SIZE_BYTES

API_PREFIX: Final = "/api/v1"
TOKEN_HEADER: Final = "x-officeai-token"
_ALLOWED_METHODS: Final = {"GET", "PUT", "POST"}
_ALLOWED_HEADERS: Final = {
    TOKEN_HEADER,
    "content-type",
    "x-officeai-filename",
    "x-officeai-confirm-duplicate",
    "x-officeai-confirm-restore",
}


class SettingUpdateRequest(BaseModel):
    value: Any


class AgentPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ids: list[str] = Field(min_length=1, max_length=5)
    instruction: str = Field(default="", max_length=10_000)


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
    app.state.document_library = DocumentLibrary(database)
    app.state.document_preview = DocumentPreview(app.state.document_library)
    app.state.backup_service = BackupService(database)
    # Keep file/database operations serial for this single-user local app. This
    # also ensures no upload or settings write overlaps a restore swap.
    app.state.data_operation_lock = asyncio.Lock()

    @app.middleware("http")
    async def guard_local_requests(request: Request, call_next):
        # Host validation also blocks DNS-rebinding hostnames. Uvicorn is bound
        # separately to 127.0.0.1; this check is an additional browser boundary.
        if request.headers.get("host") != expected_host:
            return JSONResponse({"detail": "Недопустимый локальный адрес."}, status_code=400)

        if not request.url.path.startswith(API_PREFIX):
            return await call_next(request)

        if request.url.path.endswith("/preview"):
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > 32 * 1024:
                        return JSONResponse({"detail": "Запрос предпросмотра превышает ограничение."}, status_code=413)
                except ValueError:
                    return JSONResponse({"detail": "Некорректный размер запроса."}, status_code=400)

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

        if request.method not in _ALLOWED_METHODS:
            return JSONResponse({"detail": "Метод не поддерживается."}, status_code=405)

        supplied_token = request.headers.get(TOKEN_HEADER, "")
        if not secrets.compare_digest(supplied_token, session_token):
            return JSONResponse({"detail": "Сессия приложения не подтверждена."}, status_code=403)

        async with app.state.data_operation_lock:
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

    @app.get(f"{API_PREFIX}/agents/{{agent_id}}/tasks")
    async def agent_tasks(agent_id: str) -> dict[str, list[dict[str, object]]]:
        tasks = serialize_agent_tasks(agent_id)
        if not tasks:
            raise HTTPException(status_code=404, detail="Агент не найден.")
        return {"tasks": tasks}

    @app.post(f"{API_PREFIX}/agents/{{agent_id}}/tasks/{{task_code}}/preview")
    def agent_task_preview(agent_id: str, task_code: str, payload: AgentPreviewRequest) -> JSONResponse:
        try:
            result = app.state.document_preview.create(
                agent_id=agent_id,
                task_code=task_code,
                document_ids=payload.document_ids,
                instruction=payload.instruction,
            )
            return JSONResponse(result)
        except InvalidDocumentPreview as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

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

    @app.get(f"{API_PREFIX}/documents")
    async def documents(
        search: str = Query(default="", max_length=200),
        document_type: Literal["DOCX", "XLSX", "PPTX", "PDF", "JPEG", "PNG"] | None = Query(default=None, alias="type"),
        imported_from: date | None = None,
        imported_to: date | None = None,
        sort_by: Literal["name", "imported_at", "size_bytes", "type"] = "imported_at",
        sort_order: Literal["asc", "desc"] = "desc",
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        if imported_from and imported_to and imported_from > imported_to:
            raise HTTPException(status_code=422, detail="Начальная дата позже конечной.")
        entries, total = app.state.document_library.query(
            search=search,
            detected_type=document_type,
            imported_from=imported_from.isoformat() if imported_from else None,
            imported_to=imported_to.isoformat() if imported_to else None,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )
        return {"documents": entries, "total": total}

    @app.post(f"{API_PREFIX}/documents", status_code=201, response_model=None)
    async def upload_document(request: Request) -> Any:
        encoded_name = request.headers.get("x-officeai-filename", "")
        if not encoded_name:
            raise HTTPException(status_code=400, detail="Не задано имя файла.")
        try:
            original_name = unquote(encoded_name, encoding="utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise HTTPException(status_code=400, detail="Имя файла имеет неверную кодировку.") from error
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/octet-stream":
            raise HTTPException(status_code=415, detail="Ожидалось тело файла application/octet-stream.")
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_DOCUMENT_SIZE_BYTES:
                    raise HTTPException(status_code=413, detail="Размер файла превышает ограничение 100 МиБ.")
            except ValueError as error:
                raise HTTPException(status_code=400, detail="Некорректный размер запроса.") from error

        async def chunks():
            async for chunk in request.stream():
                yield chunk

        try:
            result = await app.state.document_library.upload(
                original_name,
                chunks(),
                allow_duplicate=request.headers.get("x-officeai-confirm-duplicate") == "true",
            )
        except InvalidDocument as error:
            return JSONResponse({"detail": str(error)}, status_code=422)
        if result["duplicate"] and not result.get("confirmed"):
            return JSONResponse(result, status_code=409)
        return result

    @app.get(f"{API_PREFIX}/documents/{{document_id}}/download")
    async def download_document(document_id: str) -> FileResponse:
        result = app.state.document_library.get_download(document_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Документ не найден.")
        path, filename = result
        media_types = {
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "pdf": "application/pdf",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
        }
        return FileResponse(
            path,
            media_type=media_types[filename.rsplit(".", 1)[-1].lower()],
            filename=filename,
            headers={"X-Content-Type-Options": "nosniff"},
        )

    @app.post(f"{API_PREFIX}/backups", status_code=201)
    async def create_backup(payload: dict[str, Any]) -> dict[str, Any]:
        if payload != {}:
            raise HTTPException(status_code=400, detail="Создание копии не принимает тело запроса.")
        try:
            result = app.state.backup_service.create_backup()
        except InvalidBackup as error:
            database.record_operation(
                "backup_created",
                outcome="failure",
                message_code="backup_created",
            )
            raise HTTPException(status_code=422, detail=str(error)) from error
        database.record_operation("backup_created", message_code="backup_created")
        return result

    @app.get(f"{API_PREFIX}/backups/{{backup_id}}/download")
    async def download_backup(backup_id: str) -> FileResponse:
        result = app.state.backup_service.get_backup_download(backup_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Резервная копия не найдена.")
        path, filename = result
        return FileResponse(
            path,
            media_type="application/zip",
            filename=filename,
            headers={"X-Content-Type-Options": "nosniff"},
        )

    @app.post(f"{API_PREFIX}/restore")
    async def restore_backup(request: Request) -> dict[str, str]:
        if request.headers.get("x-officeai-confirm-restore") != "true":
            raise HTTPException(status_code=400, detail="Для восстановления требуется явное подтверждение.")
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/octet-stream":
            raise HTTPException(status_code=415, detail="Ожидался архив application/octet-stream.")
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_BACKUP_SIZE_BYTES:
                    raise HTTPException(status_code=413, detail="Размер архива превышает ограничение 2 ГиБ.")
            except ValueError as error:
                raise HTTPException(status_code=400, detail="Некорректный размер запроса.") from error

        async def chunks():
            async for chunk in request.stream():
                yield chunk

        upload_path: Path | None = None
        try:
            upload_path = await app.state.backup_service.receive_restore_upload(chunks())
            app.state.backup_service.restore_archive(upload_path)
        except InvalidBackup as error:
            database.record_operation("backup_restore_rejected", outcome="failure", message_code="backup_restore_rejected")
            raise HTTPException(status_code=422, detail=str(error)) from error
        finally:
            if upload_path is not None:
                upload_path.unlink(missing_ok=True)
        return {"status": "restored"}

    if frontend_dist is not None and (frontend_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app
