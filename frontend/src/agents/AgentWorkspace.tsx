import { useEffect, useMemo, useState, type FormEvent } from "react";

import { definitions } from "./registry";
import {
  createAgentTaskPreview,
  getAgentTasks,
  getAgentTaskHistory,
  getDocuments,
  type AgentTask,
  type AgentTaskPreview,
  type AgentTaskHistoryEntry,
  type LibraryDocument,
} from "../platform/localApi";
import type { RuntimeConfig } from "../platform/desktopBridge";
import type { AgentDescriptor } from "../platform/localApi";

const categoryDocumentTypes: Record<string, LibraryDocument["type"][]> = {
  document_text: ["DOCX", "PDF"],
  spreadsheet_values: ["XLSX"],
  presentation_content: ["PPTX"],
};

export default function AgentWorkspace({
  agent,
  runtimeConfig,
}: {
  agent: AgentDescriptor;
  runtimeConfig: RuntimeConfig | null;
}) {
  const screen = definitions[agent.id];
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [documents, setDocuments] = useState<LibraryDocument[]>([]);
  const [taskCode, setTaskCode] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [documentQuery, setDocumentQuery] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [documentOffset, setDocumentOffset] = useState(0);
  const [documentTotal, setDocumentTotal] = useState(0);
  const [instruction, setInstruction] = useState("");
  const [preview, setPreview] = useState<AgentTaskPreview | null>(null);
  const [history, setHistory] = useState<AgentTaskHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setTasks([]);
    setTaskCode("");
    setSelectedIds([]);
    setInstruction("");
    setPreview(null);
    if (!runtimeConfig) {
      setLoading(false);
      return;
    }
    Promise.all([getAgentTasks(runtimeConfig, agent.id), getAgentTaskHistory(runtimeConfig)])
      .then(([nextTasks, taskHistory]) => {
        if (!active) return;
        setTasks(nextTasks);
        setTaskCode(nextTasks[0]?.code || "");
        setHistory(taskHistory);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Не удалось загрузить данные агента.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [agent.id, runtimeConfig]);

  useEffect(() => {
    let active = true;
    if (!runtimeConfig) return;
    setLoadingDocuments(true);
    getDocuments(runtimeConfig, { search: documentQuery, limit: 200, offset: documentOffset })
      .then((response) => {
        if (!active) return;
        setDocuments((current) => documentOffset === 0 ? response.documents : [...current, ...response.documents]);
        setDocumentTotal(response.total);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Не удалось загрузить список документов.");
      })
      .finally(() => { if (active) setLoadingDocuments(false); });
    return () => { active = false; };
  }, [documentQuery, documentOffset, runtimeConfig]);

  const task = tasks.find((entry) => entry.code === taskCode);
  const selectableDocuments = useMemo(() => {
    const supportedTypes = new Set((task?.allowed_categories ?? []).flatMap((category) => categoryDocumentTypes[category] ?? []));
    return documents.filter((document) => supportedTypes.has(document.type));
  }, [documents, task]);

  if (!screen) {
    return (
      <section className="placeholder-panel">
        <span className="eyebrow">ПОДГОТОВЛЕННЫЙ МОДУЛЬ</span>
        <h1>{agent.title}</h1>
        <p>{agent.description}</p>
        <div className="availability-note"><span /> Выполнение задач пока не подключено.</div>
      </section>
    );
  }

  function toggleDocument(id: string) {
    setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
    setPreview(null);
  }

  function submitDocumentSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextQuery = searchInput.trim();
    if (nextQuery === documentQuery && documentOffset === 0) return;
    setDocuments([]);
    setDocumentOffset(0);
    setDocumentQuery(nextQuery);
  }

  async function handlePreview() {
    if (!runtimeConfig || !task || selectedIds.length === 0) return;
    setWorking(true);
    setError(null);
    setPreview(null);
    try {
      const result = await createAgentTaskPreview(runtimeConfig, agent.id, task.code, selectedIds, instruction);
      setPreview(result);
      if (result.historyEntry) setHistory((current) => [result.historyEntry!, ...current].slice(0, 20));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось сформировать предпросмотр.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <section className="agent-workspace">
      <header className="agent-page-heading">
        <span className={`agent-workspace-symbol agent-color-${screen.id}`} aria-hidden="true">{screen.symbol}</span>
        <div>
          <span className="eyebrow">ЛОКАЛЬНАЯ РАБОЧАЯ ОБЛАСТЬ</span>
          <h1>{agent.title}</h1>
          <p>{screen.intro}</p>
        </div>
        <span className="agent-status-pill"><i /> ИИ отключён</span>
      </header>

      <div className="agent-workspace-grid">
        <section className="agent-workspace-card">
          <div className="workspace-card-heading"><span>01</span><div><h2>{screen.inputLabel}</h2><p>Выберите локальную задачу и документы для предпросмотра.</p></div></div>
          {loading ? <p className="agent-inline-message">Загружаю список задач и документов…</p> : (
            <div className="agent-input-form">
              <label className="agent-field-label" htmlFor="agent-task">Задача агента</label>
              <select id="agent-task" value={taskCode} onChange={(event) => { setTaskCode(event.target.value); setSelectedIds([]); setPreview(null); }}>
                {tasks.map((item) => <option key={item.code} value={item.code}>{item.title}</option>)}
              </select>
              {task && <p className="agent-task-purpose">{task.purpose}</p>}

              <div className="agent-document-picker">
                <div className="agent-picker-heading"><strong>Документы</strong><span>{selectedIds.length} из 5 выбрано</span></div>
                <form className="agent-document-search" onSubmit={submitDocumentSearch}>
                  <input aria-label="Поиск документов библиотеки" value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="Найти по имени…" />
                  <button type="submit">Найти</button>
                </form>
                {loadingDocuments && <p className="agent-inline-message">Загружаю документы…</p>}
                {selectableDocuments.length === 0 ? (
                  <p className="agent-inline-message">Подходящих для этой задачи документов по текущему поиску не найдено.</p>
                ) : selectableDocuments.map((document) => (
                  <label className="agent-document-option" key={document.id}>
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(document.id)}
                      disabled={!selectedIds.includes(document.id) && selectedIds.length >= 5}
                      onChange={() => toggleDocument(document.id)}
                    />
                    <span className="agent-document-name"><strong>{document.name}</strong><small>{document.type} · {formatBytes(document.sizeBytes)}</small></span>
                  </label>
                ))}
                {documents.length < documentTotal && (
                  <button className="agent-load-more" type="button" disabled={loadingDocuments} onClick={() => setDocumentOffset((current) => current + 200)}>
                    Показать ещё документы
                  </button>
                )}
              </div>

              <label className="agent-field-label" htmlFor="agent-instruction">Дополнительная инструкция</label>
              <textarea id="agent-instruction" maxLength={10_000} rows={4} value={instruction} onChange={(event) => { setInstruction(event.target.value); setPreview(null); }} placeholder="Укажите, на что обратить внимание…" />
              <button className="primary-button" type="button" disabled={working || loading || !task || selectedIds.length === 0} onClick={handlePreview}>
                {working ? "Подготавливаю…" : "Сформировать локальный предпросмотр"}
              </button>
            </div>
          )}
        </section>

        <section className="agent-workspace-card task-card">
          <div className="workspace-card-heading"><span>02</span><div><h2>Что сможет этот агент</h2><p>Разрешённые задачи модуля</p></div></div>
          <ul className="planned-task-list">
            {tasks.length ? tasks.map((item) => <li key={item.code}><span aria-hidden="true">✓</span>{item.title}</li>) : screen.plannedTasks.map((item) => <li key={item}><span aria-hidden="true">✓</span>{item}</li>)}
          </ul>
          <div className="agent-result-preview">
            <span className="eyebrow">РЕЗУЛЬТАТ РАБОТЫ</span>
            <strong>{screen.resultLabel}</strong>
            <p>{screen.resultDescription}</p>
          </div>
        </section>
      </div>

      {error && <div className="agent-error" role="alert">{error}</div>}
      {preview && (
        <section className="agent-workspace-card agent-preview-card" aria-labelledby="agent-preview-title">
          <div className="workspace-card-heading"><span>03</span><div><h2 id="agent-preview-title">Предпросмотр исходных данных</h2><p>{preview.payloadCharacters.toLocaleString("ru-RU")} символов. Содержимое остаётся на этом компьютере.</p></div></div>
          <ul className="agent-preview-sources">
            {preview.sources.map((source) => <li key={source.id}><strong>{source.name}</strong><span>{source.category} · извлечено символов: {source.text.length.toLocaleString("ru-RU")}</span></li>)}
          </ul>
          <pre className="agent-preview-text">{preview.payloadPreview}</pre>
          <p className="agent-preview-footnote">Это локальный предпросмотр. Он не отправлялся в ИИ и не сохранялся в базе данных.</p>
        </section>
      )}

      <section className="agent-history-card" aria-labelledby="agent-history-title">
        <div className="workspace-card-heading"><span>04</span><div><h2 id="agent-history-title">Недавняя история</h2><p>Сохраняются только агент, задача, время и число источников.</p></div></div>
        {history.length === 0 ? <p className="agent-inline-message">История появится после первого локального предпросмотра.</p> : (
          <ul className="agent-history-list">
            {history.map((entry) => <li key={entry.id}>
              <span><strong>{agentNames[entry.agentId] ?? entry.agentId}</strong><small>{taskNames[entry.taskCode] ?? entry.taskCode} · {entry.sourceCount} {pluralDocuments(entry.sourceCount)}</small></span>
              <time dateTime={entry.createdAt}>{formatDate(entry.createdAt)}</time>
            </li>)}
          </ul>
        )}
      </section>

      <div className="agent-privacy-note" role="note">
        <span aria-hidden="true">⌑</span>
        <div><strong>Предпросмотр выполняется локально</strong><p>Извлекается текст DOCX и текстовых PDF, сохранённые значения XLSX и текст слайдов PPTX. Формулы не вычисляются. Сканированные PDF и изображения пока не распознаются. ИИ-вызовов и передачи данных нет.</p></div>
      </div>
    </section>
  );
}

const agentNames: Record<string, string> = {
  "document-management": "Документооборот",
  "business-correspondence": "Деловая переписка",
  "excel-analytics": "Excel-аналитика",
  "powerpoint-presentations": "Презентации PowerPoint",
};

const taskNames: Record<string, string> = {
  "prepare-from-template": "Подготовка документа по шаблону",
  "consolidate-files": "Собрать сведения из файлов",
  "check-completeness": "Проверка комплектности",
  "draft-letter": "Составить черновик письма",
  "draft-reply": "Подготовить ответ",
  "draft-cover-note": "Сформировать сопроводительный текст",
  "summarize-workbook": "Сделать сводку по таблице",
  "compare-periods": "Сравнить показатели и периоды",
  "report-findings": "Подготовить выводы для отчёта",
  "outline-slides": "Составить план слайдов",
  "draft-speaker-notes": "Подготовить заметки докладчика",
  "draft-presentation": "Собрать презентацию",
};

function pluralDocuments(count: number): string {
  if (count === 1) return "документ";
  if (count >= 2 && count <= 4) return "документа";
  return "документов";
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}
