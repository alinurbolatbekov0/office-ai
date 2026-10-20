import type { RuntimeConfig } from "./desktopBridge";

export interface AgentDescriptor {
  id: string;
  title: string;
  description: string;
  status: "prepared";
}

export interface HealthStatus {
  status: "ok";
  application: string;
  version: string;
}

export interface AppSettings {
  theme: "light" | "dark";
  confirm_destructive_actions: boolean;
}

export interface OperationEvent {
  id: string;
  occurredAt: string;
  operationCode: string;
  outcome: "success" | "failure";
  entityType: string | null;
  entityId: string | null;
  messageCode: string;
}

async function request<T>(
  config: RuntimeConfig,
  resource: string,
  options: { method?: "GET" | "PUT"; value?: unknown } = {},
): Promise<T> {
  const method = options.method ?? "GET";
  const response = await fetch(`${config.apiBaseUrl}/${resource}`, {
    method,
    headers: {
      "X-OfficeAI-Token": config.sessionToken,
      ...(options.value === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: options.value === undefined ? undefined : JSON.stringify({ value: options.value }),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Локальный API ответил с кодом ${response.status}.`);
  }
  return response.json() as Promise<T>;
}

export function getHealth(config: RuntimeConfig): Promise<HealthStatus> {
  return request(config, "health");
}

export async function getAgents(config: RuntimeConfig): Promise<AgentDescriptor[]> {
  const response = await request<{ agents: AgentDescriptor[] }>(config, "agents");
  return response.agents;
}

export async function getSettings(config: RuntimeConfig): Promise<AppSettings> {
  const response = await request<{ settings: AppSettings }>(config, "settings");
  return response.settings;
}

export async function saveSetting(
  config: RuntimeConfig,
  key: keyof AppSettings,
  value: AppSettings[keyof AppSettings],
): Promise<AppSettings> {
  const response = await request<{ settings: AppSettings }>(config, `settings/${key}`, {
    method: "PUT",
    value,
  });
  return response.settings;
}

export async function getOperations(config: RuntimeConfig): Promise<OperationEvent[]> {
  const response = await request<{ operations: OperationEvent[] }>(config, "operations?limit=20");
  return response.operations;
}
