"""Document-library use cases; original content is stored without conversion."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
from typing import AsyncIterable, Any
from uuid import UUID, uuid4

from office_ai.domain.documents import (
    MAX_DOCUMENT_SIZE_BYTES,
    InvalidDocument,
    detect_document_type,
    validate_original_name,
)
from office_ai.infrastructure.database import LocalDatabase


class DocumentLibrary:
    def __init__(self, database: LocalDatabase) -> None:
        self.database = database
        self.data_directory = database.data_directory
        self.documents_root = self.data_directory / "documents"

    async def upload(
        self,
        original_name: str,
        chunks: AsyncIterable[bytes],
        *,
        allow_duplicate: bool = False,
    ) -> dict[str, Any]:
        basename, extension = validate_original_name(original_name)
        self.documents_root.mkdir(parents=True, exist_ok=True)
        root = self.documents_root.resolve()
        if not root.is_relative_to(self.data_directory.resolve()):
            raise InvalidDocument("Хранилище документов выходит за пределы каталога данных.")
        temp_directory = self.documents_root / ".tmp"
        temp_directory.mkdir(exist_ok=True)
        if temp_directory.resolve().parent != root:
            raise InvalidDocument("Временный каталог выходит за пределы хранилища.")

        temporary_path = temp_directory / f"{uuid4().hex}.upload"
        digest = hashlib.sha256()
        size_bytes = 0
        final_path: Path | None = None
        registered = False
        try:
            with temporary_path.open("xb") as output:
                async for chunk in chunks:
                    if not isinstance(chunk, bytes):
                        raise InvalidDocument("Получен некорректный блок файла.")
                    size_bytes += len(chunk)
                    if size_bytes > MAX_DOCUMENT_SIZE_BYTES:
                        raise InvalidDocument("Размер файла превышает ограничение 100 МиБ.")
                    digest.update(chunk)
                    output.write(chunk)
            detected = detect_document_type(temporary_path, extension)
            checksum = digest.hexdigest()

            document_id = str(uuid4())
            stored_file_id = str(uuid4())
            storage_key = f"documents/{stored_file_id}.bin"
            final_path = self.documents_root / f"{stored_file_id}.bin"
            if final_path.exists() or final_path.parent.resolve() != root:
                raise InvalidDocument("Не удалось безопасно подготовить место для хранения.")
            # A hard link is an atomic, create-if-absent move on supported local
            # filesystems. It prevents replacing an existing stored original.
            os.link(temporary_path, final_path)
            temporary_path.unlink()

            result = self.database.register_document(
                document_id=document_id,
                stored_file_id=stored_file_id,
                storage_key=storage_key,
                sha256=checksum,
                size_bytes=size_bytes,
                detected_type=detected.type,
                original_name=basename,
                extension=extension,
                allow_duplicate=allow_duplicate,
            )
            if result["duplicate"]:
                final_path.unlink(missing_ok=True)
                final_path = None
                if allow_duplicate:
                    return {
                        "duplicate": True,
                        "confirmed": True,
                        "document": result["document"],
                    }
                return {
                    "duplicate": True,
                    "existingDocuments": self.database.list_duplicate_documents(checksum),
                }
            registered = True
            return {"duplicate": False, "document": result["document"]}
        except InvalidDocument:
            self.database.record_operation(
                "document_upload_rejected",
                outcome="failure",
                message_code="document_upload_rejected",
            )
            raise
        finally:
            temporary_path.unlink(missing_ok=True)
            if final_path is not None and not registered:
                # If persistence failed, clean up the not-yet-registered copy.
                final_path.unlink(missing_ok=True)

    def get_download(self, document_id: str) -> tuple[Path, str] | None:
        try:
            normalized_id = str(UUID(document_id))
        except (ValueError, AttributeError):
            return None
        document = self.database.get_document_download(normalized_id)
        if document is None:
            return None
        storage_key = PurePosixPath(document["storageKey"])
        if (
            storage_key.is_absolute()
            or len(storage_key.parts) != 2
            or storage_key.parts[0] != "documents"
            or storage_key.parts[1] != f"{document['storageFileId']}.bin"
        ):
            return None
        resolved_root = self.documents_root.resolve()
        if not resolved_root.is_relative_to(self.data_directory.resolve()):
            return None
        try:
            path = (self.data_directory / Path(*storage_key.parts)).resolve(strict=True)
        except OSError:
            return None
        if not path.is_relative_to(resolved_root) or not path.is_file():
            return None
        return path, document["name"]

    def query(
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
        return self.database.list_documents(
            search=search.strip(),
            detected_type=detected_type,
            imported_from=imported_from,
            imported_to=imported_to,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )
