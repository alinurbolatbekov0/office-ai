"""SQLite database, schema migrations, preferences, and operation journal."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

from office_ai.domain.settings import DEFAULT_SETTINGS, SettingValue, validate_setting

SCHEMA_VERSION = 4
MAX_OPERATION_LIMIT = 100
_ALLOWED_OPERATION_CODES = {
    "app_started",
    "setting_updated",
    "document_uploaded",
    "document_duplicate_detected",
    "document_upload_rejected",
    "backup_created",
    "backup_restored",
    "backup_restore_rejected",
    "agent_preview_created",
    "agent_ai_task_completed",
}
_ALLOWED_MESSAGE_CODES = {
    "app_started",
    "setting_saved",
    "document_uploaded",
    "document_duplicate_detected",
    "document_upload_rejected",
    "backup_created",
    "backup_restored",
    "backup_restore_rejected",
    "agent_preview_created",
    "agent_ai_task_completed",
}


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

            if version < 2:
                if version >= 1:
                    connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    CREATE TABLE stored_files (
                        id TEXT PRIMARY KEY,
                        sha256 TEXT NOT NULL UNIQUE,
                        storage_key TEXT NOT NULL UNIQUE,
                        size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
                        detected_type TEXT NOT NULL CHECK (detected_type IN
                            ('DOCX', 'XLSX', 'PPTX', 'PDF', 'JPEG', 'PNG')),
                        created_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX stored_files_sha256_idx ON stored_files(sha256)"
                )
                connection.execute(
                    """
                    CREATE TABLE documents (
                        id TEXT PRIMARY KEY,
                        stored_file_id TEXT NOT NULL REFERENCES stored_files(id),
                        original_name TEXT NOT NULL,
                        extension TEXT NOT NULL CHECK (extension IN
                            ('docx', 'xlsx', 'pptx', 'pdf', 'jpg', 'jpeg', 'png')),
                        imported_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX documents_imported_at_idx ON documents(imported_at DESC)"
                )
                connection.execute(
                    "CREATE INDEX documents_stored_file_idx ON documents(stored_file_id)"
                )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (2, _utc_now()),
                )
                connection.execute("PRAGMA user_version = 2")

            if version < 3:
                if version >= 2:
                    connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    CREATE TABLE agent_task_history (
                        id TEXT PRIMARY KEY,
                        agent_id TEXT NOT NULL CHECK (agent_id IN
                            ('document-management', 'business-correspondence',
                             'excel-analytics', 'powerpoint-presentations')),
                        task_code TEXT NOT NULL,
                        outcome TEXT NOT NULL CHECK (outcome IN ('preview_ready')),
                        source_count INTEGER NOT NULL CHECK (source_count BETWEEN 1 AND 5),
                        created_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX agent_task_history_created_idx ON agent_task_history(created_at DESC)"
                )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (3, _utc_now()),
                )
                connection.execute("PRAGMA user_version = 3")

            if version < 4:
                if version >= 3:
                    connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    CREATE TABLE agent_task_results (
                        id TEXT PRIMARY KEY,
                        history_id TEXT NOT NULL UNIQUE
                            REFERENCES agent_task_history(id) ON DELETE CASCADE,
                        provider_id TEXT NOT NULL CHECK (provider_id = 'openai'),
                        model_id TEXT NOT NULL CHECK (length(model_id) BETWEEN 1 AND 100),
                        result_text TEXT NOT NULL CHECK (length(result_text) BETWEEN 1 AND 1000000),
                        created_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX agent_task_results_created_idx ON agent_task_results(created_at DESC)"
                )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (4, _utc_now()),
                )
                connection.execute("PRAGMA user_version = 4")

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

    def register_document(
        self,
        *,
        document_id: str,
        stored_file_id: str,
        storage_key: str,
        sha256: str,
        size_bytes: int,
        detected_type: str,
        original_name: str,
        extension: str,
        allow_duplicate: bool,
    ) -> dict[str, Any]:
        """Register verified bytes and metadata, deduplicating by SHA-256."""
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id FROM stored_files WHERE sha256 = ?", (sha256,)
            ).fetchone()
            duplicate = existing is not None
            if duplicate and not allow_duplicate:
                self._insert_operation(
                    connection,
                    "document_duplicate_detected",
                    "success",
                    None,
                    None,
                    "document_duplicate_detected",
                )
                return {
                    "duplicate": True,
                    "storedFileId": existing["id"],
                    "document": None,
                }
            if duplicate:
                effective_stored_file_id = existing["id"]
            else:
                effective_stored_file_id = stored_file_id
                connection.execute(
                    """
                    INSERT INTO stored_files
                        (id, sha256, storage_key, size_bytes, detected_type, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (stored_file_id, sha256, storage_key, size_bytes, detected_type, _utc_now()),
                )

            imported_at = _utc_now()
            connection.execute(
                """
                INSERT INTO documents(id, stored_file_id, original_name, extension, imported_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (document_id, effective_stored_file_id, original_name, extension, imported_at),
            )
            self._insert_operation(
                connection,
                "document_uploaded",
                "success",
                "document",
                document_id,
                "document_uploaded",
            )
            row = connection.execute(
                """
                SELECT d.id, d.original_name, d.extension, d.imported_at,
                       f.size_bytes, f.detected_type, f.sha256
                FROM documents d JOIN stored_files f ON f.id = d.stored_file_id
                WHERE d.id = ?
                """,
                (document_id,),
            ).fetchone()
        return {"duplicate": duplicate, "storedFileId": effective_stored_file_id, "document": self._document_row(row)}

    def list_duplicate_documents(self, sha256: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT d.id, d.original_name, d.extension, d.imported_at,
                       f.size_bytes, f.detected_type, f.sha256
                FROM documents d JOIN stored_files f ON f.id = d.stored_file_id
                WHERE f.sha256 = ?
                ORDER BY d.imported_at DESC, d.id
                """,
                (sha256,),
            ).fetchall()
        return [self._document_row(row) for row in rows]

    def list_documents(
        self,
        *,
        search: str = "",
        detected_type: str | None = None,
        imported_from: str | None = None,
        imported_to: str | None = None,
        sort_by: str = "imported_at",
        sort_order: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        sort_columns = {
            "name": "office_casefold(d.original_name)",
            "imported_at": "d.imported_at",
            "size_bytes": "f.size_bytes",
            "type": "f.detected_type",
        }
        if sort_by not in sort_columns or sort_order not in {"asc", "desc"}:
            raise ValueError("Unsupported document sort")
        clauses: list[str] = []
        parameters: list[object] = []
        if search:
            escaped_search = search.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append("office_casefold(d.original_name) LIKE office_casefold(?) ESCAPE '\\'")
            parameters.append(f"%{escaped_search}%")
        if detected_type:
            clauses.append("f.detected_type = ?")
            parameters.append(detected_type)
        if imported_from:
            clauses.append("date(d.imported_at) >= date(?)")
            parameters.append(imported_from)
        if imported_to:
            clauses.append("date(d.imported_at) <= date(?)")
            parameters.append(imported_to)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        direction = sort_order.upper()
        with self._connect() as connection:
            connection.create_function("office_casefold", 1, lambda value: str(value).casefold())
            total = connection.execute(
                f"SELECT COUNT(*) FROM documents d JOIN stored_files f ON f.id = d.stored_file_id {where_sql}",
                parameters,
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT d.id, d.original_name, d.extension, d.imported_at,
                       f.size_bytes, f.detected_type, f.sha256
                FROM documents d JOIN stored_files f ON f.id = d.stored_file_id
                {where_sql}
                ORDER BY {sort_columns[sort_by]} {direction}, d.id
                LIMIT ? OFFSET ?
                """,
                [*parameters, max(1, min(int(limit), 200)), max(0, int(offset))],
            ).fetchall()
        return [self._document_row(row) for row in rows], int(total)

    def get_document_download(self, document_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT d.id, d.original_name, d.extension, d.imported_at,
                       f.id AS storage_file_id, f.size_bytes, f.detected_type,
                       f.sha256, f.storage_key
                FROM documents d JOIN stored_files f ON f.id = d.stored_file_id
                WHERE d.id = ?
                """,
                (document_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            **self._document_row(row),
            "storageKey": row["storage_key"],
            "storageFileId": row["storage_file_id"],
        }

    @staticmethod
    def _document_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["original_name"],
            "extension": row["extension"],
            "importedAt": row["imported_at"],
            "sizeBytes": row["size_bytes"],
            "type": row["detected_type"],
            "sha256": row["sha256"],
        }

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
        if entity_type not in {None, "setting", "document"}:
            raise ValueError("Unsupported operation entity type")
        if entity_type == "setting" and entity_id not in DEFAULT_SETTINGS:
            raise ValueError("Unsupported operation entity ID")
        if entity_type == "document":
            try:
                UUID(entity_id or "")
            except ValueError as error:
                raise ValueError("Unsupported document ID") from error
        if entity_type is None and entity_id is not None:
            raise ValueError("An entity ID requires an entity type")
        connection.execute(
            """
            INSERT INTO operation_log
                (id, occurred_at, operation_code, outcome, entity_type, entity_id, message_code)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (str(uuid4()), _utc_now(), operation_code, outcome, entity_type, entity_id, message_code),
        )

    def record_agent_preview(self, agent_id: str, task_code: str, source_count: int) -> dict[str, Any]:
        """Persist minimal task history; never persist the prompt or document content."""
        allowed_agents = {
            "document-management", "business-correspondence",
            "excel-analytics", "powerpoint-presentations",
        }
        if agent_id not in allowed_agents or not task_code or len(task_code) > 80:
            raise ValueError("Unsupported agent task")
        if not 1 <= source_count <= 5:
            raise ValueError("Unsupported source count")
        run_id = str(uuid4())
        created_at = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO agent_task_history
                   (id, agent_id, task_code, outcome, source_count, created_at)
                   VALUES (?, ?, ?, 'preview_ready', ?, ?)""",
                (run_id, agent_id, task_code, source_count, created_at),
            )
            self._insert_operation(
                connection, "agent_preview_created", "success", None, None, "agent_preview_created"
            )
        return {"id": run_id, "agentId": agent_id, "taskCode": task_code,
                "outcome": "preview_ready", "sourceCount": source_count, "createdAt": created_at}

    def list_agent_task_history(self, limit: int = 50) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 100))
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT h.id, h.agent_id, h.task_code, h.outcome, h.source_count, h.created_at,
                          EXISTS(SELECT 1 FROM agent_task_results r WHERE r.history_id = h.id) AS has_result
                   FROM agent_task_history h ORDER BY h.created_at DESC, h.id DESC LIMIT ?""",
                (bounded_limit,),
            ).fetchall()
        return [{"id": row["id"], "agentId": row["agent_id"], "taskCode": row["task_code"],
                 "outcome": row["outcome"], "sourceCount": row["source_count"],
                 "hasResult": bool(row["has_result"]), "createdAt": row["created_at"]}
                for row in rows]

    def get_agent_task_history_entry(self, history_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT h.id, h.agent_id, h.task_code, h.outcome, h.source_count, h.created_at,
                          EXISTS(SELECT 1 FROM agent_task_results r WHERE r.history_id = h.id) AS has_result
                   FROM agent_task_history h WHERE h.id = ?""",
                (history_id,),
            ).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "agentId": row["agent_id"], "taskCode": row["task_code"],
                "outcome": row["outcome"], "sourceCount": row["source_count"],
                "hasResult": bool(row["has_result"]), "createdAt": row["created_at"]}

    def save_agent_task_result(
        self, history_id: str, provider_id: str, model_id: str, result_text: str
    ) -> dict[str, Any]:
        if provider_id != "openai" or not model_id or len(model_id) > 100:
            raise ValueError("Unsupported result provider or model")
        if not isinstance(result_text, str) or not result_text.strip() or len(result_text) > 1_000_000:
            raise ValueError("Unsupported result text")
        result_id = str(uuid4())
        created_at = _utc_now()
        with self._connect() as connection:
            history = connection.execute(
                "SELECT id FROM agent_task_history WHERE id = ?", (history_id,)
            ).fetchone()
            if history is None:
                raise ValueError("Unknown task history entry")
            connection.execute(
                """INSERT INTO agent_task_results
                   (id, history_id, provider_id, model_id, result_text, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (result_id, history_id, provider_id, model_id, result_text, created_at),
            )
            self._insert_operation(
                connection, "agent_ai_task_completed", "success", None, None, "agent_ai_task_completed"
            )
        return {"id": result_id, "historyId": history_id, "providerId": provider_id,
                "modelId": model_id, "createdAt": created_at}

    def get_agent_task_result(self, history_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT id, history_id, provider_id, model_id, result_text, created_at
                   FROM agent_task_results WHERE history_id = ?""",
                (history_id,),
            ).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "historyId": row["history_id"],
                "providerId": row["provider_id"], "modelId": row["model_id"],
                "resultText": row["result_text"], "createdAt": row["created_at"]}

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
