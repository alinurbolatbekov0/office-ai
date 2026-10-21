import { useEffect, useMemo, useState } from "react";

import { definitions } from "./registry";
import {
  createAgentTaskPreview,
  getAgentTasks,
  getDocuments,
  type AgentTask,
  type AgentTaskPreview,
  type LibraryDocument,
} from "../platform/localApi";
import type { RuntimeConfig } from "../platform/desktopBridge";
import type { AgentDescriptor } from "../platform/localApi";

const categoryDocumentTypes: Record<string, LibraryDocument["type"][]> = {
  document_text: ["DOCX"],
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
  const [instruction, setInstruction] = useState("");
  const [preview, setPreview] = useState<AgentTaskPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setTasks([]);
    setDocuments([]);
    setTaskCode("");
    setSelectedIds([]);
    setInstruction("");
    setPreview(null);
    if (!runtimeConfig) {
      setLoading(false);
      return;
    }
    Promise.all([getAgentTasks(runtimeConfig, agent.id), getDocuments(runtimeConfig)])
      .then(([nextTasks, response]) => {
        if (!active) return;
        setTasks(nextTasks);
        setTaskCode(nextTasks[0]?.code || "");
        setDocuments(response.documents);
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

  async function handlePreview() {
    if (!runtimeConfig || !task || selectedIds.length === 0) return;
    setWorking(true);
    setError(null);
    setPreview(null);
    try {
      setPreview(await createAgentTaskPreview(runtimeConfig, agent.id, task.code, selectedIds, instruction));
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
                {selectableDocuments.length === 0 ? (
                  <p className="agent-inline-message">Подходящих DOCX, XLSX или PPTX файлов в библиотеке пока нет.</p>
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

      <div className="agent-privacy-note" role="note">
        <span aria-hidden="true">⌑</span>
        <div><strong>Предпросмотр выполняется локально</strong><p>Извлекается текст DOCX, сохранённые значения XLSX и текст слайдов PPTX. Формулы не вычисляются. PDF и изображения пока не обрабатываются. ИИ-вызовов и передачи данных нет.</p></div>
      </div>
    </section>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}
