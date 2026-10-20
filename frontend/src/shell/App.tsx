import { useEffect, useMemo, useState } from "react";

import { getRuntimeConfig } from "../platform/desktopBridge";
import {
  getAgents,
  getHealth,
  getOperations,
  getSettings,
  saveSetting,
  type AgentDescriptor,
  type AppSettings,
  type HealthStatus,
  type OperationEvent,
} from "../platform/localApi";
import SettingsPage from "../settings/SettingsPage";

type RouteId = "home" | "library" | "settings" | string;

const baseNavigation = [
  { id: "home", label: "Главная", icon: "⌂" },
  { id: "library", label: "Библиотека документов", icon: "▤" },
];

const footerNavigation = [{ id: "settings", label: "Настройки", icon: "⚙" }];

function App() {
  const [route, setRoute] = useState<RouteId>("home");
  const [agents, setAgents] = useState<AgentDescriptor[]>([]);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [runtimeConfig, setRuntimeConfig] = useState<Awaited<ReturnType<typeof getRuntimeConfig>> | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [operations, setOperations] = useState<OperationEvent[]>([]);
  const [savingKey, setSavingKey] = useState<keyof AppSettings | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getRuntimeConfig()
      .then((config) => {
        setRuntimeConfig(config);
        return Promise.all([getHealth(config), getAgents(config), getSettings(config), getOperations(config)]);
      })
      .then(([nextHealth, nextAgents, nextSettings, nextOperations]) => {
        if (!active) return;
        setHealth(nextHealth);
        setAgents(nextAgents);
        setSettings(nextSettings);
        setOperations(nextOperations);
      })
      .catch((error: unknown) => {
        if (active) {
          setConnectionError(error instanceof Error ? error.message : "Не удалось связаться с backend.");
        }
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = settings?.theme ?? "light";
  }, [settings?.theme]);

  async function handleSaveSetting(key: keyof AppSettings, value: AppSettings[keyof AppSettings]) {
    if (!runtimeConfig) return;
    setSavingKey(key);
    setSaveMessage(null);
    try {
      const nextSettings = await saveSetting(runtimeConfig, key, value);
      setSettings(nextSettings);
      setOperations(await getOperations(runtimeConfig));
      setSaveMessage("Настройка сохранена.");
    } catch (error) {
      setSaveMessage(error instanceof Error ? error.message : "Не удалось сохранить настройку.");
    } finally {
      setSavingKey(null);
    }
  }

  const activeAgent = useMemo(() => agents.find((agent) => agent.id === route), [agents, route]);
  const allNavigation = [...baseNavigation, ...agents.map((agent) => ({ id: agent.id, label: agent.title, icon: "✦" }))];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark">O</div>
          <div>
            <strong>Office AI</strong>
            <span>Локальный помощник</span>
          </div>
        </div>

        <nav className="primary-navigation" aria-label="Основная навигация">
          <span className="nav-caption">РАБОЧЕЕ ПРОСТРАНСТВО</span>
          {allNavigation.map((item) => (
            <button
              aria-current={route === item.id ? "page" : undefined}
              className={`nav-item ${route === item.id ? "active" : ""}`}
              key={item.id}
              onClick={() => setRoute(item.id)}
              type="button"
            >
              <span className="nav-icon" aria-hidden="true">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>

        <div className="sidebar-spacer" />
        <button
          aria-current={route === "settings" ? "page" : undefined}
          className={`nav-item ${route === "settings" ? "active" : ""}`}
          onClick={() => setRoute("settings")}
          type="button"
        >
          <span className="nav-icon" aria-hidden="true">{footerNavigation[0].icon}</span>
          {footerNavigation[0].label}
        </button>
        <div className="local-badge"><span /> Данные остаются на этом компьютере</div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb">Office AI <span>/</span> {getRouteTitle(route, activeAgent)}</div>
          <div className={`connection-state ${health ? "connected" : ""}`}>
            <span className="connection-dot" />
            {health ? "Локально подключено" : "Запуск каркаса"}
          </div>
        </header>

        {connectionError && (
          <div className="connection-error" role="status">
            Backend пока не подключён: {connectionError}
          </div>
        )}

        <div className="page-content">
          {route === "home" && <HomePage agents={agents} health={health} onNavigate={setRoute} />}
          {route === "library" && <PlaceholderPage title="Библиотека документов" icon="▤" />}
          {route === "settings" && (
            settings ? (
              <SettingsPage
                operations={operations}
                saveMessage={saveMessage}
                savingKey={savingKey}
                settings={settings}
                onSave={handleSaveSetting}
              />
            ) : <PlaceholderPage title="Настройки" icon="⚙" />
          )}
          {activeAgent && <AgentPage agent={activeAgent} />}
        </div>
      </main>
    </div>
  );
}

function getRouteTitle(route: RouteId, activeAgent?: AgentDescriptor): string {
  if (activeAgent) return activeAgent.title;
  if (route === "library") return "Библиотека документов";
  if (route === "settings") return "Настройки";
  return "Главная";
}

function HomePage({
  agents,
  health,
  onNavigate,
}: {
  agents: AgentDescriptor[];
  health: HealthStatus | null;
  onNavigate: (id: RouteId) => void;
}) {
  return (
    <>
      <section className="hero-panel">
        <div className="hero-copy">
          <span className="eyebrow">ВАШЕ РАБОЧЕЕ ПРОСТРАНСТВО</span>
          <h1>Работайте с документами<br />в одном месте</h1>
          <p>Office AI объединит локальную библиотеку и специализированных помощников для повседневных офисных задач.</p>
          <button className="primary-button" onClick={() => onNavigate("library")} type="button">
            Открыть библиотеку <span aria-hidden="true">→</span>
          </button>
        </div>
        <div className="hero-art" aria-hidden="true">
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <div className="hero-document hero-document-back">PPT</div>
          <div className="hero-document hero-document-front"><span>AI</span><i /><i /><i /></div>
          <div className="sparkle sparkle-one">✦</div>
          <div className="sparkle sparkle-two">✧</div>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <div><span className="eyebrow">СПЕЦИАЛИЗИРОВАННЫЕ ПОМОЩНИКИ</span><h2>Выберите агента</h2></div>
          <span className="section-note">Функции будут подключаться поэтапно</span>
        </div>
        <div className="agent-grid">
          {agents.map((agent, index) => (
            <button className="agent-card" key={agent.id} onClick={() => onNavigate(agent.id)} type="button">
              <span className={`agent-symbol agent-symbol-${index + 1}`}>{agentIcon(index)}</span>
              <span className="agent-card-copy"><strong>{agent.title}</strong><span>{agent.description}</span></span>
              <span className="card-arrow" aria-hidden="true">↗</span>
              <span className="prepared-label">Скоро</span>
            </button>
          ))}
          {agents.length === 0 && <div className="loading-card">Получаем список агентов…</div>}
        </div>
      </section>

      <section className="workspace-status">
        <div className="status-icon">⌘</div>
        <div><strong>Локальное рабочее пространство</strong><span>Ваши данные будут храниться на этом компьютере.</span></div>
        <div className="status-separator" />
        <div className="status-detail"><span>Состояние приложения</span><strong>{health ? "Готово к настройке" : "Каркас запускается"}</strong></div>
      </section>
    </>
  );
}

function AgentPage({ agent }: { agent: AgentDescriptor }) {
  return (
    <section className="placeholder-panel agent-placeholder">
      <span className="placeholder-symbol">✦</span>
      <span className="eyebrow">ПОДГОТОВЛЕННЫЙ МОДУЛЬ</span>
      <h1>{agent.title}</h1>
      <p>{agent.description}</p>
      <div className="availability-note"><span /> Интерфейс агента подготовлен. Выполнение задач пока не подключено.</div>
    </section>
  );
}

function PlaceholderPage({ title, icon }: { title: string; icon: string }) {
  return (
    <section className="placeholder-panel">
      <span className="placeholder-symbol">{icon}</span>
      <span className="eyebrow">КАРКАС ПРИЛОЖЕНИЯ</span>
      <h1>{title}</h1>
      <p>Этот раздел появится на следующем этапе разработки.</p>
      <div className="availability-note"><span /> Данные и операции пока не подключены.</div>
    </section>
  );
}

function agentIcon(index: number): string {
  return ["▤", "✉", "▥", "▰"][index] ?? "✦";
}

export default App;
