import { useEffect, useMemo, useState, type FormEvent } from "react";

import { definitions } from "./registry";
import {
  cancelAgentTransfer,
  createAgentTaskPreview,
  downloadAgentTaskResult,
  executeAgentTransfer,
  getAgentTasks,
  getAgentTaskHistory,
  getAgentTaskResult,
  getAIProviderStatus,
  getDocuments,
  prepareAgentTransfer,
  type AgentTask,
  type AgentTaskPreview,
  type AgentTaskHistoryEntry,
  type AgentTransferDisclosure,
  type AgentTaskResult,
  type AIProviderStatus,
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
  const [aiStatus, setAiStatus] = useState<AIProviderStatus | null>(null);
  const [disclosure, setDisclosure] = useState<AgentTransferDisclosure | null>(null);
  const [transferConfirmed, setTransferConfirmed] = useState(false);
  const [taskResult, setTaskResult] = useState<AgentTaskResult | null>(null);
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
    setDisclosure(null);
    setTransferConfirmed(false);
    setTaskResult(null);
    if (!runtimeConfig) {
      setLoading(false);
      return;
    }
    Promise.all([getAgentTasks(runtimeConfig, agent.id), getAgentTaskHistory(runtimeConfig), getAIProviderStatus(runtimeConfig)])
      .then(([nextTasks, taskHistory, nextAiStatus]) => {
        if (!active) return;
        setTasks(nextTasks);
        setTaskCode(nextTasks[0]?.code || "");
        setHistory(taskHistory);
        setAiStatus(nextAiStatus);
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
    setDisclosure(null);
    setTransferConfirmed(false);
    setTaskResult(null);
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
    setDisclosure(null);
    setTransferConfirmed(false);
    setTaskResult(null);
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

  async function handlePrepareTransfer() {
    if (!runtimeConfig || !task || !preview?.historyEntry || !aiStatus?.configured) return;
    setWorking(true);
    setError(null);
    try {
      const proposal = await prepareAgentTransfer(runtimeConfig, agent.id, task.code, selectedIds, instruction, preview.historyEntry.id);
      setDisclosure(proposal);
      setTransferConfirmed(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось подготовить запрос для проверки.");
    } finally { setWorking(false); }
  }

  async function handleTransfer() {
    if (!runtimeConfig || !disclosure || !transferConfirmed) return;
    setWorking(true);
    setError(null);
    try {
      const response = await executeAgentTransfer(runtimeConfig, disclosure.requestId, true);
      if (response.cancelled || !response.historyId) throw new Error("Запрос был отменён или не вернул результат.");
      setTaskResult(await getAgentTaskResult(runtimeConfig, response.historyId));
      setHistory((current) => current.map((entry) => entry.id === response.historyId ? { ...entry, hasResult: true } : entry));
      setDisclosure(null);
      setTransferConfirmed(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось выполнить запрос. Автоматического повтора не будет.");
    } finally { setWorking(false); }
  }

  async function handleCancelTransfer() {
    if (!runtimeConfig || !disclosure) return;
    setWorking(true);
    try {
      await cancelAgentTransfer(runtimeConfig, disclosure.requestId);
      setDisclosure(null);
      setTransferConfirmed(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось отменить подготовленный запрос.");
    } finally { setWorking(false); }
  }

  async function openSavedResult(historyId: string) {
    if (!runtimeConfig) return;
    setWorking(true);
    setError(null);
    try { setTaskResult(await getAgentTaskResult(runtimeConfig, historyId)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Не удалось открыть сохранённый результат."); }
    finally { setWorking(false); }
  }

  async function downloadSavedResult(historyId: string) {
    if (!runtimeConfig) return;
    setWorking(true);
    setError(null);
    try { await downloadAgentTaskResult(runtimeConfig, historyId); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Не удалось скачать файл результата."); }
    finally { setWorking(false); }
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
        <span className={`agent-status-pill ${aiStatus?.configured ? "ready" : ""}`}><i /> {aiStatus?.configured ? "ИИ доступен по запросу" : "ИИ не настроен"}</span>
      </header>

      <div className="agent-workspace-grid">
        <section className="agent-workspace-card">
          <div className="workspace-card-heading"><span>01</span><div><h2>{screen.inputLabel}</h2><p>Выберите локальную задачу и документы для предпросмотра.</p></div></div>
          {loading ? <p className="agent-inline-message">Загружаю список задач и документов…</p> : (
            <div className="agent-input-form">
              <label className="agent-field-label" htmlFor="agent-task">Задача агента</label>
              <select id="agent-task" value={taskCode} onChange={(event) => { setTaskCode(event.target.value); setSelectedIds([]); setPreview(null); setDisclosure(null); setTransferConfirmed(false); setTaskResult(null); }}>
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
              <textarea id="agent-instruction" maxLength={10_000} rows={4} value={instruction} onChange={(event) => { setInstruction(event.target.value); setPreview(null); setDisclosure(null); setTransferConfirmed(false); setTaskResult(null); }} placeholder="Укажите, на что обратить внимание…" />
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
          <button className="primary-button" type="button" disabled={working || !aiStatus?.configured || !preview.historyEntry} onClick={() => void handlePrepareTransfer()}>
            {working ? "Готовлю карточку передачи…" : "Просмотреть запрос к OpenAI"}
          </button>
          {!aiStatus?.configured && <p className="agent-preview-footnote">Чтобы подготовить запрос, сначала добавьте ключ OpenAI в разделе «Настройки».</p>}
        </section>
      )}

      {disclosure && (
        <section className="agent-workspace-card transfer-card" aria-labelledby="agent-transfer-title">
          <div className="workspace-card-heading"><span>!</span><div><h2 id="agent-transfer-title">Проверьте передачу данных</h2><p>Ниже показан точный текст запроса, который будет отправлен.</p></div></div>
          <div className="transfer-warning" role="note">При подтверждении выбранные данные и инструкция отправятся OpenAI ({disclosure.modelId}) через интернет. Это может повлечь расходы по вашему аккаунту. Параметр запроса просит не сохранять данные, но не отменяет политики обработки и хранения OpenAI.</div>
          <dl className="transfer-meta">
            <div><dt>Назначение</dt><dd>{disclosure.purpose}</dd></div>
            <div><dt>Размер</dt><dd>{formatBytes(disclosure.payloadSizeBytes)} · SHA-256 {disclosure.payloadSha256}</dd></div>
            <div><dt>Истекает</dt><dd>{formatDate(disclosure.expiresAt)}</dd></div>
          </dl>
          <ul className="agent-preview-sources">{disclosure.items.map((item) => <li key={item.id}><strong>{item.name}</strong><span>Категории: {item.categories.join(", ")}</span></li>)}</ul>
          <pre className="agent-preview-text">{disclosure.payloadPreview}</pre>
          <label className="transfer-consent"><input type="checkbox" checked={transferConfirmed} disabled={working} onChange={(event) => setTransferConfirmed(event.target.checked)} /><span>Я проверил(а) точный запрос выше, разрешаю отправить перечисленные данные OpenAI и понимаю, что запрос может быть платным.</span></label>
          <div className="backup-actions"><button className="primary-button" type="button" disabled={working || !transferConfirmed} onClick={() => void handleTransfer()}>{working ? "Ожидайте ответа…" : "Отправить в OpenAI"}</button><button className="secondary-button" type="button" disabled={working} onClick={() => void handleCancelTransfer()}>Отмена</button></div>
        </section>
      )}

      {taskResult && <section className="agent-workspace-card agent-result-card"><div className="workspace-card-heading"><span>✓</span><div><h2>Результат агента</h2><p>{taskResult.modelId} · сохранён локально {formatDate(taskResult.createdAt)}</p></div></div><pre className="agent-preview-text">{taskResult.resultText}</pre><div className="backup-actions"><button className="primary-button" type="button" disabled={working} onClick={() => void downloadSavedResult(taskResult.historyId)}>Скачать как {exportFormatLabel(agent.id)}</button></div></section>}

      <section className="agent-history-card" aria-labelledby="agent-history-title">
        <div className="workspace-card-heading"><span>04</span><div><h2 id="agent-history-title">Недавняя история</h2><p>Сохраняются только агент, задача, время и число источников.</p></div></div>
        {history.length === 0 ? <p className="agent-inline-message">История появится после первого локального предпросмотра.</p> : (
          <ul className="agent-history-list">
            {history.map((entry) => <li key={entry.id}>
              <span><strong>{agentNames[entry.agentId] ?? entry.agentId}</strong><small>{taskNames[entry.taskCode] ?? entry.taskCode} · {entry.sourceCount} {pluralDocuments(entry.sourceCount)}</small></span>
              <time dateTime={entry.createdAt}>{formatDate(entry.createdAt)}</time>
              {entry.hasResult && <button className="text-button" type="button" disabled={working} onClick={() => void openSavedResult(entry.id)}>Открыть результат</button>}
            </li>)}
          </ul>
        )}
      </section>

      <div className="agent-privacy-note" role="note">
        <span aria-hidden="true">⌑</span>
        <div><strong>Данные остаются локально до отдельного подтверждения</strong><p>Извлекается текст DOCX и текстовых PDF, сохранённые значения XLSX и текст слайдов PPTX. Формулы не вычисляются. Сканированные PDF и изображения пока не распознаются. Сетевой запрос невозможен, пока вы не просмотрели точный текст и не подтвердили конкретную передачу.</p></div>
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

function exportFormatLabel(agentId: string): string {
  if (agentId === "excel-analytics") return "XLSX";
  if (agentId === "powerpoint-presentations") return "PPTX";
  return "DOCX";
}
