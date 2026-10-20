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

export interface LibraryDocument {
  id: string;
  name: string;
  extension: string;
  importedAt: string;
  sizeBytes: number;
  type: "DOCX" | "XLSX" | "PPTX" | "PDF" | "JPEG" | "PNG";
  sha256: string;
}

export interface DocumentFilters {
  search?: string;
  type?: LibraryDocument["type"] | "";
  importedFrom?: string;
  importedTo?: string;
  sortBy?: "name" | "imported_at" | "size_bytes" | "type";
  sortOrder?: "asc" | "desc";
}

export class DuplicateDocumentError extends Error {
  constructor(readonly existingDocuments: LibraryDocument[]) {
    super("Такой файл уже есть в библиотеке.");
  }
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
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `Локальный API ответил с кодом ${response.status}.`);
  }
  return response.json() as Promise<T>;
}

export async function getDocuments(
  config: RuntimeConfig,
  filters: DocumentFilters = {},
): Promise<{ documents: LibraryDocument[]; total: number }> {
  const query = new URLSearchParams({ limit: "50", offset: "0" });
  if (filters.search) query.set("search", filters.search);
  if (filters.type) query.set("type", filters.type);
  if (filters.importedFrom) query.set("imported_from", filters.importedFrom);
  if (filters.importedTo) query.set("imported_to", filters.importedTo);
  if (filters.sortBy) query.set("sort_by", filters.sortBy);
  if (filters.sortOrder) query.set("sort_order", filters.sortOrder);
  return request(config, `documents?${query.toString()}`);
}

export async function uploadDocument(
  config: RuntimeConfig,
  file: File,
  confirmDuplicate = false,
): Promise<{ duplicate: boolean; confirmed?: boolean; document?: LibraryDocument }> {
  const response = await fetch(`${config.apiBaseUrl}/documents`, {
    method: "POST",
    headers: {
      "X-OfficeAI-Token": config.sessionToken,
      "Content-Type": "application/octet-stream",
      "X-OfficeAI-Filename": encodeURIComponent(file.name),
      ...(confirmDuplicate ? { "X-OfficeAI-Confirm-Duplicate": "true" } : {}),
    },
    body: file,
    cache: "no-store",
  });
  const payload = (await response.json().catch(() => null)) as {
    duplicate?: boolean;
    confirmed?: boolean;
    document?: LibraryDocument;
    existingDocuments?: LibraryDocument[];
    detail?: string;
  } | null;
  if (response.status === 409) {
    throw new DuplicateDocumentError(payload?.existingDocuments ?? []);
  }
  if (!response.ok) {
    throw new Error(payload?.detail ?? `Не удалось сохранить файл (код ${response.status}).`);
  }
  return {
    duplicate: payload?.duplicate === true,
    confirmed: payload?.confirmed,
    document: payload?.document,
  };
}

export async function downloadDocument(config: RuntimeConfig, document: LibraryDocument): Promise<void> {
  const response = await fetch(`${config.apiBaseUrl}/documents/${document.id}/download`, {
    headers: { "X-OfficeAI-Token": config.sessionToken },
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Не удалось скачать файл (код ${response.status}).`);
  const disposition = response.headers.get("content-disposition") ?? "";
  const encodedFilename = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const filename = encodedFilename ? decodeURIComponent(encodedFilename) : document.name;
  const objectUrl = URL.createObjectURL(await response.blob());
  const link = documentLink(objectUrl, filename);
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

function documentLink(url: string, filename: string): HTMLAnchorElement {
  const link = window.document.createElement("a");
  link.href = url;
  link.download = filename;
  link.hidden = true;
  window.document.body.append(link);
  queueMicrotask(() => link.remove());
  return link;
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
