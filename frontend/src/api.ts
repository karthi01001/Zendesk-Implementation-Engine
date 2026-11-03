// Typed calls to the local Python backend. Secrets are sent once to connect and never read back.

export type AuthType = "oauth" | "api_token";

export interface ConnectRequest {
  subdomain: string;
  auth_type: AuthType;
  client_id?: string;
  client_secret?: string;
  email?: string;
  api_token?: string;
}

export interface ConnectionInfo {
  subdomain: string;
  auth_type: AuthType;
  user_name: string;
  user_email: string | null;
  role: string;
  is_admin: boolean;
  granted_scope: string | null;
  warnings: string[];
}

export interface ActiveConnection {
  active: boolean;
  subdomain: string | null;
  auth_type: AuthType | null;
  scope: string | null;
}

export interface AreaInfo {
  key: string;
  label: string;
  section: string;
  plan_note: string | null;
}

export type AreaStatus = "ok" | "unavailable" | "error";

export interface AreaSummary {
  key: string;
  label: string;
  section: string;
  status: AreaStatus;
  count: number;
  message: string | null;
  duration_ms: number;
}

export interface SnapshotSummary {
  id: string;
  subdomain: string;
  taken_at: string;
  engine_version: string;
  areas_ok: number;
  areas_total: number;
  total_items: number;
  areas: AreaSummary[];
}

export interface ItemRow {
  id: string;
  name: string;
  active: boolean | null;
  updated_at: string | null;
  /** How many items refer to this one; null for areas nothing can refer to. */
  used_by: number | null;
  /** true/false when known; null when the area cannot be "used" or a rule area was not read. */
  unused: boolean | null;
  raw: Record<string, unknown>;
}

export interface ItemKey {
  area: string;
  id: string;
  name: string;
  label: string;
  missing: boolean;
}

export interface Reference {
  source: ItemKey;
  target: ItemKey;
  context: string;
  detail: string | null;
}

export interface ItemDependencies {
  item: ItemKey;
  uses: Reference[];
  used_by: Reference[];
}

export interface TagUsage {
  tag: string;
  used_by: number;
}

export interface DependencySummary {
  snapshot_id: string;
  references: number;
  tags: number;
  broken: Reference[];
  unused_ticket_fields: ItemKey[];
  incomplete_areas: string[];
}

export interface FieldChange {
  path: string;
  before: unknown;
  after: unknown;
}

export interface ItemRef {
  id: string;
  name: string;
}

export interface ChangedItem extends ItemRef {
  changes: FieldChange[];
  truncated: boolean;
}

export interface AreaDiff {
  key: string;
  label: string;
  section: string;
  base_status: AreaStatus | null;
  target_status: AreaStatus | null;
  added: ItemRef[];
  removed: ItemRef[];
  changed: ChangedItem[];
}

export interface SnapshotDiff {
  subdomain: string;
  base_id: string;
  target_id: string;
  base_taken_at: string;
  target_taken_at: string;
  added: number;
  removed: number;
  changed: number;
  areas: AreaDiff[];
}

export interface AreaData {
  key: string;
  label: string;
  section: string;
  plan_note: string | null;
  snapshot_id: string;
  taken_at: string;
  status: AreaStatus;
  message: string | null;
  count: number;
  items: ItemRow[];
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const ENGINE_DOWN =
  "The local engine is not running or still starting. Start it with scripts\\start.ps1, then retry.";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, ENGINE_DOWN);
  }
  if (!response.ok) {
    // The dev-server proxy answers 5xx with no JSON body when the backend is not running.
    const isJson = (response.headers.get("content-type") ?? "").includes("application/json");
    if (response.status >= 500 && !isJson) throw new ApiError(response.status, ENGINE_DOWN);
    throw new ApiError(response.status, await errorMessage(response));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) {
        return detail
          .map((item) =>
            item && typeof item === "object" && "msg" in item ? String(item.msg) : "",
          )
          .filter(Boolean)
          .join("; ");
      }
    }
  } catch {
    // fall through to the status text
  }
  return `${response.status} ${response.statusText}`.trim();
}

export const api = {
  getConnection: () => request<ActiveConnection>("/api/connection"),
  testConnection: (body: ConnectRequest) =>
    request<ConnectionInfo>("/api/connection/test", { method: "POST", body: JSON.stringify(body) }),
  connect: (body: ConnectRequest) =>
    request<ConnectionInfo>("/api/connection", { method: "POST", body: JSON.stringify(body) }),
  disconnect: () => request<void>("/api/connection", { method: "DELETE" }),
  getAreas: () => request<AreaInfo[]>("/api/areas"),
  getLatestSnapshot: () => request<{ snapshot: SnapshotSummary | null }>("/api/snapshots/latest"),
  readEverything: () => request<SnapshotSummary>("/api/snapshots", { method: "POST" }),
  getArea: (key: string) => request<AreaData>(`/api/config/${encodeURIComponent(key)}`),
  getSnapshots: () => request<SnapshotSummary[]>("/api/snapshots"),
  compareSnapshots: (base: string, target: string) =>
    request<SnapshotDiff>(
      `/api/snapshots/compare?base=${encodeURIComponent(base)}&target=${encodeURIComponent(target)}`,
    ),
  getDependencySummary: () => request<DependencySummary>("/api/dependencies/summary"),
  getDependencies: (area: string, id: string) =>
    request<ItemDependencies>(
      `/api/dependencies/${encodeURIComponent(area)}/${encodeURIComponent(id)}`,
    ),
  getTags: () => request<TagUsage[]>("/api/tags"),
};

/** Download a file from the backend, reporting the backend's error message if it fails. */
export async function downloadFile(url: string, fallbackName: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(url);
  } catch {
    throw new ApiError(0, ENGINE_DOWN);
  }
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response));
  const disposition = response.headers.get("content-disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? fallbackName;
  const href = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = href;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(href), 10_000);
}

/** Links the browser can open directly (downloads go through the same local backend). */
export const reportUrls = {
  docx: "/api/reports/current-state?format=docx",
  html: "/api/reports/current-state?format=html",
};
