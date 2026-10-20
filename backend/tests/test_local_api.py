"""Focused checks for the scaffold's local API boundary."""

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from office_ai.api.app import create_app
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

    def request(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        method: str = "GET",
        body: bytes = b"",
    ) -> tuple[int, bytes, dict[str, str]]:
        request_headers = headers or self.headers
        raw_headers = [(key.lower().encode(), value.encode()) for key, value in request_headers.items()]
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": raw_headers,
            "client": ("127.0.0.1", 45678),
            "server": ("127.0.0.1", 43127),
        }
        messages: list[dict] = []
        received = False

        async def receive() -> dict:
            nonlocal received
            if received:
                return {"type": "http.disconnect"}
            received = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message: dict) -> None:
            messages.append(message)

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
        with sqlite3.connect(database_path) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(
                connection.execute("SELECT version FROM schema_migrations").fetchone()[0],
                1,
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


if __name__ == "__main__":
    unittest.main()
