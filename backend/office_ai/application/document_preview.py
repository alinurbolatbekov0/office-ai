"""Bounded, read-only extraction for a locally displayed agent preview."""

from __future__ import annotations

import re
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader

from office_ai.application.document_library import DocumentLibrary
from office_ai.domain.agents.task_catalog import get_agent_task

MAX_DOCUMENTS = 5
MAX_PREVIEW_CHARS = 300_000
MAX_XML_MEMBER_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 10_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
MAX_SPREADSHEET_CELLS = 20_000
MAX_PDF_PAGES = 500
MAX_SLIDES = 100
_FORBIDDEN_XML_DECLARATIONS = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
class InvalidDocumentPreview(ValueError):
    """Raised when a selected file cannot safely contribute to a preview."""


class DocumentPreview:
    def __init__(self, library: DocumentLibrary) -> None:
        self.library = library

    def create(
        self,
        *,
        agent_id: str,
        task_code: str,
        document_ids: list[str],
        instruction: str,
    ) -> dict[str, object]:
        task = get_agent_task(agent_id, task_code)
        if task is None:
            raise InvalidDocumentPreview("Неизвестная задача агента.")
        if not document_ids or len(document_ids) > MAX_DOCUMENTS:
            raise InvalidDocumentPreview("Выберите от одного до пяти документов.")
        if len(document_ids) != len(set(document_ids)):
            raise InvalidDocumentPreview("Один документ выбран несколько раз.")
        instruction = instruction.strip()
        if len(instruction) > 10_000:
            raise InvalidDocumentPreview("Инструкция превышает ограничение 10 000 символов.")
        if instruction and "user_instruction" not in task.allowed_categories:
            raise InvalidDocumentPreview("Для этой задачи инструкция не предусмотрена.")

        sources: list[dict[str, object]] = []
        parts = [f"Задача: {task.title}", f"Цель: {task.purpose}"]
        if instruction:
            parts.extend(("Инструкция пользователя:", instruction))

        for document_id in document_ids:
            result = self.library.get_download(document_id)
            if result is None:
                raise InvalidDocumentPreview("Один из выбранных документов не найден.")
            path, filename = result
            document_type = filename.rsplit(".", 1)[-1].lower()
            category = {
                "docx": "document_text",
                "pdf": "document_text",
                "xlsx": "spreadsheet_values",
                "pptx": "presentation_content",
            }.get(document_type)
            if category is None:
                if document_type in {"jpg", "jpeg", "png"}:
                    raise InvalidDocumentPreview(
                        "Извлечение текста из изображений пока не подключено. "
                        "Для изображений потребуется локальный OCR."
                    )
                raise InvalidDocumentPreview("Формат документа не поддерживается этим предпросмотром.")
            if category not in task.allowed_categories:
                raise InvalidDocumentPreview("Тип документа не разрешён для выбранной задачи.")
            text = _extract(path, document_type)
            sources.append({"id": document_id, "name": filename, "category": category, "text": text})
            parts.extend((f"Источник {len(sources)}:", text))

        payload = "\n\n".join(parts)
        if len(payload) > MAX_PREVIEW_CHARS:
            raise InvalidDocumentPreview("Предпросмотр превышает ограничение 300 000 символов.")
        return {
            "agentId": task.agent_id,
            "taskCode": task.code,
            "taskTitle": task.title,
            "purpose": task.purpose,
            "sources": sources,
            "payloadPreview": payload,
            "payloadCharacters": len(payload),
        }


def _extract(path: Path, extension: str) -> str:
    if extension == "docx":
        return _extract_docx(path)
    if extension == "pdf":
        return _extract_pdf(path)
    if extension == "xlsx":
        return _extract_xlsx(path)
    if extension == "pptx":
        return _extract_pptx(path)
    raise InvalidDocumentPreview("Формат документа не поддерживается этим предпросмотром.")


