"""One-use transfer authorization tests with synthetic text only."""

import unittest
from datetime import datetime, timedelta, timezone

from office_ai.application.agent_consent import AgentTransferConsent, ConsentRequired
from office_ai.domain.agents.consent import InvalidTransferDisclosure, TransferItem


class AgentTransferConsentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = AgentTransferConsent()
        self.payload = b'{"model":"gpt-4.1-mini","input":"synthetic"}'
        self.preview = self.payload.decode("utf-8")
        self.item = TransferItem("synthetic-document-id", "Test.docx", ("document_text",))

    def prepare(self, now: datetime | None = None):
        return self.service.prepare(
            provider_id="openai",
            agent_id="document-management",
            task_code="consolidate-files",
            purpose="Сведение только выбранных пользователем сведений в отдельный черновик.",
            items=(self.item,),
            payload=self.payload,
            payload_preview=self.preview,
            now=now,
        )

    def test_single_approval_authorizes_the_same_payload_once(self) -> None:
        manifest = self.prepare()
        receipt = self.service.confirm(manifest.request_id, user_confirmed=True)
        approved = self.service.consume(
            receipt.receipt_id, provider_id="openai", payload=self.payload
        )
        self.assertEqual(approved, self.payload)
        with self.assertRaises(ConsentRequired):
            self.service.consume(receipt.receipt_id, provider_id="openai", payload=self.payload)

    def test_cancel_expiry_and_denial_never_issue_a_receipt(self) -> None:
        manifest = self.prepare()
        self.service.cancel(manifest.request_id)
        with self.assertRaises(ConsentRequired):
            self.service.confirm(manifest.request_id, user_confirmed=True)

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        expired = self.prepare(start)
        with self.assertRaises(ConsentRequired):
            self.service.confirm(
                expired.request_id, user_confirmed=True, now=start + timedelta(minutes=10)
            )

        denied = self.prepare(start)
        with self.assertRaises(ConsentRequired):
            self.service.confirm(denied.request_id, user_confirmed=False, now=start)

    def test_changed_payload_or_provider_consumes_the_receipt(self) -> None:
        manifest = self.prepare()
        receipt = self.service.confirm(manifest.request_id, user_confirmed=True)
        with self.assertRaises(ConsentRequired):
            self.service.consume(receipt.receipt_id, provider_id="openai", payload=b"changed")
        with self.assertRaises(ConsentRequired):
            self.service.consume(receipt.receipt_id, provider_id="openai", payload=self.payload)

        second = self.service.confirm(self.prepare().request_id, user_confirmed=True)
        with self.assertRaises(ConsentRequired):
            self.service.consume(second.receipt_id, provider_id="other", payload=self.payload)

    def test_unapproved_provider_purpose_category_and_preview_are_rejected(self) -> None:
        args = {
            "provider_id": "openai",
            "agent_id": "document-management",
            "task_code": "consolidate-files",
            "purpose": "Сведение только выбранных пользователем сведений в отдельный черновик.",
            "items": (self.item,),
            "payload": self.payload,
            "payload_preview": self.preview,
        }
        for updates in (
            {"provider_id": "other"},
            {"purpose": "произвольная цель"},
            {"items": (TransferItem("book", "Sheet.xlsx", ("spreadsheet_values",)),)},
            {"payload_preview": "не тот запрос"},
        ):
            with self.subTest(updates=updates), self.assertRaises(InvalidTransferDisclosure):
                self.service.prepare(**{**args, **updates})


if __name__ == "__main__":
    unittest.main()
