"""Focused checks for the scaffold's local API boundary."""

import asyncio
import hashlib
import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from types import SimpleNamespace
import unittest
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile
import io

from fastapi import FastAPI
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from office_ai.api.app import AgentPreviewRequest, AgentTransferConfirmRequest, AgentTransferPrepareRequest, create_app
from office_ai.application.backups import BackupService, InvalidBackup
from office_ai.application.document_preview import InvalidDocumentPreview
from office_ai.domain.documents import InvalidDocument
from office_ai.desktop import DesktopBridge, RuntimeConfig, _start_backend
from office_ai.infrastructure.database import LocalDatabase
from office_ai.infrastructure.storage_paths import get_user_data_directory


class LocalApiSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.data_directory = Path(temporary_directory.name)
        app = create_app(
            expected_host="127.0.0.1:43127",
            expected_origin="http://127.0.0.1:5173",
            session_token="test-session-token",
            data_directory=self.data_directory,
        )
        self.app = app
        self.headers = {
            "host": "127.0.0.1:43127",
            "origin": "http://127.0.0.1:5173",
            "x-officeai-token": "test-session-token",
        }

    def test_backend_listener_binds_only_to_ipv4_loopback(self) -> None:
        stub_app = FastAPI()
        stub_app.state.backup_service = object()
        listener = SimpleNamespace(
            getsockname=lambda: ("127.0.0.1", 43128),
            bind=lambda address: setattr(listener, "bound", address),
            listen=lambda _limit: None,
        )
        server = SimpleNamespace(started=True, should_exit=False, run=lambda **_kwargs: None)
        thread = SimpleNamespace(start=lambda: None, is_alive=lambda: True)
        with (
            patch("office_ai.desktop.create_app", return_value=stub_app),
            patch("office_ai.desktop.socket.socket", return_value=listener) as socket_factory,
            patch("office_ai.desktop.uvicorn.Config") as config_factory,
            patch("office_ai.desktop.uvicorn.Server", return_value=server),
            patch("office_ai.desktop.threading.Thread", return_value=thread),
        ):
            _, _, _, port, _, _ = _start_backend(
                "synthetic-session-token",
                "http://127.0.0.1:5173",
            )
        self.assertEqual(port, 43128)
        self.assertEqual(listener.bound, ("127.0.0.1", 0))
        socket_factory.assert_called_once()
        self.assertEqual(config_factory.call_args.kwargs["host"], "127.0.0.1")

    def request(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        method: str = "GET",
        body: bytes = b"",
    ) -> tuple[int, bytes, dict[str, str]]:
        request_headers = headers or self.headers
        raw_headers = [(key.lower().encode(), value.encode()) for key, value in request_headers.items()]
        parsed_path = urlsplit(path)
        path_only = parsed_path.path
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path_only,
            "raw_path": path_only.encode(),
            "query_string": parsed_path.query.encode(),
            "root_path": "",
            "headers": raw_headers,
            "client": ("127.0.0.1", 45678),
            "server": ("127.0.0.1", 43127),
        }
        messages: list[dict] = []
        received_count = 0
        response_complete = asyncio.Event()

        async def receive() -> dict:
            nonlocal received_count
            if received_count == 0:
                received_count += 1
                return {"type": "http.request", "body": body, "more_body": bool(body)}
            if received_count == 1 and body:
                received_count += 1
                return {"type": "http.request", "body": b"", "more_body": False}
            if not response_complete.is_set():
                await response_complete.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict) -> None:
            messages.append(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                response_complete.set()

        async def invoke() -> None:
            await self.app(scope, receive, send)

        asyncio.run(invoke())
        start = next(message for message in messages if message["type"] == "http.response.start")
        body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        response_headers = {
            key.decode().lower(): value.decode()
            for key, value in start.get("headers", [])
        }
        return start["status"], body, response_headers

    def test_health_requires_expected_origin_and_token(self) -> None:
        status, body, _ = self.request("/api/v1/health", self.headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")

        missing_token = {key: value for key, value in self.headers.items() if key != "x-officeai-token"}
        self.assertEqual(self.request("/api/v1/health", missing_token)[0], 403)

        wrong_origin = {**self.headers, "origin": "http://localhost:5173"}
        self.assertEqual(self.request("/api/v1/health", wrong_origin)[0], 403)

    def test_wrong_host_is_rejected(self) -> None:
        headers = {**self.headers, "host": "attacker.example"}
        self.assertEqual(self.request("/api/v1/health", headers)[0], 400)

    def test_agent_catalog_contains_four_prepared_agents(self) -> None:
        status, body, _ = self.request("/api/v1/agents", self.headers)
        agents = json.loads(body)["agents"]
        self.assertEqual(status, 200)
        self.assertEqual(len(agents), 4)
        self.assertTrue(all(agent["status"] == "prepared" for agent in agents))

    def test_only_read_methods_are_available(self) -> None:
        self.assertEqual(self.request("/api/v1/health", self.headers, method="POST")[0], 405)

    def test_preflight_allows_only_the_local_ui_origin_and_token_header(self) -> None:
        headers = {
            "host": "127.0.0.1:43127",
            "origin": "http://127.0.0.1:5173",
            "access-control-request-method": "PUT",
            "access-control-request-headers": "content-type, x-officeai-token",
        }
        status, _, response_headers = self.request("/api/v1/health", headers, method="OPTIONS")
        self.assertEqual(status, 204)
        self.assertEqual(response_headers["access-control-allow-origin"], "http://127.0.0.1:5173")

        unsafe_headers = {**headers, "access-control-request-headers": "authorization"}
        self.assertEqual(self.request("/api/v1/health", unsafe_headers, method="OPTIONS")[0], 403)

    def test_schema_is_versioned_and_database_stays_under_injected_user_data_root(self) -> None:
        database_path = self.data_directory / "officeai.sqlite3"
        self.assertTrue(database_path.is_file())
        self.assertEqual(database_path.parent, self.data_directory)
        with closing(sqlite3.connect(database_path)) as connection, connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(
                connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
                4,
            )
            self.assertIn(
                "documents",
                {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")},
            )

    def test_version_one_database_migrates_without_losing_settings(self) -> None:
        legacy_path = self.data_directory / "legacy"
        legacy_path.mkdir()
        database_path = legacy_path / "officeai.sqlite3"
        with closing(sqlite3.connect(database_path)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
                INSERT INTO schema_migrations VALUES (1, '2026-01-01T00:00:00Z');
                CREATE TABLE app_settings(setting_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL);
                INSERT INTO app_settings VALUES ('theme', '"dark"', '2026-01-01T00:00:00Z');
                INSERT INTO app_settings VALUES ('confirm_destructive_actions', 'true', '2026-01-01T00:00:00Z');
                CREATE TABLE operation_log(
                    id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL, operation_code TEXT NOT NULL,
                    outcome TEXT NOT NULL, entity_type TEXT, entity_id TEXT, message_code TEXT NOT NULL
                );
                PRAGMA user_version = 1;
                """
            )
        database = LocalDatabase(legacy_path)
        database.initialize()
        self.assertEqual(database.get_settings()["theme"], "dark")
        with closing(sqlite3.connect(database_path)) as connection, connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(
                [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")],
                [1, 2, 3, 4],
            )

    def test_windows_data_directory_uses_local_app_data(self) -> None:
        with patch("office_ai.infrastructure.storage_paths.sys.platform", "win32"):
            with patch.dict("os.environ", {"LOCALAPPDATA": r"C:\Users\Tester\AppData\Local"}):
                self.assertTrue(str(get_user_data_directory()).endswith("OfficeAI"))
            with patch.dict("os.environ", {}, clear=True):
                with self.assertRaises(RuntimeError):
                    get_user_data_directory()

    def test_settings_persist_and_journal_never_contains_values(self) -> None:
        status, body, _ = self.request("/api/v1/settings")
        self.assertEqual(status, 200)
        self.assertEqual(
            json.loads(body)["settings"],
            {"theme": "light", "confirm_destructive_actions": True},
        )

        payload = json.dumps({"value": "dark"}).encode()
        headers = {**self.headers, "content-type": "application/json"}
        status, body, _ = self.request("/api/v1/settings/theme", headers, method="PUT", body=payload)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["settings"]["theme"], "dark")

        app_after_restart = create_app(
            expected_host="127.0.0.1:43127",
            expected_origin="http://127.0.0.1:5173",
            session_token="new-session-token",
            data_directory=self.data_directory,
        )
        self.app = app_after_restart
        next_headers = {**self.headers, "x-officeai-token": "new-session-token"}
        status, body, _ = self.request("/api/v1/settings", next_headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["settings"]["theme"], "dark")

        status, body, _ = self.request("/api/v1/operations", next_headers)
        self.assertEqual(status, 200)
        events = json.loads(body)["operations"]
        self.assertTrue(any(event["operationCode"] == "setting_updated" for event in events))
        self.assertNotIn("dark", body.decode())

    def test_unknown_or_invalid_settings_are_rejected(self) -> None:
        headers = {**self.headers, "content-type": "application/json"}
        invalid_value = self.request(
            "/api/v1/settings/theme",
            headers,
            method="PUT",
            body=b'{"value":"auto"}',
        )
        unknown_key = self.request(
            "/api/v1/settings/unknown",
            headers,
            method="PUT",
            body=b'{"value":"x"}',
        )
        self.assertEqual(invalid_value[0], 422)
        self.assertEqual(unknown_key[0], 422)

    def upload(self, name: str, contents: bytes, *, confirm_duplicate: bool = False) -> tuple[int, bytes, dict[str, str]]:
        headers = {
            **self.headers,
            "content-type": "application/octet-stream",
            "x-officeai-filename": quote(name, safe=""),
        }
        if confirm_duplicate:
            headers["x-officeai-confirm-duplicate"] = "true"
        return self.request("/api/v1/documents", headers, method="POST", body=contents)

    @staticmethod
    def office_fixture(extension: str, parts: dict[str, str]) -> bytes:
        required_parts = {
            "docx": "word/document.xml",
            "xlsx": "xl/workbook.xml",
            "pptx": "ppt/presentation.xml",
        }
        buffer = io.BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            if required_parts[extension] not in parts:
                archive.writestr(required_parts[extension], "<root/>")
            for name, content in parts.items():
                archive.writestr(name, content)
        return buffer.getvalue()

    @staticmethod
    def pdf_fixture(text: str | None) -> bytes:
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        if text:
            font = DictionaryObject()
            font[NameObject("/F1")] = writer._add_object(
                DictionaryObject({
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                })
            )
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): font})
            stream = DecodedStreamObject()
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(stream)
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()

    def preview(self, agent: str, task: str, document_ids: list[str], instruction: str = "") -> dict[str, object]:
        return self.app.state.document_preview.create(
            agent_id=agent,
            task_code=task,
            document_ids=document_ids,
            instruction=instruction,
        )

    def test_upload_detects_duplicates_and_requires_explicit_confirmation(self) -> None:
        original = b"%PDF-1.7\nsynthetic anonymized test fixture\n%%EOF"
        status, body, _ = self.upload("Тестовый отчёт.pdf", original)
        self.assertEqual(status, 201)
        document = json.loads(body)["document"]
        self.assertEqual(document["type"], "PDF")
        self.assertEqual(document["sizeBytes"], len(original))

        duplicate_status, duplicate_body, _ = self.upload("Копия.pdf", original)
        self.assertEqual(duplicate_status, 409)
        self.assertEqual(len(json.loads(duplicate_body)["existingDocuments"]), 1)

        path, download_name = self.app.state.document_library.get_download(document["id"])
        downloaded = path.read_bytes()
        self.assertEqual(downloaded, original)
        self.assertEqual(hashlib.sha256(downloaded).hexdigest(), document["sha256"])
        self.assertEqual(download_name, "Тестовый отчёт.pdf")
        self.assertEqual(
            self.request("/api/v1/documents/not-a-uuid/download", self.headers)[0],
            404,
        )

        confirmed_status, confirmed_body, _ = self.upload("Копия.pdf", original, confirm_duplicate=True)
        self.assertEqual(confirmed_status, 201)
        self.assertTrue(json.loads(confirmed_body)["confirmed"])
        with closing(sqlite3.connect(self.data_directory / "officeai.sqlite3")) as connection, connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM stored_files").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 2)
        _, journal_body, _ = self.request("/api/v1/operations", self.headers)
        journal = journal_body.decode()
        self.assertNotIn("synthetic anonymized test fixture", journal)
        self.assertNotIn("Тестовый отчёт.pdf", journal)

    def test_download_refuses_storage_key_outside_document_root(self) -> None:
        status, body, _ = self.upload("Безопасный.pdf", b"%PDF-1.7\nfixture")
        self.assertEqual(status, 201)
        document_id = json.loads(body)["document"]["id"]
        with closing(sqlite3.connect(self.data_directory / "officeai.sqlite3")) as connection, connection:
            connection.execute(
                "UPDATE stored_files SET storage_key = ? WHERE id = "
                "(SELECT stored_file_id FROM documents WHERE id = ?)",
                ("documents/../../outside.bin", document_id),
            )

        self.assertEqual(
            self.request(f"/api/v1/documents/{document_id}/download", self.headers)[0],
            404,
        )

    def test_all_supported_office_open_xml_containers_are_detected(self) -> None:
        main_parts = {
            "xlsx": ("XLSX", "xl/workbook.xml"),
            "pptx": ("PPTX", "ppt/presentation.xml"),
        }
        for extension, (expected_type, main_part) in main_parts.items():
            with self.subTest(extension=extension):
                buffer = io.BytesIO()
                with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
                    archive.writestr("[Content_Types].xml", "<Types/>")
                    archive.writestr(main_part, "<root/>")
                status, body, _ = self.upload(f"Тест.{extension}", buffer.getvalue())
                self.assertEqual(status, 201)
                self.assertEqual(json.loads(body)["document"]["type"], expected_type)

    def test_upload_limit_stops_streaming_and_cleans_temporary_file(self) -> None:
        library = self.app.state.document_library

        async def oversized_chunks():
            yield b"%PDF-"
            yield b"1234"

        with patch("office_ai.application.document_library.MAX_DOCUMENT_SIZE_BYTES", 8):
            with self.assertRaises(InvalidDocument):
                asyncio.run(library.upload("large.pdf", oversized_chunks()))
        self.assertEqual(list((self.data_directory / "documents" / ".tmp").iterdir()), [])

    def test_png_and_jpeg_signatures_require_complete_image_end_markers(self) -> None:
        png_chunks = (
            b"\x89PNG\r\n\x1a\n"
            + b"\x00\x00\x00\rIHDR"
            + (1).to_bytes(4, "big")
            + (1).to_bytes(4, "big")
            + b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            + b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        self.assertEqual(self.upload("пиксель.png", png_chunks)[0], 201)
        self.assertEqual(self.upload("not-image.jpg", b"\xff\xd8\xffbroken")[0], 422)

    def test_jpeg_and_jpg_extensions_are_both_supported(self) -> None:
        for extension in ("jpg", "jpeg"):
            with self.subTest(extension=extension):
                fixture = b"\xff\xd8\xffsynthetic-image-" + extension.encode("ascii") + b"\xff\xd9"
                status, body, _ = self.upload(f"фото.{extension}", fixture)
                self.assertEqual(status, 201)
                self.assertEqual(json.loads(body)["document"]["type"], "JPEG")

    def test_file_signatures_extensions_and_original_names_are_validated(self) -> None:
        mismatch_status = self.upload("fake.png", b"%PDF-1.7\\nnot a PNG")[0]
        unsupported_status = self.upload("notes.txt", b"some text")[0]
        traversal_status, traversal_body, _ = self.upload("../../Часть.pdf", b"%PDF-1.7\\nsynthetic")
        self.assertEqual(mismatch_status, 422)
        self.assertEqual(unsupported_status, 422)
        self.assertEqual(traversal_status, 201)
        self.assertEqual(json.loads(traversal_body)["document"]["name"], "Часть.pdf")

    def test_library_search_is_unicode_case_insensitive_and_sort_is_allowlisted(self) -> None:
        self.assertEqual(self.upload("Отчёт ҚАЗАҚ.pdf", b"%PDF-1.7\\nfixture")[0], 201)
        search = urlencode({"search": "қазақ", "sort_by": "name", "sort_order": "asc"})
        status, body, _ = self.request(f"/api/v1/documents?{search}", self.headers)
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["documents"][0]["name"], "Отчёт ҚАЗАҚ.pdf")

        invalid_sort = self.request("/api/v1/documents?sort_by=original_name%3Bdrop+table", self.headers)
        self.assertEqual(invalid_sort[0], 422)

    def test_office_container_is_checked_without_extracting(self) -> None:
        buffer = io.BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "<document/>")
        status, body, _ = self.upload("Контракт.docx", buffer.getvalue())
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(body)["document"]["type"], "DOCX")

    def test_docx_agent_preview_is_local_read_only_and_not_journaled(self) -> None:
        source_text = "Құжаттың синтетикалық мәтіні / Текст синтетического документа"
        original = self.office_fixture(
            "docx",
            {
                "word/document.xml": (
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    f"<w:body><w:p><w:r><w:t>{source_text}</w:t></w:r></w:p></w:body></w:document>"
                )
            },
        )
        status, uploaded, _ = self.upload("Synthetic.docx", original)
        self.assertEqual(status, 201)
        document = json.loads(uploaded)["document"]
        stored_path, _ = self.app.state.document_library.get_download(document["id"])
        before = stored_path.read_bytes()

        result = self.preview(
            "document-management",
            "consolidate-files",
            [document["id"]],
            "Кратко перечисли ключевые сведения",
        )

        self.assertIn(source_text, result["payloadPreview"])
        self.assertIn("Кратко перечисли ключевые сведения", result["payloadPreview"])
        self.assertEqual(stored_path.read_bytes(), before)
        self.assertEqual(list((self.data_directory / "documents").glob("*.bin")), [stored_path])
        _, journal_body, _ = self.request("/api/v1/operations", self.headers)
        self.assertNotIn(source_text, journal_body.decode())

    def test_agent_preview_api_handler_returns_the_service_preview(self) -> None:
        source_text = "Синтетический фрагмент для теста API"
        original = self.office_fixture(
            "docx",
            {
                "word/document.xml": (
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    f"<w:body><w:p><w:r><w:t>{source_text}</w:t></w:r></w:p></w:body></w:document>"
                )
            },
        )
        status, uploaded, _ = self.upload("Synthetic API.docx", original)
        self.assertEqual(status, 201)
        document_id = json.loads(uploaded)["document"]["id"]
        route_path = "/api/v1/agents/{agent_id}/tasks/{task_code}/preview"
        route = next(route for route in self.app.routes if getattr(route, "path", None) == route_path)
        payload = AgentPreviewRequest(document_ids=[document_id], instruction="Только локальная подготовка")

        response = route.endpoint("document-management", "consolidate-files", payload)

        self.assertEqual(response.status_code, 200)
        preview = json.loads(response.body)
        self.assertIn(source_text, preview["payloadPreview"])
        self.assertEqual(preview["sources"][0]["id"], document_id)
        self.assertEqual(preview["historyEntry"]["sourceCount"], 1)
        history = self.app.state.database.list_agent_task_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["taskCode"], "consolidate-files")
        with closing(sqlite3.connect(self.data_directory / "officeai.sqlite3")) as connection, connection:
            history_columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_task_history)")}
            persisted_row = connection.execute("SELECT * FROM agent_task_history").fetchone()
        self.assertNotIn("instruction", history_columns)
        self.assertNotIn("payload", history_columns)
        self.assertNotIn(source_text, repr(persisted_row))

    def test_ai_transfer_api_requires_an_explicit_confirmation_and_stores_only_result(self) -> None:
        source_text = "Synthetic approved-only source"
        original = self.office_fixture(
            "docx",
            {
                "word/document.xml": (
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    f"<w:body><w:p><w:r><w:t>{source_text}</w:t></w:r></w:p></w:body></w:document>"
                )
            },
        )
        status, uploaded, _ = self.upload("Synthetic approval.docx", original)
        self.assertEqual(status, 201)
        document_id = json.loads(uploaded)["document"]["id"]
        preview = self.preview("document-management", "consolidate-files", [document_id])
        history = self.app.state.database.record_agent_preview(
            "document-management", "consolidate-files", len(preview["sources"])
        )

        class FakeCredentials:
            def read_api_key(self):
                return "sk-synthetic-api-key-for-tests-only"

            def save_api_key(self, _value):
                raise AssertionError("Test must not save a real API key")

            def delete_api_key(self):
                return None

        class FakeProvider:
            def __init__(self):
                self.calls = []

            def generate(self, payload, api_key):
                self.calls.append((payload, api_key))
                return "Synthetic AI draft"

        self.app.state.credential_store = FakeCredentials()
        self.app.state.openai_adapter = FakeProvider()
        self.app.state.agent_request_service = None
        prepare_route = next(
            route for route in self.app.routes
            if getattr(route, "path", None) == "/api/v1/agents/{agent_id}/tasks/{task_code}/prepare-transfer"
        )
        execute_route = next(
            route for route in self.app.routes
            if getattr(route, "path", None) == "/api/v1/ai/transfer/{request_id}/execute"
        )
        request = AgentTransferPrepareRequest(
            document_ids=[document_id], history_id=history["id"]
        )
        manifest = prepare_route.endpoint("document-management", "consolidate-files", request)
        self.assertEqual(self.app.state.openai_adapter.calls, [])
        self.assertEqual(manifest["providerId"], "openai")
        self.assertIn(source_text, manifest["payloadPreview"])
        self.assertNotIn("sk-synthetic-api-key", manifest["payloadPreview"])

        cancelled = execute_route.endpoint(
            manifest["requestId"], AgentTransferConfirmRequest(confirmed=False)
        )
        self.assertTrue(cancelled["cancelled"])
        self.assertEqual(self.app.state.openai_adapter.calls, [])

        manifest = prepare_route.endpoint("document-management", "consolidate-files", request)
        result = execute_route.endpoint(
            manifest["requestId"], AgentTransferConfirmRequest(confirmed=True)
        )
        self.assertEqual(len(self.app.state.openai_adapter.calls), 1)
        self.assertEqual(result["resultText"], "Synthetic AI draft")
        self.assertEqual(
            self.app.state.database.get_agent_task_result(history["id"])["resultText"],
            "Synthetic AI draft",
        )
        export_status, exported_body, export_headers = self.request(
            f"/api/v1/agents/history/{history['id']}/export", self.headers
        )
        self.assertEqual(export_status, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.wordprocessingml.document", export_headers["content-type"])
        self.assertTrue(exported_body.startswith(b"PK"))
        with closing(sqlite3.connect(self.data_directory / "officeai.sqlite3")) as connection, connection:
            saved_request = connection.execute(
                "SELECT result_text FROM agent_task_results"
            ).fetchone()[0]
        self.assertEqual(saved_request, "Synthetic AI draft")
        self.assertNotIn(source_text, saved_request)

    def test_xlsx_preview_includes_saved_values_but_skips_formulas_and_cached_results(self) -> None:
        original = self.office_fixture(
            "xlsx",
            {
                "xl/sharedStrings.xml": (
                    '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    "<si><t>Синтетический доход</t></si></sst>"
                ),
                "xl/worksheets/sheet1.xml": (
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    "<sheetData><row r=\"1\"><c r=\"A1\" t=\"s\"><v>0</v></c>"
                    "<c r=\"A2\"><f>SUM(A1:A1)</f><v>987654</v></c></row></sheetData></worksheet>"
                ),
            },
        )
        status, uploaded, _ = self.upload("Synthetic.xlsx", original)
        self.assertEqual(status, 201)
        document_id = json.loads(uploaded)["document"]["id"]

        result = self.preview("excel-analytics", "summarize-workbook", [document_id])

        preview_text = result["payloadPreview"]
        self.assertIn("Синтетический доход", preview_text)
        self.assertNotIn("SUM(", preview_text)
        self.assertNotIn("987654", preview_text)

    def test_pptx_preview_orders_slides_by_number(self) -> None:
        drawing = "http://schemas.openxmlformats.org/drawingml/2006/main"
        original = self.office_fixture(
            "pptx",
            {
                "ppt/slides/slide2.xml": f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="{drawing}"><a:t>Слайд второй</a:t></p:sld>',
                "ppt/slides/slide1.xml": f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="{drawing}"><a:t>Слайд первый</a:t></p:sld>',
            },
        )
        status, uploaded, _ = self.upload("Synthetic.pptx", original)
        self.assertEqual(status, 201)
        document_id = json.loads(uploaded)["document"]["id"]

        result = self.preview("powerpoint-presentations", "draft-speaker-notes", [document_id])

        preview_text = result["payloadPreview"]
        self.assertLess(preview_text.index("Слайд первый"), preview_text.index("Слайд второй"))

    def test_preview_rejects_xml_entities_malformed_pdf_and_wrong_task_category(self) -> None:
        unsafe_xml = (
            '<!DOCTYPE w:document [<!ENTITY local SYSTEM "file:///not-read">]>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>&local;</w:t></w:r></w:p></w:body></w:document>"
        )
        status, uploaded, _ = self.upload(
            "Unsafe.docx",
            self.office_fixture("docx", {"word/document.xml": unsafe_xml}),
        )
        self.assertEqual(status, 201)
        unsafe_id = json.loads(uploaded)["document"]["id"]
        with self.assertRaises(InvalidDocumentPreview):
            self.preview("document-management", "consolidate-files", [unsafe_id])

        status, uploaded, _ = self.upload("Synthetic.pdf", b"%PDF-1.7\nsynthetic fixture\n%%EOF")
        self.assertEqual(status, 201)
        pdf_id = json.loads(uploaded)["document"]["id"]
        with self.assertRaises(InvalidDocumentPreview):
            self.preview("document-management", "consolidate-files", [pdf_id])
        with self.assertRaises(InvalidDocumentPreview):
            self.preview("excel-analytics", "summarize-workbook", [unsafe_id])

    def test_text_pdf_preview_is_local_and_scanned_pdf_is_rejected_without_ocr(self) -> None:
        source_text = "Synthetic PDF text"
        original = self.pdf_fixture(source_text)
        status, uploaded, _ = self.upload("Synthetic.pdf", original)
        self.assertEqual(status, 201)
        document_id = json.loads(uploaded)["document"]["id"]
        path, _ = self.app.state.document_library.get_download(document_id)
        before = path.read_bytes()

        result = self.preview("document-management", "consolidate-files", [document_id])

        self.assertIn(source_text, result["payloadPreview"])
        self.assertIn("Страница 1", result["payloadPreview"])
        self.assertEqual(before, path.read_bytes())

        status, uploaded, _ = self.upload("Scanned.pdf", self.pdf_fixture(None))
        self.assertEqual(status, 201)
        scanned_id = json.loads(uploaded)["document"]["id"]
        with self.assertRaisesRegex(InvalidDocumentPreview, "OCR отключён"):
            self.preview("document-management", "consolidate-files", [scanned_id])

    def test_backup_round_trip_restores_database_and_original_documents(self) -> None:
        original = b"%PDF-1.7\nsynthetic backup fixture\n%%EOF"
        status, body, _ = self.upload("Архив Құжат.pdf", original)
        self.assertEqual(status, 201)
        history = self.app.state.database.record_agent_preview(
            "document-management", "check-completeness", 1
        )
        self.app.state.database.save_agent_task_result(
            history["id"], "openai", "gpt-4.1-mini", "Synthetic saved result"
        )
        service: BackupService = self.app.state.backup_service
        backup = service.create_backup()
        archive_path = self.data_directory / "backups" / f"{backup['id']}.zip"
        self.assertTrue(archive_path.is_file())

        self.app.state.database.update_setting("theme", "dark")
        stored_file = next((self.data_directory / "documents").glob("*.bin"))
        stored_file.write_bytes(b"changed local contents")

        async def chunks():
            yield archive_path.read_bytes()

        uploaded_archive = asyncio.run(service.receive_restore_upload(chunks()))
        service.restore_archive(uploaded_archive)
        self.assertEqual(self.app.state.database.get_settings()["theme"], "light")
        restored = next((self.data_directory / "documents").glob("*.bin"))
        self.assertEqual(restored.read_bytes(), original)
        self.assertEqual(self.app.state.document_library.query()[1], 1)
        self.assertEqual(len(self.app.state.database.list_agent_task_history()), 1)
        self.assertEqual(
            self.app.state.database.get_agent_task_result(history["id"])["resultText"],
            "Synthetic saved result",
        )
        with closing(sqlite3.connect(self.data_directory / "officeai.sqlite3")) as connection, connection:
            operation_codes = {row[0] for row in connection.execute("SELECT operation_code FROM operation_log")}
        self.assertIn("backup_restored", operation_codes)

    def test_invalid_backup_is_rejected_without_changing_live_database(self) -> None:
        service: BackupService = self.app.state.backup_service
        original_setting = self.app.state.database.get_settings()["theme"]
        (self.data_directory / "backups").mkdir(exist_ok=True)
        malicious_archive = self.data_directory / "backups" / f".restore-upload-{uuid4().hex}.zip"
        manifest = {
            "format": "office-ai-backup",
            "schemaVersion": 2,
            "files": [{"path": "../escape", "sizeBytes": 0, "sha256": "0" * 64}],
        }
        with ZipFile(malicious_archive, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("../escape", b"")
        with self.assertRaises(InvalidBackup):
            service.restore_archive(malicious_archive)
        self.assertFalse((self.data_directory.parent / "escape").exists())
        self.assertEqual(self.app.state.database.get_settings()["theme"], original_setting)

    def test_restore_api_requires_explicit_confirmation_before_reading_archive(self) -> None:
        headers = {**self.headers, "content-type": "application/octet-stream"}
        status, body, _ = self.request("/api/v1/restore", headers, method="POST", body=b"not-an-archive")
        self.assertEqual(status, 400)
        self.assertIn("подтверждение", body.decode().lower())
        backup_directory = self.data_directory / "backups"
        self.assertFalse(backup_directory.exists())

    def test_backup_api_creates_a_generated_local_archive(self) -> None:
        headers = {**self.headers, "content-type": "application/json"}
        status, body, _ = self.request("/api/v1/backups", headers, method="POST", body=b"{}")
        self.assertEqual(status, 201)
        backup = json.loads(body)
        self.assertRegex(backup["id"], r"^[0-9a-f]{32}$")
        self.assertTrue((self.data_directory / "backups" / f"{backup['id']}.zip").is_file())
        _, journal, _ = self.request("/api/v1/operations", self.headers)
        self.assertIn("backup_created", journal.decode())

    def test_desktop_bridge_saves_backup_to_user_selected_path(self) -> None:
        service: BackupService = self.app.state.backup_service
        backup = service.create_backup()
        source = self.data_directory / "backups" / f"{backup['id']}.zip"
        destination = self.data_directory / "user-selected-copy.zip"
        fake_window = SimpleNamespace(create_file_dialog=lambda *args, **kwargs: [str(destination)])
        fake_webview = SimpleNamespace(SAVE_DIALOG=2, windows=[fake_window])
        bridge = DesktopBridge(RuntimeConfig("http://127.0.0.1/api/v1", "synthetic-token"), service)
        with patch.dict(sys.modules, {"webview": fake_webview}):
            self.assertTrue(bridge.save_backup(backup["id"]))
        self.assertEqual(destination.read_bytes(), source.read_bytes())

if __name__ == "__main__":
    unittest.main()
