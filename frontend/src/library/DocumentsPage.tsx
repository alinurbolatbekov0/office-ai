import { useCallback, useEffect, useState, type ChangeEvent } from "react";

import type { RuntimeConfig } from "../platform/desktopBridge";
import {
  DuplicateDocumentError,
  downloadDocument,
  getDocuments,
  uploadDocument,
  type LibraryDocument,
} from "../platform/localApi";

const MAX_FILE_BYTES = 100 * 1024 * 1024;

interface DocumentsPageProps {
  runtimeConfig: RuntimeConfig | null;
}

export default function DocumentsPage({ runtimeConfig }: DocumentsPageProps) {
  const [documents, setDocuments] = useState<LibraryDocument[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [type, setType] = useState("");
  const [importedFrom, setImportedFrom] = useState("");
  const [importedTo, setImportedTo] = useState("");
  const [sortBy, setSortBy] = useState("imported_at");
  const [sortOrder, setSortOrder] = useState("desc");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [pendingDuplicate, setPendingDuplicate] = useState<{
    file: File;
    matches: LibraryDocument[];
  } | null>(null);

  const refresh = useCallback(async () => {
    if (!runtimeConfig) return;
    setLoading(true);
    try {
      const result = await getDocuments(runtimeConfig, {
        search,
        type: type as LibraryDocument["type"] | "",
        importedFrom,
        importedTo,
        sortBy: sortBy as "name" | "imported_at" | "size_bytes" | "type",
        sortOrder: sortOrder as "asc" | "desc",
      });
      setDocuments(result.documents);
      setTotal(result.total);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось загрузить библиотеку.");
    } finally {
      setLoading(false);
    }
  }, [runtimeConfig, search, type, importedFrom, importedTo, sortBy, sortOrder]);

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 180);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !runtimeConfig) return;
    if (file.size > MAX_FILE_BYTES) {
      setMessage("Файл превышает ограничение 100 МиБ.");
      return;
    }
    setBusy(true);
    setMessage(null);
    setPendingDuplicate(null);
    try {
      const result = await uploadDocument(runtimeConfig, file);
      if (result.document) {
        setMessage("Оригинал добавлен в локальную библиотеку.");
        await refresh();
      }
    } catch (error) {
      if (error instanceof DuplicateDocumentError) {
        setPendingDuplicate({ file, matches: error.existingDocuments });
      } else {
        setMessage(error instanceof Error ? error.message : "Не удалось добавить файл.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function confirmDuplicate() {
    if (!runtimeConfig || !pendingDuplicate) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await uploadDocument(runtimeConfig, pendingDuplicate.file, true);
      setPendingDuplicate(null);
      setMessage(result.document ? "Добавлена ещё одна запись; байты файла хранятся в одном экземпляре." : "Файл добавлен.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось добавить дубликат.");
    } finally {
      setBusy(false);
    }
  }

  async function handleDownload(document: LibraryDocument) {
    if (!runtimeConfig) return;
    setMessage(null);
    try {
      await downloadDocument(runtimeConfig, document);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось скачать файл.");
    }
  }

  return (
    <div className="library-page">
      <div className="page-title-block library-title-row">
        <div>
          <span className="eyebrow">ЛОКАЛЬНОЕ ХРАНИЛИЩЕ</span>
          <h1>Библиотека документов</h1>
          <p>Оригиналы сохраняются без изменений в профиле текущего пользователя.</p>
        </div>
        <label className={`primary-button upload-button ${busy || !runtimeConfig ? "disabled" : ""}`}>
          {busy ? "Обработка…" : "Добавить файл"}
          <input
            accept=".docx,.xlsx,.pptx,.pdf,.jpg,.jpeg,.png"
            disabled={busy || !runtimeConfig}
            onChange={handleFileChange}
            type="file"
          />
        </label>
      </div>

      <div className="library-toolbar">
        <label className="search-field">
          <span aria-hidden="true">⌕</span>
          <input
            aria-label="Поиск по имени файла"
            maxLength={200}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Поиск по имени файла"
            value={search}
          />
        </label>
        <select aria-label="Фильтр по типу" onChange={(event) => setType(event.target.value)} value={type}>
          <option value="">Все типы</option>
          <option value="DOCX">DOCX</option>
          <option value="XLSX">XLSX</option>
          <option value="PPTX">PPTX</option>
          <option value="PDF">PDF</option>
          <option value="JPEG">JPEG</option>
          <option value="PNG">PNG</option>
        </select>
        <label className="date-filter"><span>С</span><input aria-label="Импортировано с" onChange={(event) => setImportedFrom(event.target.value)} type="date" value={importedFrom} /></label>
        <label className="date-filter"><span>По</span><input aria-label="Импортировано по" onChange={(event) => setImportedTo(event.target.value)} type="date" value={importedTo} /></label>
        <select aria-label="Сортировка" onChange={(event) => setSortBy(event.target.value)} value={sortBy}>
          <option value="imported_at">По дате</option>
          <option value="name">По имени</option>
          <option value="size_bytes">По размеру</option>
          <option value="type">По типу</option>
        </select>
        <button
          aria-label={sortOrder === "desc" ? "Сначала новые" : "Сначала старые"}
          className="sort-direction"
          onClick={() => setSortOrder(sortOrder === "desc" ? "asc" : "desc")}
          type="button"
        >
          {sortOrder === "desc" ? "↓" : "↑"}
        </button>
      </div>

      {message && <div className="library-feedback" role="status">{message}</div>}
      {pendingDuplicate && (
        <section className="duplicate-confirmation" aria-live="polite">
          <div>
            <strong>Такое содержимое уже есть в библиотеке.</strong>
            <p>Оригинал не перезаписан. Добавить отдельную запись «{pendingDuplicate.file.name}»? Байты останутся в одном экземпляре.</p>
            {pendingDuplicate.matches.map((match) => <small key={match.id}>Совпадение: {match.name}</small>)}
          </div>
          <div className="duplicate-actions">
            <button className="secondary-button" disabled={busy} onClick={() => setPendingDuplicate(null)} type="button">Отмена</button>
            <button className="primary-button" disabled={busy} onClick={() => void confirmDuplicate()} type="button">Добавить запись</button>
          </div>
        </section>
      )}

      <section className="document-table-card">
        <div className="document-list-heading"><h2>Файлы</h2><span>{total} {pluralize(total, "документ", "документа", "документов")}</span></div>
        {loading ? (
          <div className="library-empty">Обновляем список…</div>
        ) : documents.length === 0 ? (
          <div className="library-empty">{total === 0 ? "Библиотека пока пуста. Добавьте первый файл." : "По выбранным условиям ничего не найдено."}</div>
        ) : (
          <div className="document-table-scroll">
            <table className="document-table">
              <thead><tr><th>Имя</th><th>Тип</th><th>Размер</th><th>Добавлен</th><th><span className="visually-hidden">Действие</span></th></tr></thead>
              <tbody>{documents.map((document) => (
                <tr key={document.id}>
                  <td><span className="file-type-icon">{fileIcon(document.type)}</span><span className="document-name">{document.name}</span></td>
                  <td><span className="type-pill">{document.type}</span></td>
                  <td>{formatSize(document.sizeBytes)}</td>
                  <td>{formatDate(document.importedAt)}</td>
                  <td><button className="download-button" onClick={() => void handleDownload(document)} type="button">Скачать</button></td>
                </tr>
              ))}</tbody>
            </table>
            {total > documents.length && <p className="page-limit-note">Показаны первые {documents.length} файлов. Уточните поиск, чтобы найти остальные.</p>}
          </div>
        )}
      </section>
      <p className="library-footnote">Поддерживаются DOCX, XLSX, PPTX, PDF, JPG/JPEG и PNG. Максимальный размер — 100 МиБ. Файлы не открываются и не исполняются приложением.</p>
    </div>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", year: "numeric" }).format(new Date(value));
}

function fileIcon(type: LibraryDocument["type"]): string {
  return ({ DOCX: "W", XLSX: "X", PPTX: "P", PDF: "P", JPEG: "J", PNG: "I" })[type];
}

function pluralize(count: number, one: string, few: string, many: string): string {
  const lastTwo = count % 100;
  const last = count % 10;
  if (lastTwo >= 11 && lastTwo <= 14) return many;
  if (last === 1) return one;
  if (last >= 2 && last <= 4) return few;
  return many;
}
