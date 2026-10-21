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
import DocumentsPage from "../library/DocumentsPage";
import AgentWorkspace from "../agents/AgentWorkspace";

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
  const [startupLoading, setStartupLoading] = useState(true);
  const [startupAttempt, setStartupAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setStartupLoading(true);
    setConnectionError(null);
    setHealth(null);
    setAgents([]);
    getRuntimeConfig()
      .then((config) => {
        setRuntimeConfig(config);
        return Promise.allSettled([getHealth(config), getAgents(config), getSettings(config), getOperations(config)] as const);
      })
      .then((results) => {
        if (!active) return;
        const [healthResult, agentsResult, settingsResult, operationsResult] = results;
        const errors: string[] = [];
        if (healthResult.status === "fulfilled") setHealth(healthResult.value);
        else errors.push(`проверка backend: ${errorMessage(healthResult.reason)}`);
        if (agentsResult.status === "fulfilled") setAgents(agentsResult.value);
        else errors.push(`список помощников: ${errorMessage(agentsResult.reason)}`);
        if (settingsResult.status === "fulfilled") setSettings(settingsResult.value);
        else errors.push(`настройки: ${errorMessage(settingsResult.reason)}`);
        if (operationsResult.status === "fulfilled") setOperations(operationsResult.value);
        else errors.push(`журнал операций: ${errorMessage(operationsResult.reason)}`);
        if (errors.length) setConnectionError(errors.join("; "));
      })
      .catch((error: unknown) => {
        if (active) {
          setConnectionError(errorMessage(error));
        }
      })
      .finally(() => {
        if (active) setStartupLoading(false);
      });

    return () => {
      active = false;
    };
  }, [startupAttempt]);

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
    <div className="app-shell" data-backend-ready={health ? "true" : startupLoading ? "loading" : "false"}>
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
              title={item.label}
              aria-label={item.label}
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
          title={footerNavigation[0].label}
          aria-label={footerNavigation[0].label}
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
            {health ? "Backend подключён" : startupLoading ? "Подключение…" : "Backend недоступен"}
          </div>
        </header>

        {connectionError && (
          <div className="connection-error" role="status">
            Backend или отдельный раздел не ответил: {connectionError}{" "}
            <button className="inline-retry-button" onClick={() => setStartupAttempt((attempt) => attempt + 1)} type="button">Повторить</button>
          </div>
        )}

        <div className="page-content">
          {route === "home" && <HomePage agents={agents} health={health} loading={startupLoading} error={connectionError} onRetry={() => setStartupAttempt((attempt) => attempt + 1)} onNavigate={setRoute} />}
          {route === "library" && <DocumentsPage runtimeConfig={runtimeConfig} />}
          {route === "settings" && (
            settings && health ? (
              <SettingsPage
                operations={operations}
                runtimeConfig={runtimeConfig}
                saveMessage={saveMessage}
                savingKey={savingKey}
                settings={settings}
                onSave={handleSaveSetting}
                onRestored={() => window.location.reload()}
              />
            ) : <StatusPage title="Настройки" loading={startupLoading} onRetry={() => setStartupAttempt((attempt) => attempt + 1)} />
          )}
          {activeAgent && <AgentWorkspace agent={activeAgent} runtimeConfig={runtimeConfig} />}
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
  loading,
  error,
  onRetry,
  onNavigate,
}: {
  agents: AgentDescriptor[];
  health: HealthStatus | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onNavigate: (id: RouteId) => void;
}) {
  return (
    <>
      <section className="hero-panel">
        <div className="hero-copy">
          <span className="eyebrow">ВАШЕ РАБОЧЕЕ ПРОСТРАНСТВО</span>
          <h1>Документы и помощники<br />в одном рабочем окне</h1>
          <p>Храните файлы локально, просматривайте содержимое и готовьте черновики. Передача выбранных данных OpenAI выполняется только после отдельного подтверждения.</p>
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
          <span className="section-note">{health ? "Подключены к локальному backend" : loading ? "Подключение к локальному backend…" : "Локальный backend недоступен"}</span>
        </div>
        <div className="agent-grid">
          {agents.map((agent, index) => (
            <button className="agent-card" key={agent.id} onClick={() => onNavigate(agent.id)} type="button">
              <span className={`agent-symbol agent-symbol-${index + 1}`}>{agentIcon(index)}</span>
              <span className="agent-card-copy"><strong>{agent.title}</strong><span>{agent.description}</span></span>
              <span className="card-arrow" aria-hidden="true">↗</span>
              <span className="prepared-label">Открыть</span>
            </button>
          ))}
          {agents.length === 0 && (
            <div className="loading-card">
              {loading ? "Загружаем помощников из локального backend…" : error ? "Не удалось загрузить список помощников. Проверьте подключение и повторите попытку." : "Список помощников пуст."}
              {!loading && error && <button className="inline-retry-button" onClick={onRetry} type="button">Повторить</button>}
            </div>
          )}
        </div>
      </section>

      <section className="workspace-status">
        <div className="status-icon">⌘</div>
        <div><strong>Локальное рабочее пространство</strong><span>Документы, настройки и журнал хранятся на этом компьютере.</span></div>
        <div className="status-separator" />
        <div className="status-detail"><span>Состояние backend</span><strong>{health ? "Подключён" : loading ? "Подключаемся…" : "Недоступен"}</strong></div>
      </section>
    </>
  );
}

function StatusPage({ title, loading, onRetry }: { title: string; loading: boolean; onRetry: () => void }) {
  return (
    <section className="placeholder-panel">
      <span className="eyebrow">ЛОКАЛЬНЫЙ BACKEND</span>
      <h1>{title}</h1>
      <p>{loading ? "Подключаем настройки и журнал операций…" : "Не удалось получить данные этого раздела. Попробуйте снова."}</p>
      <button className="primary-button" disabled={loading} onClick={onRetry} type="button">Повторить подключение</button>
    </section>
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "неизвестная ошибка";
}

function agentIcon(index: number): string {
  return ["▤", "✉", "▥", "▰"][index] ?? "✦";
}

export default App;
