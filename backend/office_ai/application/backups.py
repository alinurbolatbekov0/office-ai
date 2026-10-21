"""Local, integrity-checked backups of the database and immutable originals."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import zlib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import AsyncIterable, Any
from uuid import UUID, uuid4
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from office_ai import __version__
from office_ai.infrastructure.database import LocalDatabase, SCHEMA_VERSION

BACKUP_FORMAT = "office-ai-backup"
MAX_BACKUP_SIZE_BYTES = 2 * 1024 * 1024 * 1024
MAX_DATABASE_SIZE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 10_002
MAX_MANIFEST_SIZE_BYTES = 4 * 1024 * 1024
_BACKUP_ID = re.compile(r"^[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class InvalidBackup(ValueError):
    """Raised when a backup is malformed, unsafe or inconsistent."""


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class BackupService:
    """Creates backups under the user data root and restores only validated archives."""

    def __init__(self, database: LocalDatabase) -> None:
        self.database = database
        self.data_directory = database.data_directory
        self.documents_root = self.data_directory / "documents"
        self.backups_root = self.data_directory / "backups"

    def _ensure_roots(self) -> Path:
        self.data_directory.mkdir(parents=True, exist_ok=True)
        data_root = self.data_directory.resolve(strict=True)
        self.backups_root.mkdir(parents=True, exist_ok=True)
        backup_root = self.backups_root.resolve(strict=True)
        if not backup_root.is_relative_to(data_root) or backup_root == data_root:
            raise InvalidBackup("Каталог резервных копий выходит за пределы локальных данных.")
        return backup_root

    def create_backup(self) -> dict[str, Any]:
        """Create a stable SQLite snapshot and include every stored original."""
        backup_root = self._ensure_roots()
        database_path = self.database.database_path.resolve(strict=True)
        if not database_path.is_relative_to(self.data_directory.resolve()) or not database_path.is_file():
            raise InvalidBackup("База данных выходит за пределы локальных данных.")
        if self.documents_root.exists() and not self.documents_root.resolve().is_relative_to(self.data_directory.resolve()):
            raise InvalidBackup("Каталог документов выходит за пределы локальных данных.")

        backup_id = uuid4().hex
        work = backup_root / f".create-{backup_id}"
        work.mkdir(mode=0o700)
        temporary_archive = work / "archive.zip"
        try:
            snapshot_path = work / "officeai.sqlite3"
            with sqlite3.connect(database_path, timeout=5.0) as source:
                with sqlite3.connect(snapshot_path) as snapshot:
                    source.backup(snapshot)
            db_digest, db_size = _sha256(snapshot_path)
            if db_size > MAX_DATABASE_SIZE_BYTES:
                raise InvalidBackup("Размер локальной базы превышает лимит резервного копирования.")

            with sqlite3.connect(snapshot_path) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    "SELECT id, storage_key, size_bytes, sha256 FROM stored_files ORDER BY id"
                ).fetchall()
            entries: list[dict[str, Any]] = [{
                "path": "database/officeai.sqlite3",
                "sizeBytes": db_size,
                "sha256": db_digest,
            }]
            total_size = db_size
            content_files: list[tuple[str, Path, str, int]] = [(entries[0]["path"], snapshot_path, db_digest, db_size)]
            documents_root = self.documents_root.resolve(strict=True) if self.documents_root.exists() else self.documents_root
            for row in rows:
                try:
                    file_id = str(UUID(row["id"]))
                except (ValueError, TypeError, AttributeError) as error:
                    raise InvalidBackup("В базе обнаружена некорректная ссылка на документ.") from error
                archive_name = f"documents/{file_id}.bin"
                if row["storage_key"] != archive_name:
                    raise InvalidBackup("В базе обнаружен некорректный путь к документу.")
                source_path = documents_root / f"{file_id}.bin"
                try:
                    resolved = source_path.resolve(strict=True)
                except OSError as error:
                    raise InvalidBackup("Не удалось найти оригинал из библиотеки.") from error
                if not resolved.is_relative_to(documents_root) or not resolved.is_file():
                    raise InvalidBackup("Путь к оригиналу выходит за пределы хранилища.")
                digest, size = _sha256(resolved)
                if digest != row["sha256"] or size != row["size_bytes"]:
                    raise InvalidBackup("Файл библиотеки не совпадает с метаданными базы.")
                total_size += size
                if total_size > MAX_BACKUP_SIZE_BYTES:
                    raise InvalidBackup("Суммарный размер данных превышает ограничение 2 ГиБ.")
                entries.append({"path": archive_name, "sizeBytes": size, "sha256": digest})
                content_files.append((archive_name, resolved, digest, size))
                if len(entries) > MAX_ARCHIVE_MEMBERS - 1:
                    raise InvalidBackup("В библиотеке слишком много файлов для резервной копии.")

            manifest = {
                "format": BACKUP_FORMAT,
                "schemaVersion": SCHEMA_VERSION,
                "applicationVersion": __version__,
                "createdAt": _utc_now(),
                "files": entries,
            }
            with ZipFile(temporary_archive, "w", compression=ZIP_STORED, allowZip64=True) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
                for archive_name, source_path, expected_digest, expected_size in content_files:
                    with source_path.open("rb") as source, archive.open(archive_name, "w") as target:
                        digest = hashlib.sha256()
                        size = 0
                        while chunk := source.read(1024 * 1024):
                            target.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                    if size != expected_size or digest.hexdigest() != expected_digest:
                        raise InvalidBackup("Данные изменились во время создания резервной копии.")
            archive_size = temporary_archive.stat().st_size
            if archive_size > MAX_BACKUP_SIZE_BYTES:
                raise InvalidBackup("Резервная копия превышает ограничение 2 ГиБ.")
            filename = f"officeai-backup-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{backup_id[:8]}.zip"
            destination = backup_root / f"{backup_id}.zip"
            os.replace(temporary_archive, destination)
            return {
                "id": backup_id,
                "filename": filename,
                "sizeBytes": archive_size,
                "createdAt": manifest["createdAt"],
            }
        finally:
            shutil.rmtree(work, ignore_errors=True)

    async def receive_restore_upload(self, chunks: AsyncIterable[bytes]) -> Path:
        """Stream a user-selected archive into a private temporary local file."""
        backup_root = self._ensure_roots()
        upload_path = backup_root / f".restore-upload-{uuid4().hex}.zip"
        size = 0
        try:
            with upload_path.open("xb") as output:
                async for chunk in chunks:
                    if not isinstance(chunk, bytes):
                        raise InvalidBackup("Получен некорректный блок резервной копии.")
                    size += len(chunk)
                    if size > MAX_BACKUP_SIZE_BYTES:
                        raise InvalidBackup("Размер резервной копии превышает ограничение 2 ГиБ.")
                    output.write(chunk)
            if size == 0:
                raise InvalidBackup("Выбранный файл пуст.")
            return upload_path
        except BaseException:
            upload_path.unlink(missing_ok=True)
            raise

    def restore_archive(self, archive_path: Path) -> None:
        """Validate the full archive in staging, then swap data with rollback."""
        backup_root = self._ensure_roots()
        try:
            if archive_path.parent.resolve() != backup_root or not archive_path.name.startswith(".restore-upload-"):
                raise InvalidBackup("Резервная копия не находится во временном локальном каталоге.")
            if archive_path.stat().st_size > MAX_BACKUP_SIZE_BYTES:
                raise InvalidBackup("Размер резервной копии превышает ограничение 2 ГиБ.")
            work = backup_root / f".restore-{uuid4().hex}"
            work.mkdir(mode=0o700)
            try:
                staged_database, staged_documents = self._validate_and_extract(archive_path, work)
                self._replace_live_data(staged_database, staged_documents, work)
                self.database.record_operation("backup_restored", message_code="backup_restored")
            finally:
                shutil.rmtree(work, ignore_errors=True)
        finally:
            archive_path.unlink(missing_ok=True)

    def _validate_and_extract(self, archive_path: Path, work: Path) -> tuple[Path, Path]:
        staged_database = work / "officeai.sqlite3"
        staged_documents = work / "documents"
        staged_documents.mkdir()
        try:
            with ZipFile(archive_path, "r") as archive:
                infos = archive.infolist()
                if not 2 <= len(infos) <= MAX_ARCHIVE_MEMBERS:
                    raise InvalidBackup("Архив содержит недопустимое количество элементов.")
                names = [info.filename for info in infos]
                if len(names) != len(set(names)) or "manifest.json" not in names:
                    raise InvalidBackup("В архиве есть повторяющиеся элементы или отсутствует манифест.")
                for info in infos:
                    if info.is_dir() or info.flag_bits & 0x1 or info.compress_type not in {ZIP_STORED, ZIP_DEFLATED}:
                        raise InvalidBackup("Архив содержит неподдерживаемый или небезопасный элемент.")
                    if stat.S_ISLNK(info.external_attr >> 16):
                        raise InvalidBackup("Символические ссылки в архиве не разрешены.")
                    if info.file_size < 0 or info.file_size > MAX_BACKUP_SIZE_BYTES:
                        raise InvalidBackup("Размер элемента архива превышает ограничение.")
                manifest_info = archive.getinfo("manifest.json")
                if manifest_info.file_size > MAX_MANIFEST_SIZE_BYTES:
                    raise InvalidBackup("Манифест резервной копии слишком велик.")
                try:
                    manifest = json.loads(archive.read(manifest_info))
                except (UnicodeDecodeError, json.JSONDecodeError, BadZipFile) as error:
                    raise InvalidBackup("Манифест резервной копии повреждён.") from error
                if (
                    not isinstance(manifest, dict)
                    or manifest.get("format") != BACKUP_FORMAT
                    or manifest.get("schemaVersion") != SCHEMA_VERSION
                    or not isinstance(manifest.get("files"), list)
                ):
                    raise InvalidBackup("Формат или версия резервной копии не поддерживается.")
                declared: dict[str, tuple[int, str]] = {}
                total_size = 0
                for entry in manifest["files"]:
                    if not isinstance(entry, dict):
                        raise InvalidBackup("Манифест содержит некорректную запись.")
                    name, size, digest = entry.get("path"), entry.get("sizeBytes"), entry.get("sha256")
                    if not isinstance(name, str) or not isinstance(size, int) or isinstance(size, bool) or not isinstance(digest, str):
                        raise InvalidBackup("Манифест содержит некорректные метаданные файла.")
                    canonical = PurePosixPath(name)
                    if canonical.is_absolute() or ".." in canonical.parts or str(canonical) != name:
                        raise InvalidBackup("В манифесте обнаружен небезопасный путь.")
                    if name != "database/officeai.sqlite3" and not re.fullmatch(r"documents/[0-9a-f-]{36}\.bin", name):
                        raise InvalidBackup("В манифесте обнаружен неизвестный тип файла.")
                    if size < 0 or size > (MAX_DATABASE_SIZE_BYTES if name.startswith("database/") else 100 * 1024 * 1024):
                        raise InvalidBackup("Размер файла в манифесте недопустим.")
                    if not _SHA256.fullmatch(digest) or name in declared:
                        raise InvalidBackup("Хеш или путь в манифесте некорректен.")
                    declared[name] = (size, digest)
                    total_size += size
                    if total_size > MAX_BACKUP_SIZE_BYTES:
                        raise InvalidBackup("Распакованный объём превышает ограничение 2 ГиБ.")
                if "database/officeai.sqlite3" not in declared:
                    raise InvalidBackup("В резервной копии отсутствует база данных.")
                if set(names) != {"manifest.json", *declared.keys()}:
                    raise InvalidBackup("Содержимое архива не совпадает с манифестом.")

                for name, (expected_size, expected_digest) in declared.items():
                    info = archive.getinfo(name)
                    if info.file_size != expected_size:
                        raise InvalidBackup("Размер файла не совпадает с манифестом.")
                    destination = staged_database if name == "database/officeai.sqlite3" else staged_documents / PurePosixPath(name).name
                    digest = hashlib.sha256()
                    size = 0
                    with archive.open(info, "r") as source, destination.open("xb") as output:
                        while chunk := source.read(1024 * 1024):
                            size += len(chunk)
                            if size > expected_size:
                                raise InvalidBackup("Файл в архиве превышает заявленный размер.")
                            digest.update(chunk)
                            output.write(chunk)
                    if size != expected_size or digest.hexdigest() != expected_digest:
                        raise InvalidBackup("Контрольная сумма файла не совпадает.")
        except (BadZipFile, OSError, RuntimeError, EOFError, zlib.error) as error:
            if isinstance(error, InvalidBackup):
                raise
            raise InvalidBackup("Не удалось прочитать резервный архив.") from error

        self._validate_database(staged_database, staged_documents, declared)
        return staged_database, staged_documents

    @staticmethod
    def _validate_database(database_path: Path, documents_root: Path, declared: dict[str, tuple[int, str]]) -> None:
        try:
            with sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True, timeout=5.0) as connection:
                connection.row_factory = sqlite3.Row
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise InvalidBackup("База данных внутри архива повреждена.")
                if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                    raise InvalidBackup("Версия схемы базы данных не поддерживается.")
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {"schema_migrations", "app_settings", "operation_log", "stored_files", "documents"}.issubset(tables):
                    raise InvalidBackup("В базе данных отсутствуют обязательные таблицы.")
                if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise InvalidBackup("Связи в базе данных повреждены.")
                rows = connection.execute("SELECT id, storage_key, size_bytes, sha256 FROM stored_files").fetchall()
                expected_documents = {name: details for name, details in declared.items() if name.startswith("documents/")}
                if len(rows) != len(expected_documents):
                    raise InvalidBackup("Список документов в базе не совпадает с манифестом.")
                found: set[str] = set()
                for row in rows:
                    file_id = str(UUID(row["id"]))
                    name = f"documents/{file_id}.bin"
                    if row["storage_key"] != name or name not in expected_documents:
                        raise InvalidBackup("Путь или запись документа в базе некорректны.")
                    declared_size, declared_digest = expected_documents[name]
                    if row["size_bytes"] != declared_size or row["sha256"] != declared_digest:
                        raise InvalidBackup("Метаданные документа не совпадают с манифестом.")
                    found.add(name)
                if found != set(expected_documents):
                    raise InvalidBackup("В резервной копии не хватает оригиналов документов.")
        except (sqlite3.DatabaseError, ValueError, TypeError) as error:
            if isinstance(error, InvalidBackup):
                raise
            raise InvalidBackup("База данных внутри архива не прошла проверку.") from error
        if {f"documents/{path.name}" for path in documents_root.iterdir()} != {
            name for name in declared if name.startswith("documents/")
        }:
            raise InvalidBackup("Файлы документов в архиве не совпадают с манифестом.")

    def _replace_live_data(self, staged_database: Path, staged_documents: Path, work: Path) -> None:
        data_root = self.data_directory.resolve(strict=True)
        current_database = self.database.database_path
        if not current_database.resolve(strict=True).is_relative_to(data_root):
            raise InvalidBackup("Текущая база данных выходит за пределы локальных данных.")
        if self.documents_root.exists() and not self.documents_root.resolve().is_relative_to(data_root):
            raise InvalidBackup("Текущий каталог документов выходит за пределы локальных данных.")
        with sqlite3.connect(current_database, timeout=5.0) as connection:
            checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint and checkpoint[0] != 0:
                raise InvalidBackup("Не удалось подготовить базу данных к восстановлению.")

        previous = work / "previous"
        previous.mkdir()
        moved: list[tuple[Path, Path]] = []
        installed: list[Path] = []
        try:
            for live_path in (current_database, Path(f"{current_database}-wal"), Path(f"{current_database}-shm"), self.documents_root):
                if live_path.exists():
                    saved_path = previous / live_path.name
                    os.replace(live_path, saved_path)
                    moved.append((saved_path, live_path))
            os.replace(staged_database, current_database)
            installed.append(current_database)
            os.replace(staged_documents, self.documents_root)
            installed.append(self.documents_root)
        except Exception:
            for new_path in reversed(installed):
                if new_path.is_dir():
                    shutil.rmtree(new_path, ignore_errors=True)
                else:
                    new_path.unlink(missing_ok=True)
            for saved_path, live_path in reversed(moved):
                if saved_path.exists():
                    os.replace(saved_path, live_path)
            raise InvalidBackup("Не удалось завершить восстановление; прежние данные возвращены.")

    def get_backup_download(self, backup_id: str) -> tuple[Path, str] | None:
        if not _BACKUP_ID.fullmatch(backup_id):
            return None
        root = self._ensure_roots()
        path = root / f"{backup_id}.zip"
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            return None
        if not resolved.is_relative_to(root) or not resolved.is_file():
            return None
        # The generated download name is read from the trusted manifest.
        try:
            with ZipFile(resolved) as archive:
                manifest = json.loads(archive.read("manifest.json"))
            created = datetime.fromisoformat(manifest["createdAt"].replace("Z", "+00:00"))
        except (BadZipFile, KeyError, ValueError, TypeError, json.JSONDecodeError):
            return None
        return resolved, f"officeai-backup-{created:%Y%m%d-%H%M%S}-{backup_id[:8]}.zip"
