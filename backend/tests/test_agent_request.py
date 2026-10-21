"""Local disclosure-flow tests; all provider calls are synthetic mocks."""

import json
import tempfile
import unittest
from pathlib import Path

from office_ai.application.agent_consent import AgentTransferConsent, ConsentRequired
from office_ai.application.agent_request import AgentRequestError, AgentRequestService, MODEL_ID
from office_ai.infrastructure.database import LocalDatabase


class FakePreview:
    def create(self, **_kwargs: object) -> dict[str, object]:
        return {
            "taskTitle": "Собрать сведения из файлов",
            "purpose": "Сведение только выбранных пользователем сведений в отдельный черновик.",
            "payloadPreview": "Задача: собрать сведения\nИсточник 1:\nSynthetic source text",
            "sources": [{
                "id": "synthetic-document-id",
                "name": "Synthetic.docx",
                "category": "document_text",
                "text": "Synthetic source text",
            }],
        }


class FakeCredentials:
    def __init__(self) -> None:
        self.api_key: str | None = "sk-synthetic-key-for-tests-only"

    def save_api_key(self, api_key: str) -> None:
        self.api_key = api_key

    def read_api_key(self) -> str | None:
        return self.api_key

    def delete_api_key(self) -> None:
        self.api_key = None


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str]] = []

    def generate(self, payload: bytes, api_key: str) -> str:
        self.calls.append((payload, api_key))
        return "Synthetic generated draft"


class AgentRequestServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = LocalDatabase(Path(self.temp.name))
        self.database.initialize()
        self.history = self.database.record_agent_preview("document-management", "consolidate-files", 1)
        self.credentials = FakeCredentials()
        self.provider = FakeProvider()
        self.service = AgentRequestService(
            preview=FakePreview(),
            consent=AgentTransferConsent(),
            credentials=self.credentials,
            provider=self.provider,
            database=self.database,
        )

    def prepare(self) -> object:
        return self.service.prepare(
            agent_id="document-management",
            task_code="consolidate-files",
            document_ids=["synthetic-document-id"],
            instruction="",
            history_id=self.history["id"],
        )

    def test_prepare_discloses_exact_request_without_network_or_secret(self) -> None:
        manifest = self.prepare()

        self.assertEqual(self.provider.calls, [])
        self.assertEqual(manifest.provider_id, "openai")
        self.assertEqual(manifest.items[0].display_name, "Synthetic.docx")
        self.assertNotIn("sk-synthetic-key", manifest.payload_preview)
        payload = json.loads(manifest.payload_preview)
        self.assertEqual(payload["model"], MODEL_ID)
        self.assertEqual(payload["store"], False)
        self.assertIn("Synthetic source text", payload["input"])
        self.assertIn("заголовком и разделами", payload["instructions"])
        self.assertIn("недоверенными данными", payload["instructions"])

    def test_cancel_never_calls_provider_and_confirmed_send_persists_result(self) -> None:
        cancelled = self.prepare()
        self.assertIsNone(self.service.execute(cancelled.request_id, user_confirmed=False))
        self.assertEqual(self.provider.calls, [])

        manifest = self.prepare()
        result = self.service.execute(manifest.request_id, user_confirmed=True)

        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.provider.calls[0][1], "sk-synthetic-key-for-tests-only")
        self.assertEqual(result["resultText"], "Synthetic generated draft")
        saved = self.database.get_agent_task_result(self.history["id"])
        self.assertEqual(saved["resultText"], "Synthetic generated draft")
        self.assertTrue(self.database.list_agent_task_history()[0]["hasResult"])

    def test_old_history_key_or_replayed_request_does_not_call_provider(self) -> None:
        self.credentials.delete_api_key()
        with self.assertRaisesRegex(AgentRequestError, "ключ OpenAI"):
            self.prepare()
        self.assertEqual(self.provider.calls, [])

        self.credentials.api_key = "sk-synthetic-key-for-tests-only"
        manifest = self.prepare()
        self.service.execute(manifest.request_id, user_confirmed=True)
        with self.assertRaises(ConsentRequired):
            self.service.execute(manifest.request_id, user_confirmed=True)
        self.assertEqual(len(self.provider.calls), 1)


if __name__ == "__main__":
    unittest.main()
