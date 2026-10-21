"""Disclosure records used to gate future, user-approved AI transfers.

This module has no network or persistence responsibilities. It describes the
exact outbound payload and the data the user must see before approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

MAX_TRANSFER_BYTES: Final = 20 * 1024 * 1024
ALLOWED_DATA_CATEGORIES: Final = frozenset(
    {
        "document_text",
        "spreadsheet_values",
        "presentation_content",
        "user_instruction",
        "document_metadata",
    }
)


class InvalidTransferDisclosure(ValueError):
    """Raised when a proposed outbound transfer cannot be disclosed safely."""


@dataclass(frozen=True)
class TransferItem:
    """A user-visible reference to one selected source of outbound data."""

    resource_id: str
    display_name: str
    categories: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.categories, tuple):
            object.__setattr__(self, "categories", tuple(self.categories))
        if not self.resource_id or len(self.resource_id) > 128 or any(c in self.resource_id for c in "/\\:"):
            raise InvalidTransferDisclosure("Для передачи указан некорректный внутренний ID данных.")
        if not self.display_name or len(self.display_name) > 255 or any(c in self.display_name for c in "\r\n"):
            raise InvalidTransferDisclosure("Не удалось безопасно показать имя выбранных данных.")
        if (
            not self.categories
            or len(self.categories) != len(set(self.categories))
            or not set(self.categories).issubset(ALLOWED_DATA_CATEGORIES)
        ):
            raise InvalidTransferDisclosure("В передаче указана неизвестная категория данных.")


@dataclass(frozen=True)
class TransferManifest:
    """The disclosure shown to a user before any external request is allowed."""

    request_id: str
    provider_id: str
    agent_id: str
    task_code: str
    purpose: str
    items: tuple[TransferItem, ...]
    payload_preview: str = field(repr=False)
    payload_sha256: str = field(repr=False)
    payload_size_bytes: int
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class TransferReceipt:
    """Opaque, short-lived, one-use approval for one exact transfer request."""

    receipt_id: str = field(repr=False)
    request_id: str
    provider_id: str
    payload_sha256: str = field(repr=False)
    payload_size_bytes: int
    expires_at: datetime
