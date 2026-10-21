import type { AgentDescriptor } from "../platform/localApi";
import { definitions } from "./registry";

export default function AgentWorkspace({ agent }: { agent: AgentDescriptor }) {
  const screen = definitions[agent.id];

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

  return (
    <section className="agent-workspace">
      <header className="agent-page-heading">
        <span className={`agent-workspace-symbol agent-color-${screen.id}`} aria-hidden="true">{screen.symbol}</span>
        <div>
          <span className="eyebrow">ПОДГОТОВЛЕННЫЙ МОДУЛЬ</span>
          <h1>{agent.title}</h1>
          <p>{screen.intro}</p>
        </div>
        <span className="agent-status-pill"><i /> ИИ отключён</span>
      </header>

      <div className="agent-workspace-grid">
        <section className="agent-workspace-card">
          <div className="workspace-card-heading"><span>01</span><div><h2>{screen.inputLabel}</h2><p>{screen.inputDescription}</p></div></div>
          <div className="agent-empty-stage">
            <span className="empty-stage-icon" aria-hidden="true">＋</span>
            <strong>Рабочая область подготовлена</strong>
            <p>Выбор данных и выполнение задач станут доступны на следующем этапе.</p>
            <button type="button" className="primary-button" disabled>Создать задачу</button>
          </div>
        </section>

        <section className="agent-workspace-card task-card">
          <div className="workspace-card-heading"><span>02</span><div><h2>Что сможет этот агент</h2><p>Планируемые задачи модуля</p></div></div>
          <ul className="planned-task-list">
            {screen.plannedTasks.map((task) => <li key={task}><span aria-hidden="true">✓</span>{task}</li>)}
          </ul>
          <div className="agent-result-preview">
            <span className="eyebrow">РЕЗУЛЬТАТ РАБОТЫ</span>
            <strong>{screen.resultLabel}</strong>
            <p>{screen.resultDescription}</p>
          </div>
        </section>
      </div>

      <div className="agent-privacy-note" role="note">
        <span aria-hidden="true">⌑</span>
        <div><strong>Данные не передаются внешним сервисам</strong><p>На этом этапе нет ИИ-вызовов и обработки документов. Любая будущая передача данных потребует отдельного согласия.</p></div>
      </div>
    </section>
  );
}
