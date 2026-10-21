"""FastAPI app factory for the loopback-only desktop backend."""

from __future__ import annotations

import asyncio
import secrets
from datetime import date
from pathlib import Path
from typing import Any, Final, Literal
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from office_ai import __version__
from office_ai.application.agent_catalog import list_agents
from office_ai.application.backups import BackupService, InvalidBackup, MAX_BACKUP_SIZE_BYTES
from office_ai.application.document_library import DocumentLibrary
from office_ai.application.document_preview import DocumentPreview, InvalidDocumentPreview
from office_ai.application.result_export import AgentResultExporter, ResultExportError
from office_ai.application.agent_consent import ConsentRequired
from office_ai.application.agent_request import AgentRequestError, AgentRequestService, MODEL_ID
from office_ai.application.operation_journal import read_recent_operations
from office_ai.application.settings import read_settings, update_setting
from office_ai.domain.agents.task_catalog import serialize_agent_tasks
from office_ai.domain.settings import InvalidSetting
from office_ai.infrastructure.database import LocalDatabase
from office_ai.infrastructure.credential_store import CredentialStoreError, WindowsCredentialStore
from office_ai.infrastructure.openai_responses import OpenAIResponsesAdapter
from office_ai.domain.agents.consent import InvalidTransferDisclosure
from office_ai.application.agent_consent import AgentTransferConsent
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


class AgentTransferPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ids: list[str] = Field(min_length=1, max_length=5)
    instruction: str = Field(default="", max_length=10_000)
    history_id: str = Field(min_length=1, max_length=80)


class AgentTransferConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: StrictBool


class ApiKeyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr = Field(min_length=20, max_length=5_120)


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
    app.state.agent_transfer_consent = AgentTransferConsent()
    app.state.credential_store = None
    app.state.openai_adapter = OpenAIResponsesAdapter()
    app.state.agent_request_service = None
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

        if request.url.path.endswith(("/preview", "/prepare")) or request.url.path.endswith("/ai/key"):
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > 32 * 1024:
                        return JSONResponse({"detail": "Размер запроса превышает ограничение."}, status_code=413)
                except ValueError:
                    return JSONResponse({"detail": "Некорректный размер запроса."}, status_code=400)

        origin = request.headers.get("origin")
        # WebView2 may omit Origin for same-origin GET/PUT requests. The random
        # per-window session token and exact Host check still authenticate those
        # calls. Browsers include Origin on cross-origin fetches and preflights,
        # so keep rejecting every supplied origin except the app's own UI.
        if (origin is not None and origin != expected_origin) or (
            origin is None and request.method == "OPTIONS"
        ):
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
        if origin is not None:
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
            history_entry = app.state.database.record_agent_preview(
                result["agentId"], result["taskCode"], len(result["sources"])
            )
            result["historyEntry"] = history_entry
            return JSONResponse(result)
        except InvalidDocumentPreview as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    def get_credential_store():
        if app.state.credential_store is not None:
            return app.state.credential_store
        try:
            app.state.credential_store = WindowsCredentialStore()
        except CredentialStoreError as error:
            raise HTTPException(status_code=503, detail="Защищённое хранилище ключей недоступно в этой среде.") from error
        return app.state.credential_store

    def get_agent_request_service() -> AgentRequestService:
        if app.state.agent_request_service is None:
            app.state.agent_request_service = AgentRequestService(
                preview=app.state.document_preview,
                consent=app.state.agent_transfer_consent,
                credentials=get_credential_store(),
                provider=app.state.openai_adapter,
                database=app.state.database,
            )
        return app.state.agent_request_service

    @app.get(f"{API_PREFIX}/ai/status")
    async def ai_status() -> dict[str, Any]:
        try:
            configured = get_agent_request_service().is_configured()
            return {"providerAvailable": True, "configured": configured, "providerId": "openai", "modelId": MODEL_ID}
        except HTTPException as error:
            if error.status_code == 503:
                return {"providerAvailable": False, "configured": False, "providerId": "openai", "modelId": MODEL_ID}
            raise
        except CredentialStoreError as error:
            raise HTTPException(status_code=503, detail="Не удалось проверить защищённое хранилище ключей.") from error

    @app.post(f"{API_PREFIX}/ai/key")
    async def save_ai_key(payload: ApiKeyUpdateRequest) -> dict[str, bool]:
        try:
            get_credential_store().save_api_key(payload.api_key.get_secret_value())
        except CredentialStoreError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"configured": True}

    @app.post(f"{API_PREFIX}/ai/key/delete")
    async def delete_ai_key() -> dict[str, bool]:
        try:
            get_credential_store().delete_api_key()
        except CredentialStoreError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"configured": False}

    @app.post(f"{API_PREFIX}/agents/{{agent_id}}/tasks/{{task_code}}/prepare-transfer")
    def prepare_agent_transfer(
        agent_id: str, task_code: str, payload: AgentTransferPrepareRequest
    ) -> dict[str, Any]:
        try:
            manifest = get_agent_request_service().prepare(
                agent_id=agent_id,
                task_code=task_code,
                document_ids=payload.document_ids,
                instruction=payload.instruction,
                history_id=payload.history_id,
            )
        except (AgentRequestError, InvalidTransferDisclosure, InvalidDocumentPreview) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "requestId": manifest.request_id,
            "providerId": manifest.provider_id,
            "modelId": MODEL_ID,
            "agentId": manifest.agent_id,
            "taskCode": manifest.task_code,
            "purpose": manifest.purpose,
            "items": [
                {"id": item.resource_id, "name": item.display_name, "categories": list(item.categories)}
                for item in manifest.items
            ],
            "payloadPreview": manifest.payload_preview,
            "payloadSizeBytes": manifest.payload_size_bytes,
            "payloadSha256": manifest.payload_sha256,
            "createdAt": manifest.created_at.isoformat(),
            "expiresAt": manifest.expires_at.isoformat(),
        }

    @app.post(f"{API_PREFIX}/ai/transfer/{{request_id}}/execute")
    def execute_agent_transfer(request_id: str, payload: AgentTransferConfirmRequest) -> dict[str, Any]:
        try:
            result = get_agent_request_service().execute(request_id, user_confirmed=payload.confirmed)
        except ConsentRequired as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except AgentRequestError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        if result is None:
            return {"cancelled": True}
        return {"cancelled": False, **result}

    @app.post(f"{API_PREFIX}/ai/transfer/{{request_id}}/cancel")
    async def cancel_agent_transfer(request_id: str) -> dict[str, bool]:
        get_agent_request_service().cancel(request_id)
        return {"cancelled": True}

    @app.get(f"{API_PREFIX}/agents/history/{{history_id}}/result")
    async def agent_task_result(history_id: str) -> dict[str, Any]:
        result = app.state.database.get_agent_task_result(history_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Для этой задачи нет сохранённого результата.")
        return result

    @app.get(f"{API_PREFIX}/agents/history/{{history_id}}/export")
    async def export_agent_task_result(history_id: str) -> Response:
        try:
            rendered = AgentResultExporter(app.state.database).render(history_id)
        except ResultExportError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return Response(
            content=rendered.content,
            media_type=rendered.media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{rendered.filename}"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get(f"{API_PREFIX}/agents/history")
    async def agent_history(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, list[dict[str, Any]]]:
        return {"history": app.state.database.list_agent_task_history(limit)}

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
