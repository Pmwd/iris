import type {
  BackupInfo,
  ContextPreview,
  Health,
  Note,
  PermissionProfile,
  Project,
  ResearchJob,
  Role,
  Run,
  RunEvent,
  Task,
  TaskRole,
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

function json(body: unknown): RequestInit {
  return { method: "POST", body: JSON.stringify(body) };
}

export const api = {
  health: () => request<Health>("/health"),

  listProjects: () => request<Project[]>("/projects"),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (body: {
    name: string;
    workspace_path: string;
    brief_md: string;
    allowed_tools: string[];
  }) => request<Project>("/projects", json(body)),
  updateProject: (
    id: string,
    body: Partial<Pick<Project, "name" | "workspace_path" | "brief_md" | "allowed_tools">>,
  ) => request<Project>(`/projects/${id}`, { ...json(body), method: "PATCH" }),
  deleteProject: (id: string) =>
    request<{ deleted: boolean }>(`/projects/${id}`, { method: "DELETE" }),

  listBackups: () => request<BackupInfo[]>("/maintenance/backups"),
  backup: () => request<BackupInfo>("/maintenance/backup", { method: "POST" }),

  listRoles: () => request<Role[]>("/roles"),
  listTasks: (projectId: string) => request<Task[]>(`/projects/${projectId}/tasks`),
  createTask: (
    projectId: string,
    body: {
      title: string;
      goal_md: string;
      role?: TaskRole;
      source_task_id?: string | null;
    },
  ) => request<Task>(`/projects/${projectId}/tasks`, json(body)),
  getTask: (id: string) => request<Task>(`/tasks/${id}`),
  updateTask: (id: string, body: { title?: string; goal_md?: string }) =>
    request<Task>(`/tasks/${id}`, { ...json(body), method: "PATCH" }),
  completeTask: (id: string) =>
    request<Task>(`/tasks/${id}/complete`, { method: "POST" }),
  contextPreview: (taskId: string) =>
    request<ContextPreview>(`/tasks/${taskId}/context-preview`),

  listResearchJobs: (taskId: string) =>
    request<ResearchJob[]>(`/tasks/${taskId}/research`),
  createResearchPlan: (taskId: string, allowWeb: boolean) =>
    request<ResearchJob>(`/tasks/${taskId}/research/plan`, json({ allow_web: allowWeb })),
  getResearchJob: (jobId: string) => request<ResearchJob>(`/research/${jobId}`),
  updateResearchPlan: (jobId: string, questions: string[]) =>
    request<ResearchJob>(`/research/${jobId}/plan`, {
      ...json({ questions }),
      method: "PATCH",
    }),
  startResearchJob: (jobId: string) =>
    request<ResearchJob>(`/research/${jobId}/start`, { method: "POST" }),
  cancelResearchJob: (jobId: string) =>
    request<ResearchJob>(`/research/${jobId}/cancel`, { method: "POST" }),

  startRun: (
    taskId: string,
    body: {
      mode: "new" | "resume";
      permission_profile: PermissionProfile;
      context_note_ids: string[] | null;
    },
  ) => request<Run>(`/tasks/${taskId}/runs`, json(body)),
  listRuns: (taskId: string) => request<Run[]>(`/tasks/${taskId}/runs`),
  getRun: (runId: string) => request<Run>(`/runs/${runId}`),
  cancelRun: (runId: string) =>
    request<Run>(`/runs/${runId}/cancel`, { method: "POST" }),
  listEvents: (runId: string, afterSeq = 0) =>
    request<RunEvent[]>(`/runs/${runId}/events?after_seq=${afterSeq}`),
  runStreamUrl: (runId: string, afterSeq = 0) =>
    `${BASE}/runs/${runId}/events/stream?after_seq=${afterSeq}`,

  listNotes: (projectId: string, status?: string) =>
    request<Note[]>(
      `/projects/${projectId}/notes${status ? `?status=${encodeURIComponent(status)}` : ""}`,
    ),
  createNote: (
    projectId: string,
    body: {
      title: string;
      content_md: string;
      aliases?: string[];
      kind?: Note["kind"];
      status?: "draft" | "accepted";
      pinned?: boolean;
      task_id?: string | null;
      source_run_id?: string | null;
    },
  ) => request<Note>(`/projects/${projectId}/notes`, json(body)),
  updateNote: (
    noteId: string,
    body: {
      title?: string;
      content_md?: string;
      aliases?: string[];
      status?: Note["status"];
      pinned?: boolean;
    },
  ) => request<Note>(`/notes/${noteId}`, { ...json(body), method: "PATCH" }),
  deleteNote: (noteId: string) =>
    request<{ deleted: boolean }>(`/notes/${noteId}`, { method: "DELETE" }),

  listGlobalNotes: (status?: string) =>
    request<Note[]>(
      `/global-notes${status ? `?status=${encodeURIComponent(status)}` : ""}`,
    ),
  createGlobalNote: (body: {
    title: string;
    content_md: string;
    aliases?: string[];
    kind?: Note["kind"];
    status?: "draft" | "accepted";
    pinned?: boolean;
  }) => request<Note>("/global-notes", json(body)),
  updateGlobalNote: (
    noteId: string,
    body: {
      title?: string;
      content_md?: string;
      aliases?: string[];
      status?: Note["status"];
      pinned?: boolean;
    },
  ) => request<Note>(`/global-notes/${noteId}`, { ...json(body), method: "PATCH" }),
  deleteGlobalNote: (noteId: string) =>
    request<{ deleted: boolean }>(`/global-notes/${noteId}`, {
      method: "DELETE",
    }),
};
