"""SQLite database, schema migrations, preferences, and operation journal."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from contextlib import contextmanager
from uuid import uuid4

from office_ai.domain.settings import DEFAULT_SETTINGS, SettingValue, validate_setting

SCHEMA_VERSION = 1
MAX_OPERATION_LIMIT = 100
_ALLOWED_OPERATION_CODES = {"app_started", "setting_updated"}
_ALLOWED_MESSAGE_CODES = {"app_started", "setting_saved"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class LocalDatabase:
    """Small connection-per-operation SQLite adapter for one local user."""

    def __init__(self, data_directory: Path) -> None:
        self.data_directory = data_directory
        self.database_path = data_directory / "officeai.sqlite3"

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.data_directory.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create the first schema or apply any known pending migrations."""
        self.data_directory.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"База версии {version} новее поддерживаемой версии {SCHEMA_VERSION}."
                )
            if version < 1:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    CREATE TABLE schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE app_settings (
                        setting_key TEXT PRIMARY KEY,
                        value_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE operation_log (
                        id TEXT PRIMARY KEY,
                        occurred_at TEXT NOT NULL,
                        operation_code TEXT NOT NULL,
                        outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failure')),
                        entity_type TEXT,
                        entity_id TEXT,
                        message_code TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX operation_log_occurred_at_idx ON operation_log(occurred_at DESC)"
                )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (1, _utc_now()),
                )
                connection.execute("PRAGMA user_version = 1")
                for key, value in DEFAULT_SETTINGS.items():
                    connection.execute(
                        "INSERT INTO app_settings(setting_key, value_json, updated_at) VALUES (?, ?, ?)",
                        (key, json.dumps(value), _utc_now()),
                    )

    def get_settings(self) -> dict[str, SettingValue]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT setting_key, value_json FROM app_settings ORDER BY setting_key"
            ).fetchall()
        settings: dict[str, SettingValue] = dict(DEFAULT_SETTINGS)
        for row in rows:
            try:
                settings[row["setting_key"]] = validate_setting(
                    row["setting_key"], json.loads(row["value_json"])
                )
            except (json.JSONDecodeError, ValueError):
                # Corrupt or unknown values are ignored and replaced by defaults
                # on the next explicit update; they are never reflected to UI.
                continue
        return settings

    def update_setting(self, key: str, value: object) -> dict[str, SettingValue]:
        safe_value = validate_setting(key, value)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO app_settings(setting_key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(safe_value), _utc_now()),
            )
            self._insert_operation(
                connection,
                "setting_updated",
                "success",
                "setting",
                key,
                "setting_saved",
            )
        return self.get_settings()

    def record_operation(
        self,
        operation_code: str,
        *,
        outcome: str = "success",
        entity_type: str | None = None,
        entity_id: str | None = None,
        message_code: str,
    ) -> None:
        """Record fixed codes/IDs only; this API intentionally accepts no text payload."""
        with self._connect() as connection:
            self._insert_operation(
                connection,
                operation_code,
                outcome,
                entity_type,
                entity_id,
                message_code,
            )

    @staticmethod
    def _insert_operation(
        connection: sqlite3.Connection,
        operation_code: str,
        outcome: str,
        entity_type: str | None,
        entity_id: str | None,
        message_code: str,
    ) -> None:
        if outcome not in {"success", "failure"}:
            raise ValueError("Unsupported operation outcome")
        if operation_code not in _ALLOWED_OPERATION_CODES or message_code not in _ALLOWED_MESSAGE_CODES:
            raise ValueError("Unsupported operation or message code")
        if entity_type not in {None, "setting"}:
            raise ValueError("Unsupported operation entity type")
        if entity_id is not None and entity_id not in DEFAULT_SETTINGS:
            raise ValueError("Unsupported operation entity ID")
        connection.execute(
            """
            INSERT INTO operation_log
                (id, occurred_at, operation_code, outcome, entity_type, entity_id, message_code)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (str(uuid4()), _utc_now(), operation_code, outcome, entity_type, entity_id, message_code),
        )

    def list_operations(self, limit: int = 50) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), MAX_OPERATION_LIMIT))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, occurred_at, operation_code, outcome, entity_type, entity_id, message_code
                FROM operation_log
                ORDER BY occurred_at DESC, id DESC
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "occurredAt": row["occurred_at"],
                "operationCode": row["operation_code"],
                "outcome": row["outcome"],
                "entityType": row["entity_type"],
                "entityId": row["entity_id"],
                "messageCode": row["message_code"],
            }
            for row in rows
        ]
