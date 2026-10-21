"""In-memory, per-request consent gate for future external AI adapters."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final

from office_ai.domain.agents.consent import (
    MAX_TRANSFER_BYTES,
    InvalidTransferDisclosure,
    TransferItem,
    TransferManifest,
    TransferReceipt,
)
from office_ai.domain.agents.task_catalog import get_agent_task

REQUEST_LIFETIME: Final = timedelta(minutes=10)
RECEIPT_LIFETIME: Final = timedelta(minutes=5)


class ConsentRequired(PermissionError):
    """Raised when no current approval exists for an exact outbound payload."""


@dataclass(frozen=True)
class _PendingTransfer:
    manifest: TransferManifest


@dataclass(frozen=True)
class _ApprovedTransfer:
    receipt: TransferReceipt


class AgentTransferConsent:
    """Prepare, approve and consume ephemeral approval for an exact payload.

    The service intentionally stores neither payload bytes nor consent in the
    database. Restarting the app invalidates every request and receipt. Calling
    this service never performs network I/O.
    """

    def __init__(self, allowed_providers: frozenset[str] = frozenset({"openai"})) -> None:
        self._allowed_providers = allowed_providers
        self._pending: dict[str, _PendingTransfer] = {}
        self._approved: dict[str, _ApprovedTransfer] = {}

    def prepare(
        self,
        *,
        provider_id: str,
        agent_id: str,
        task_code: str,
        purpose: str,
        items: tuple[TransferItem, ...],
        payload: bytes,
        payload_preview: str,
        now: datetime | None = None,
    ) -> TransferManifest:
        """Create a disclosure for user review without sending the payload."""
        issued = _utc(now)
        if provider_id not in self._allowed_providers:
            raise InvalidTransferDisclosure("Поставщик ИИ не разрешён настройками приложения.")
        task = get_agent_task(agent_id, task_code)
        if task is None:
            raise InvalidTransferDisclosure("Для агента не разрешён такой тип задачи.")
        if purpose != task.purpose:
            raise InvalidTransferDisclosure("Цель передачи не совпадает с утверждённым описанием задачи.")
        if not items or len(items) > 100 or len({item.resource_id for item in items}) != len(items):
            raise InvalidTransferDisclosure("Выберите корректный набор данных для просмотра.")
        if any(not set(item.categories).issubset(task.allowed_categories) for item in items):
            raise InvalidTransferDisclosure("Задача не разрешает передачу одной из указанных категорий данных.")
        if not isinstance(payload, bytes) or not payload or len(payload) > MAX_TRANSFER_BYTES:
            raise InvalidTransferDisclosure("Размер подготовленных данных не допускается к передаче.")
        try:
            exact_preview = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise InvalidTransferDisclosure("Перед передачей можно подтвердить только отображаемый текстовый запрос.") from error
        if (
            not payload_preview
            or len(payload_preview.encode("utf-8")) > MAX_TRANSFER_BYTES
            or payload_preview != exact_preview
        ):
            raise InvalidTransferDisclosure("Не удалось показать полный объём данных перед передачей.")

        manifest = TransferManifest(
            request_id=secrets.token_urlsafe(24),
            provider_id=provider_id,
            agent_id=agent_id,
            task_code=task_code,
            purpose=purpose,
            items=items,
            payload_preview=payload_preview,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            payload_size_bytes=len(payload),
            created_at=issued,
            expires_at=issued + REQUEST_LIFETIME,
        )
        self._pending[manifest.request_id] = _PendingTransfer(manifest)
        return manifest

    def confirm(self, request_id: str, *, user_confirmed: bool, now: datetime | None = None) -> TransferReceipt:
        """Record a single explicit decision for one disclosure."""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            raise ConsentRequired("Запрос передачи данных отсутствует или уже закрыт.")
        manifest = pending.manifest
        moment = _utc(now)
        if moment >= manifest.expires_at:
            raise ConsentRequired("Время подтверждения передачи истекло. Подготовьте запрос заново.")
        if not user_confirmed:
            raise ConsentRequired("Пользователь не подтвердил передачу данных.")

        receipt = TransferReceipt(
            receipt_id=secrets.token_urlsafe(32),
            request_id=manifest.request_id,
            provider_id=manifest.provider_id,
            payload_sha256=manifest.payload_sha256,
            payload_size_bytes=manifest.payload_size_bytes,
            expires_at=min(manifest.expires_at, moment + RECEIPT_LIFETIME),
        )
        self._approved[receipt.receipt_id] = _ApprovedTransfer(receipt)
        return receipt

    def consume(self, receipt_id: str, *, provider_id: str, payload: bytes, now: datetime | None = None) -> bytes:
        """Consume approval exactly once and return only the reviewed bytes.

        A failed attempt also consumes the receipt, so a modified payload cannot
        be retried under approval for the original preview.
        """
        approved = self._approved.pop(receipt_id, None)
        if approved is None:
            raise ConsentRequired("Подтверждение отсутствует, истекло или уже использовано.")
        receipt = approved.receipt
        moment = _utc(now)
        if moment >= receipt.expires_at:
            raise ConsentRequired("Подтверждение передачи данных истекло.")
        if provider_id != receipt.provider_id:
            raise ConsentRequired("Поставщик отличается от показанного перед подтверждением.")
        if not isinstance(payload, bytes) or len(payload) != receipt.payload_size_bytes:
            raise ConsentRequired("Состав или размер данных изменился после подтверждения.")
        actual_digest = hashlib.sha256(payload).hexdigest()
        if not hmac.compare_digest(actual_digest, receipt.payload_sha256):
            raise ConsentRequired("Состав данных изменился после подтверждения.")
        return payload

    def cancel(self, request_id: str) -> None:
        """Discard a disclosure when the user closes the review screen."""
        self._pending.pop(request_id, None)


def _utc(value: datetime | None) -> datetime:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("Для контроля срока действия требуется часовой пояс.")
    return moment.astimezone(timezone.utc)
