"""Document file types and upload validation rules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile

MAX_DOCUMENT_SIZE_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class DetectedDocument:
    type: str
    extension: str


class InvalidDocument(ValueError):
    """Raised when a file name, size, or signature is not supported."""


def validate_original_name(name: str) -> tuple[str, str]:
    """Return a safe basename and extension; never retain a supplied path."""
    if not isinstance(name, str) or not name or len(name) > 255:
        raise InvalidDocument("Недопустимое имя файла.")
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise InvalidDocument("Имя файла содержит управляющие символы.")
    basename = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if basename in {"", ".", ".."}:
        raise InvalidDocument("Недопустимое имя файла.")
    if len(basename) > 255:
        raise InvalidDocument("Имя файла слишком длинное.")
    if "." not in basename or basename.startswith("."):
        raise InvalidDocument("У файла должно быть поддерживаемое расширение.")
    extension = basename.rsplit(".", 1)[-1].lower()
    if extension not in {"docx", "xlsx", "pptx", "pdf", "jpg", "jpeg", "png"}:
        raise InvalidDocument("Формат файла не поддерживается.")
    return basename, extension


def detect_document_type(path: Path, extension: str) -> DetectedDocument:
    """Inspect signatures and Office ZIP members without extracting or executing."""
    with path.open("rb") as file:
        prefix = file.read(16)
        file.seek(0, 2)
        size = file.tell()

    if size <= 0 or size > MAX_DOCUMENT_SIZE_BYTES:
        raise InvalidDocument("Размер файла должен быть от 1 байта до 100 МиБ.")

    detected: DetectedDocument | None = None
    if prefix.startswith(b"%PDF-"):
        if size < 8:
            raise InvalidDocument("PDF-файл слишком короткий.")
        detected = DetectedDocument("PDF", "pdf")
    elif prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        if size < 45:
            raise InvalidDocument("PNG-файл имеет неполную структуру.")
        with path.open("rb") as file:
            header = file.read(24)
            file.seek(-12, 2)
            end_chunk = file.read(12)
        width = int.from_bytes(header[16:20], "big")
        height = int.from_bytes(header[20:24], "big")
        if (
            header[8:12] != b"\x00\x00\x00\r"
            or header[12:16] != b"IHDR"
            or not 0 < width <= 100_000
            or not 0 < height <= 100_000
            or end_chunk != b"\x00\x00\x00\x00IEND\xaeB`\x82"
        ):
            raise InvalidDocument("PNG-файл имеет некорректную структуру.")
        detected = DetectedDocument("PNG", "png")
    elif prefix.startswith(b"\xff\xd8\xff"):
        with path.open("rb") as file:
            file.seek(-2, 2)
            if file.read(2) != b"\xff\xd9":
                raise InvalidDocument("JPEG-файл не завершён корректно.")
        detected = DetectedDocument("JPEG", "jpg")
    elif prefix.startswith(b"PK\x03\x04"):
        office_types = {
            "docx": ("DOCX", "docx", "word/document.xml"),
            "xlsx": ("XLSX", "xlsx", "xl/workbook.xml"),
            "pptx": ("PPTX", "pptx", "ppt/presentation.xml"),
        }
        office_type = office_types.get(extension)
        if office_type is None:
            raise InvalidDocument("Содержимое файла не соответствует расширению.")
        try:
            with ZipFile(path) as archive:
                entries = archive.infolist()
                names = {entry.filename for entry in entries}
                if (
                    len(entries) > 10_000
                    or sum(entry.file_size for entry in entries) > 500 * 1024 * 1024
                    or "[Content_Types].xml" not in names
                    or office_type[2] not in names
                ):
                    raise InvalidDocument("Структура Office-файла некорректна.")
        except (BadZipFile, OSError, RuntimeError) as error:
            raise InvalidDocument("Не удалось проверить структуру Office-файла.") from error
        detected = DetectedDocument(office_type[0], office_type[1])

    if detected is None:
        raise InvalidDocument("Содержимое файла не соответствует поддерживаемому формату.")
    extension_matches = detected.extension == extension or (
        detected.type == "JPEG" and extension == "jpeg"
    )
    if not extension_matches:
        raise InvalidDocument("Содержимое файла не соответствует расширению.")
    return detected
