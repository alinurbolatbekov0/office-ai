import { useEffect, useState, type FormEvent } from "react";
import type { AIProviderStatus, AppSettings, OperationEvent } from "../platform/localApi";
import { createBackup, deleteOpenAIApiKey, getAIProviderStatus, restoreBackup, saveOpenAIApiKey } from "../platform/localApi";
import type { RuntimeConfig } from "../platform/desktopBridge";

interface SettingsPageProps {
  settings: AppSettings;
  operations: OperationEvent[];
  savingKey: keyof AppSettings | null;
  saveMessage: string | null;
  onSave: (key: keyof AppSettings, value: AppSettings[keyof AppSettings]) => void;
  runtimeConfig: RuntimeConfig | null;
  onRestored: () => void;
}

export default function SettingsPage({
  settings,
  operations,
  savingKey,
  saveMessage,
  onSave,
  runtimeConfig,
  onRestored,
}: SettingsPageProps) {
  const [backupBusy, setBackupBusy] = useState(false);
  const [backupMessage, setBackupMessage] = useState<string | null>(null);
  const [aiStatus, setAiStatus] = useState<AIProviderStatus | null>(null);
  const [aiKeyInput, setAiKeyInput] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [aiMessage, setAiMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    if (!runtimeConfig) return;
    getAIProviderStatus(runtimeConfig)
      .then((status) => { if (active) setAiStatus(status); })
      .catch((error: unknown) => {
        if (active) setAiMessage(error instanceof Error ? error.message : "Не удалось проверить настройки OpenAI.");
      });
    return () => { active = false; };
  }, [runtimeConfig]);

  function save(key: keyof AppSettings, value: AppSettings[keyof AppSettings]) {
    onSave(key, value);
  }

  async function handleCreateBackup() {
    if (!runtimeConfig) return;
    setBackupBusy(true);
    setBackupMessage(null);
    try {
      const backup = await createBackup(runtimeConfig);
      setBackupMessage(`Резервная копия создана и сохранена в локальном каталоге backups (${formatBytes(backup.sizeBytes)}).`);
    } catch (error) {
      setBackupMessage(error instanceof Error ? error.message : "Не удалось создать резервную копию.");
    } finally {
      setBackupBusy(false);
    }
  }

  async function handleRestore(file: File | undefined) {
    if (!runtimeConfig || !file) return;
    const confirmed = window.confirm(
      "Восстановление заменит текущую базу Office AI и библиотеку документов данными выбранной резервной копии. Сначала проверьте файл. Продолжить?",
    );
    if (!confirmed) return;
    setBackupBusy(true);
    setBackupMessage(null);
    try {
      await restoreBackup(runtimeConfig, file);
      setBackupMessage("Данные восстановлены. Обновляем приложение…");
      window.setTimeout(onRestored, 600);
    } catch (error) {
      setBackupMessage(error instanceof Error ? error.message : "Не удалось восстановить данные.");
    } finally {
      setBackupBusy(false);
    }
  }

  async function handleSaveAIKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!runtimeConfig || !aiKeyInput.trim()) return;
    setAiBusy(true);
    setAiMessage(null);
    try {
      await saveOpenAIApiKey(runtimeConfig, aiKeyInput);
      setAiStatus((current) => current ? { ...current, configured: true } : current);
      setAiKeyInput("");
      setAiMessage("Ключ сохранён в защищённом хранилище Windows.");
    } catch (error) {
      setAiMessage(error instanceof Error ? error.message : "Не удалось сохранить ключ OpenAI.");
    } finally {
      setAiBusy(false);
    }
  }

  async function handleDeleteAIKey() {
    if (!runtimeConfig || !window.confirm("Удалить сохранённый ключ OpenAI из защищённого хранилища Windows?")) return;
    setAiBusy(true);
    setAiMessage(null);
    try {
      await deleteOpenAIApiKey(runtimeConfig);
      setAiStatus((current) => current ? { ...current, configured: false } : current);
      setAiMessage("Ключ удалён. Передача данных агентами теперь недоступна.");
    } catch (error) {
      setAiMessage(error instanceof Error ? error.message : "Не удалось удалить ключ OpenAI.");
    } finally {
      setAiBusy(false);
    }
  }

  return (
    <div className="settings-page">
      <div className="page-title-block">
        <span className="eyebrow">ПРИЛОЖЕНИЕ</span>
        <h1>Настройки</h1>
        <p>Параметры и журнал операций хранятся локально.</p>
      </div>

      <section className="settings-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon">⚙</span>
          <div><h2>Внешний вид</h2><p>Настройте отображение приложения.</p></div>
        </div>
        <label className="setting-row">
          <span><strong>Цветовая тема</strong><small>Изменение применяется сразу после сохранения.</small></span>
          <select
            aria-label="Цветовая тема"
            disabled={savingKey === "theme"}
            onChange={(event) => save("theme", event.target.value as AppSettings["theme"])}
            value={settings.theme}
          >
            <option value="light">Светлая</option>
            <option value="dark">Тёмная</option>
          </select>
        </label>
      </section>

      <section className="settings-card backup-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon journal">↻</span>
          <div><h2>Резервное копирование</h2><p>Копия включает базу, настройки, журнал и библиотеку документов.</p></div>
        </div>
        <div className="backup-warning" role="note">
          Архив хранится без шифрования. Внутренняя копия создаётся в `%LOCALAPPDATA%\OfficeAI\backups`, затем приложение предлагает сохранить её через загрузку файла.
        </div>
        <div className="backup-actions">
          <button className="primary-button" disabled={!runtimeConfig || backupBusy} onClick={handleCreateBackup} type="button">
            {backupBusy ? "Выполняется…" : "Создать и скачать копию"}
          </button>
          <label className={`secondary-button restore-file-button ${!runtimeConfig || backupBusy ? "disabled" : ""}`}>
            Выбрать копию для восстановления
            <input
              accept=".zip,application/zip"
              disabled={!runtimeConfig || backupBusy}
              onChange={(event) => {
                const file = event.currentTarget.files?.[0];
                event.currentTarget.value = "";
                void handleRestore(file);
              }}
              type="file"
            />
          </label>
        </div>
        {backupMessage && (
          <div className={`settings-feedback backup-feedback ${backupMessage.startsWith("Не удалось") ? "error" : ""}`} role="status">
            {backupMessage}
          </div>
        )}
      </section>

      <section className="settings-card ai-provider-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon shield">AI</span>
          <div><h2>Подключение OpenAI</h2><p>Модель для запросов агентов: {aiStatus?.modelId ?? "gpt-4.1-mini"}</p></div>
        </div>
        <div className="backup-warning" role="note">
          Ключ хранится в Credential Manager Windows и не попадает в базу, журнал или резервную копию. Само сохранение ключа не отправляет документы. Каждый запрос показывает файлы и точное содержимое и требует отдельного подтверждения. Запрос может тарифицироваться OpenAI.
        </div>
        {!aiStatus?.providerAvailable && (
          <p className="settings-feedback error">Защищённое хранилище ключей доступно в установленной версии Office AI для Windows.</p>
        )}
        <form className="ai-key-form" onSubmit={(event) => void handleSaveAIKey(event)}>
          <label className="setting-row ai-key-row">
            <span><strong>Ключ API OpenAI</strong><small>{aiStatus?.configured ? "Ключ сохранён; его значение нельзя посмотреть из приложения." : "Ключ не задан; реальные запросы отключены."}</small></span>
            <input
              aria-label="Ключ API OpenAI"
              autoComplete="off"
              disabled={!runtimeConfig || !aiStatus?.providerAvailable || aiBusy}
              onChange={(event) => setAiKeyInput(event.target.value)}
              spellCheck={false}
              type="password"
              value={aiKeyInput}
            />
          </label>
          <div className="backup-actions">
            <button className="primary-button" disabled={!runtimeConfig || !aiStatus?.providerAvailable || aiBusy || !aiKeyInput.trim()} type="submit">
              {aiBusy ? "Сохраняю…" : "Сохранить ключ локально"}
            </button>
            {aiStatus?.configured && (
              <button className="secondary-button" disabled={aiBusy} onClick={() => void handleDeleteAIKey()} type="button">
                Удалить ключ
              </button>
            )}
          </div>
        </form>
        {aiMessage && <div className={`settings-feedback ${aiMessage.startsWith("Не удалось") ? "error" : ""}`} role="status">{aiMessage}</div>}
      </section>

      <section className="settings-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon shield">✓</span>
          <div><h2>Подтверждения</h2><p>Защитные настройки для будущих операций.</p></div>
        </div>
        <label className="setting-row toggle-row">
          <span><strong>Подтверждать опасные действия</strong><small>Восстановление всегда требует отдельного подтверждения.</small></span>
          <input
            checked={settings.confirm_destructive_actions}
            disabled={savingKey === "confirm_destructive_actions"}
            onChange={(event) => save("confirm_destructive_actions", event.target.checked)}
            type="checkbox"
          />
        </label>
      </section>

      {saveMessage && (
        <div className={`settings-feedback ${saveMessage.startsWith("Не удалось") || saveMessage.includes("кодом") ? "error" : ""}`} role="status">
          {saveMessage}
        </div>
      )}

      <section className="settings-card operations-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon journal">≡</span>
          <div><h2>Журнал операций</h2><p>Последние действия в приложении.</p></div>
        </div>
        {operations.length === 0 ? (
          <div className="empty-operations">Операций пока нет.</div>
        ) : (
          <ol className="operation-list">
            {operations.map((operation) => (
              <li className="operation-row" key={operation.id}>
                <span className={`operation-status ${operation.outcome}`} aria-hidden="true" />
                <span className="operation-copy">
                  <strong>{operationTitle(operation)}</strong>
                  <small>{operationDescription(operation)}</small>
                </span>
                <time dateTime={operation.occurredAt}>{formatDate(operation.occurredAt)}</time>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}

function formatBytes(size: number): string {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} КиБ`;
  return `${(size / (1024 * 1024)).toFixed(1)} МиБ`;
}

function operationTitle(event: OperationEvent): string {
  if (event.operationCode === "app_started") return "Приложение запущено";
  if (event.operationCode === "setting_updated") return "Настройка сохранена";
  if (event.operationCode === "document_uploaded") return "Документ добавлен";
  if (event.operationCode === "document_duplicate_detected") return "Обнаружен дубликат";
  if (event.operationCode === "document_upload_rejected") return "Загрузка отклонена";
  if (event.operationCode === "backup_created") return event.outcome === "success" ? "Резервная копия создана" : "Резервная копия не создана";
  if (event.operationCode === "backup_restored") return "Резервная копия восстановлена";
  if (event.operationCode === "backup_restore_rejected") return "Восстановление отклонено";
  if (event.operationCode === "agent_preview_created") return "Подготовлены данные агента";
  return "Операция";
}

function operationDescription(event: OperationEvent): string {
  if (event.entityId === "theme") return "Изменена цветовая тема";
  if (event.entityId === "confirm_destructive_actions") return "Обновлено подтверждение опасных действий";
  if (event.operationCode === "document_uploaded") return "Файл добавлен в локальную библиотеку";
  if (event.operationCode === "document_duplicate_detected") return "Байты совпадают с файлом в библиотеке";
  if (event.operationCode === "document_upload_rejected") return "Тип, содержимое или размер не прошли проверку";
  if (event.operationCode === "backup_created") return event.outcome === "success" ? "Создан локальный архив библиотеки, настроек и журнала" : "Не удалось создать локальный архив";
  if (event.operationCode === "backup_restored") return "Данные восстановлены из локальной резервной копии";
  if (event.operationCode === "backup_restore_rejected") return "Архив не прошёл проверку целостности";
  if (event.operationCode === "agent_preview_created") return "Локальный предпросмотр; данные не отправлялись";
  return event.outcome === "success" ? "Выполнено успешно" : "Не выполнено";
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}
