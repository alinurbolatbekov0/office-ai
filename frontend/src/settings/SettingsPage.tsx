import type { AppSettings, OperationEvent } from "../platform/localApi";

interface SettingsPageProps {
  settings: AppSettings;
  operations: OperationEvent[];
  savingKey: keyof AppSettings | null;
  saveMessage: string | null;
  onSave: (key: keyof AppSettings, value: AppSettings[keyof AppSettings]) => void;
}

export default function SettingsPage({
  settings,
  operations,
  savingKey,
  saveMessage,
  onSave,
}: SettingsPageProps) {
  function save(key: keyof AppSettings, value: AppSettings[keyof AppSettings]) {
    onSave(key, value);
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

      <section className="settings-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon shield">✓</span>
          <div><h2>Подтверждения</h2><p>Защитные настройки для будущих операций.</p></div>
        </div>
        <label className="setting-row toggle-row">
          <span><strong>Подтверждать опасные действия</strong><small>Запрашивать подтверждение перед удалением и восстановлением.</small></span>
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

function operationTitle(event: OperationEvent): string {
  if (event.operationCode === "app_started") return "Приложение запущено";
  if (event.operationCode === "setting_updated") return "Настройка сохранена";
  if (event.operationCode === "document_uploaded") return "Документ добавлен";
  if (event.operationCode === "document_duplicate_detected") return "Обнаружен дубликат";
  if (event.operationCode === "document_upload_rejected") return "Загрузка отклонена";
  return "Операция";
}

function operationDescription(event: OperationEvent): string {
  if (event.entityId === "theme") return "Изменена цветовая тема";
  if (event.entityId === "confirm_destructive_actions") return "Обновлено подтверждение опасных действий";
  if (event.operationCode === "document_uploaded") return "Файл добавлен в локальную библиотеку";
  if (event.operationCode === "document_duplicate_detected") return "Байты совпадают с файлом в библиотеке";
  if (event.operationCode === "document_upload_rejected") return "Тип, содержимое или размер не прошли проверку";
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
