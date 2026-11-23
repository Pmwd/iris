import type {
  Approval,
  ApprovalDecision,
  BackupInfo,
  Extraction,
  Fact,
  FactKind,
  FactRole,
  FactScope,
  Health,
  ManagedProcess,
  Message,
  PermissionProfile,
  ProcessLogs,
  Role,
  RoleId,
  Session,
  SummaryResponse,
  Turn,
  TurnEvent,
  Workspace,
} from "./types";

const BASE = "/api";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  };
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    headers["X-Iris-Client"] = "web";
  }
  const response = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    const text = await response.text();
    let detail = text;
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      if (typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      // keep the raw response
    }
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

function json(body: unknown, method = "POST"): RequestInit {
  return { method, body: JSON.stringify(body) };
}

function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  health: () => request<Health>("/health"),
  listRoles: () => request<Role[]>("/roles"),

  listWorkspaces: (includeArchived = false) =>
    request<Workspace[]>(`/workspaces${query({ include_archived: includeArchived })}`),
  getWorkspace: (id: string) => request<Workspace>(`/workspaces/${id}`),
  createWorkspace: (body: {
    name: string;
    workspace_path: string;
    brief_md: string;
    allowed_tools: string[];
  }) => request<Workspace>("/workspaces", json(body)),
  updateWorkspace: (
    id: string,
    body: Partial<
      Pick<Workspace, "name" | "workspace_path" | "brief_md" | "allowed_tools"> & {
        archived: boolean;
      }
    >,
  ) => request<Workspace>(`/workspaces/${id}`, json(body, "PATCH")),
  deleteWorkspace: (id: string) =>
    request<{ deleted: boolean }>(`/workspaces/${id}`, { method: "DELETE" }),

  listProcesses: (workspaceId: string) =>
    request<ManagedProcess[]>(`/workspaces/${workspaceId}/processes`),
  startProcess: (workspaceId: string, body: { command: string; label?: string }) =>
    request<ManagedProcess>(`/workspaces/${workspaceId}/processes`, json(body)),
  getProcess: (processId: string) =>
    request<ManagedProcess>(`/processes/${processId}`),
  getProcessLogs: (processId: string, afterSeq = 0) =>
    request<ProcessLogs>(
      `/processes/${processId}/logs${query({ after_seq: afterSeq })}`,
    ),
  stopProcess: (processId: string) =>
    request<ManagedProcess>(`/processes/${processId}/stop`, { method: "POST" }),

  listSessions: (params: {
    role?: RoleId;
    project_id?: string;
    status?: string;
    limit?: number;
  } = {}) => request<Session[]>(`/sessions${query(params)}`),
  createSession: (body: { role: RoleId; title?: string; project_id?: string | null }) =>
    request<Session>("/sessions", json(body)),
  getSession: (id: string) => request<Session>(`/sessions/${id}`),
  updateSession: (id: string, body: { title?: string; status?: string }) =>
    request<Session>(`/sessions/${id}`, json(body, "PATCH")),
  deleteSession: (id: string) =>
    request<{ deleted: boolean }>(`/sessions/${id}`, { method: "DELETE" }),
  endSession: (id: string) =>
    request<Session>(`/sessions/${id}/end`, { method: "POST" }),
  compactSession: (id: string) =>
    request<{ queued: boolean; session?: Session }>(`/sessions/${id}/compact`, {
      method: "POST",
    }),
  listMessages: (sessionId: string, afterSeq = 0, limit = 500) =>
    request<Message[]>(
      `/sessions/${sessionId}/messages${query({ after_seq: afterSeq, limit })}`,
    ),
  sendMessage: (
    sessionId: string,
    body: {
      content: string;
      permission_profile?: PermissionProfile;
      fact_ids?: string[] | null;
    },
  ) =>
    request<{ turn: Turn; user_message: Message }>(
      `/sessions/${sessionId}/messages`,
      json(body),
    ),
  listTurns: (sessionId: string, limit = 200) =>
    request<Turn[]>(`/sessions/${sessionId}/turns${query({ limit })}`),
  getTurn: (turnId: string) => request<Turn>(`/turns/${turnId}`),
  cancelTurn: (turnId: string) =>
    request<Turn>(`/turns/${turnId}/cancel`, { method: "POST" }),
  listTurnEvents: (turnId: string, afterSeq = 0) =>
    request<TurnEvent[]>(
      `/turns/${turnId}/events${query({ after_seq: afterSeq })}`,
    ),
  turnStreamUrl: (turnId: string, afterSeq = 0) =>
    `${BASE}/turns/${turnId}/events/stream${query({ after_seq: afterSeq })}`,
  turnRawUrl: (turnId: string) => `${BASE}/turns/${turnId}/raw`,

  listTurnApprovals: (turnId: string) =>
    request<Approval[]>(`/turns/${turnId}/approvals`),
  decideApproval: (
    approvalId: string,
    decision: ApprovalDecision,
    message = "",
  ) =>
    request<Approval>(
      `/approvals/${approvalId}/decide`,
      json({ decision, message }),
    ),

  getSummary: (sessionId: string) =>
    request<SummaryResponse>(`/sessions/${sessionId}/summary`),
  requestSummary: (sessionId: string) =>
    request<{ queued: boolean }>(`/sessions/${sessionId}/summary`, {
      method: "POST",
    }),

  listFacts: (params: {
    status?: string;
    scope?: FactScope;
    project_id?: string;
    role?: FactRole;
    include_global?: boolean;
    limit?: number;
  } = {}) => request<Fact[]>(`/facts${query(params)}`),
  createFact: (body: {
    scope: FactScope;
    project_id?: string | null;
    role?: FactRole;
    kind?: FactKind;
    status?: "candidate" | "accepted";
    title: string;
    content_md?: string;
    aliases?: string[];
    pinned?: boolean;
  }) => request<Fact>("/facts", json(body)),
  updateFact: (
    id: string,
    body: {
      scope?: FactScope;
      project_id?: string | null;
      role?: FactRole;
      kind?: FactKind;
      status?: string;
      title?: string;
      content_md?: string;
      aliases?: string[];
      pinned?: boolean;
    },
  ) => request<Fact>(`/facts/${id}`, json(body, "PATCH")),
  archiveFact: (id: string) =>
    request<{ archived: boolean }>(`/facts/${id}`, { method: "DELETE" }),
  extractFacts: (body: {
    role?: RoleId | null;
    project_id?: string | null;
    session_ids?: string[] | null;
    max_sessions?: number | null;
  }) => request<Extraction>("/facts/extract", json(body)),
  listExtractions: (limit = 50) =>
    request<Extraction[]>(`/fact-extractions${query({ limit })}`),
  getExtraction: (id: string) =>
    request<Extraction>(`/fact-extractions/${id}`),

  listBackups: () => request<BackupInfo[]>("/maintenance/backups"),
  backup: () => request<BackupInfo>("/maintenance/backup", { method: "POST" }),
};