def _extract_pdf(path: Path) -> str:
    """Extract bounded text locally; PDF actions, attachments and scripts are not executed."""
    try:
        reader = PdfReader(path, strict=True, root_object_recovery_limit=5_000)
        if reader.is_encrypted:
            raise InvalidDocumentPreview("Зашифрованные PDF пока не поддерживаются.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise InvalidDocumentPreview("В PDF больше 500 страниц.")
        pages: list[str] = []
        characters_seen = 0
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text(extraction_mode="plain") or ""
            if text.strip():
                page_text = f"Страница {index}:\n{text.strip()}"
                characters_seen += len(page_text)
                if characters_seen > MAX_PREVIEW_CHARS:
                    raise InvalidDocumentPreview("Текст документа превышает ограничение предпросмотра 300 000 символов.")
                pages.append(page_text)
        if not pages:
            raise InvalidDocumentPreview(
                "В PDF не найден текст. Сканированные страницы пока не распознаются (OCR отключён)."
            )
        return "\n\n".join(pages)
    except InvalidDocumentPreview:
        raise
    except Exception as error:
        raise InvalidDocumentPreview("Не удалось безопасно извлечь текст из PDF.") from error


def _read_xml(archive: ZipFile, member: str) -> ET.Element:
    try:
        info = archive.getinfo(member)
    except KeyError as error:
        raise InvalidDocumentPreview("В документе отсутствует требуемый раздел.") from error
    if info.file_size > MAX_XML_MEMBER_BYTES:
        raise InvalidDocumentPreview("Внутренний XML-раздел слишком велик для безопасной обработки.")
    try:
        with archive.open(info) as stream:
            content = stream.read(MAX_XML_MEMBER_BYTES + 1)
    except (BadZipFile, EOFError, OSError, RuntimeError, zlib.error) as error:
        raise InvalidDocumentPreview("Не удалось безопасно прочитать раздел документа.") from error
    if len(content) > MAX_XML_MEMBER_BYTES:
        raise InvalidDocumentPreview("Внутренний XML-раздел слишком велик для безопасной обработки.")
    if _FORBIDDEN_XML_DECLARATIONS.search(content):
        raise InvalidDocumentPreview("XML с пользовательскими объявлениями сущностей не поддерживается.")
    try:
        return ET.fromstring(content)
    except (ET.ParseError, RecursionError) as error:
        raise InvalidDocumentPreview("Не удалось прочитать текстовую структуру документа.") from error


def _open_archive(path: Path) -> ZipFile:
    try:
        archive = ZipFile(path)
        entries = archive.infolist()
        names = [item.filename for item in entries]
        if (
            len(entries) > MAX_ARCHIVE_ENTRIES
            or len(names) != len(set(names))
            or sum(item.file_size for item in entries) > MAX_ARCHIVE_UNCOMPRESSED_BYTES
        ):
            archive.close()
            raise InvalidDocumentPreview("Архив документа превышает ограничения безопасности.")
        return archive
    except (BadZipFile, OSError, RuntimeError) as error:
        raise InvalidDocumentPreview("Не удалось прочитать структуру документа.") from error


def _joined_text(root: ET.Element, namespace: str, tag: str) -> str:
    blocks: list[str] = []
    for block in root.findall(f".//{{{namespace}}}{tag}"):
        value = "".join(node.text or "" for node in block.iter() if node.tag.endswith("}t"))
        if value.strip():
            blocks.append(value)
    return "\n".join(blocks)


def _extract_docx(path: Path) -> str:
    with _open_archive(path) as archive:
        root = _read_xml(archive, "word/document.xml")
    return _bounded_text(_joined_text(root, "http://schemas.openxmlformats.org/wordprocessingml/2006/main", "p"))


def _extract_pptx(path: Path) -> str:
    with _open_archive(path) as archive:
        slides = []
        for name in archive.namelist():
            match = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", name)
            if match:
                slides.append((int(match.group(1)), name))
        slides.sort()
        if len(slides) > MAX_SLIDES:
            raise InvalidDocumentPreview("В презентации больше 100 слайдов.")
        result: list[str] = []
        namespace = "http://schemas.openxmlformats.org/drawingml/2006/main"
        for number, name in slides:
            root = _read_xml(archive, name)
            text = "\n".join((node.text or "") for node in root.findall(f".//{{{namespace}}}t"))
            result.append(_bounded_text(f"Слайд {number}:\n{text}" if text.strip() else f"Слайд {number}: [нет текста]", sum(map(len, result))))
    return "\n\n".join(result)


def _extract_xlsx(path: Path) -> str:
    with _open_archive(path) as archive:
        names = set(archive.namelist())
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = _read_xml(archive, "xl/sharedStrings.xml")
            shared_strings = [
                "".join(node.text or "" for node in item.iter() if node.tag.endswith("}t"))
                for item in root.findall("{*}si")
            ]
        sheets = sorted(
            (name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)),
            key=lambda name: int(re.search(r"sheet(\d+)", name).group(1)),
        )
        if not sheets:
            raise InvalidDocumentPreview("В таблице нет поддерживаемых листов.")
        if len(sheets) > MAX_SLIDES:
            raise InvalidDocumentPreview("В таблице больше 100 листов.")
        rows: list[str] = []
        cells_seen = 0
        for sheet_number, name in enumerate(sheets, 1):
            root = _read_xml(archive, name)
            values: list[str] = []
            for cell in root.findall(".//{*}sheetData/{*}row/{*}c"):
                cells_seen += 1
                if cells_seen > MAX_SPREADSHEET_CELLS:
                    raise InvalidDocumentPreview("Таблица содержит более 20 000 ячеек.")
                if cell.find("{*}f") is not None:
                    continue
                value_node = cell.find("{*}v")
                value = value_node.text if value_node is not None else None
                if cell.get("t") == "s" and value is not None:
                    try:
                        value = shared_strings[int(value)]
                    except (ValueError, IndexError):
                        raise InvalidDocumentPreview("Таблица содержит некорректную ссылку на текст.") from None
                elif cell.get("t") == "inlineStr":
                    inline = cell.find("{*}is")
                    value = "".join(node.text or "" for node in inline.iter() if node.tag.endswith("}t")) if inline is not None else ""
                if value is not None and value != "":
                    values.append(_bounded_text(f"{cell.get('r', '?')} = {value}", sum(map(len, values))))
            rows.append(_bounded_text(f"Лист {sheet_number}:\n" + ("\n".join(values) if values else "[нет сохранённых значений]"), sum(map(len, rows))))
    return "\n\n".join(rows)


def _bounded_text(value: str, current_size: int = 0) -> str:
    if current_size + len(value) > MAX_PREVIEW_CHARS:
        raise InvalidDocumentPreview("Текст документа превышает ограничение предпросмотра 300 000 символов.")
    return value
