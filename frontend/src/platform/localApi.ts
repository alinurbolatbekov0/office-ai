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

async function request<T>(config: RuntimeConfig, resource: string): Promise<T> {
  const response = await fetch(`${config.apiBaseUrl}/${resource}`, {
    method: "GET",
    headers: { "X-OfficeAI-Token": config.sessionToken },
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
