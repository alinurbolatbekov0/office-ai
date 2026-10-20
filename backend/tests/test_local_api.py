"""Focused checks for the scaffold's local API boundary."""

import asyncio
import json
import unittest

from office_ai.api.app import create_app


class LocalApiSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app(
            expected_host="127.0.0.1:43127",
            expected_origin="http://127.0.0.1:5173",
            session_token="test-session-token",
        )
        self.app = app
        self.headers = {
            "host": "127.0.0.1:43127",
            "origin": "http://127.0.0.1:5173",
            "x-officeai-token": "test-session-token",
        }

    def request(self, path: str, headers: dict[str, str], method: str = "GET") -> tuple[int, bytes, dict[str, str]]:
        raw_headers = [(key.lower().encode(), value.encode()) for key, value in headers.items()]
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
            return {"type": "http.request", "body": b"", "more_body": False}

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
            "access-control-request-method": "GET",
            "access-control-request-headers": "x-officeai-token",
        }
        status, _, response_headers = self.request("/api/v1/health", headers, method="OPTIONS")
        self.assertEqual(status, 204)
        self.assertEqual(response_headers["access-control-allow-origin"], "http://127.0.0.1:5173")

        unsafe_headers = {**headers, "access-control-request-headers": "authorization"}
        self.assertEqual(self.request("/api/v1/health", unsafe_headers, method="OPTIONS")[0], 403)


if __name__ == "__main__":
    unittest.main()
