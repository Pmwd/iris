export type TaskStatus =
  | "ready"
  | "running"
  | "needs_review"
  | "interrupted"
  | "failed"
  | "canceled"
  | "done";

export type RunStatus =
  | "starting"
  | "running"
  | "canceling"
  | "succeeded"
  | "failed"
  | "canceled"
  | "interrupted";

export type PermissionProfile =
  | "read_only"
  | "edit"
  | "execute"
  | "verify"
  | "research";
export type TaskRole = "coding" | "scholar" | "mentor" | "testing";
export type ResearchStatus =
  | "planning"
  | "planned"
  | "running"
  | "canceling"
  | "completed"
  | "failed"
  | "canceled"
  | "interrupted";

export interface Project {
  id: string;
  name: string;
  workspace_path: string;
  brief_md: string;
  allowed_tools: string[];
  trusted_at: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface Task {
  id: string;
  project_id: string;
  title: string;
  goal_md: string;
  role: TaskRole;
  source_task_id: string | null;
  status: TaskStatus;
  current_session_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ContextManifest {
  prompt_version?: string;
  budget_chars?: number;
  total_chars?: number;
  available_note_count?: number;
  included_notes?: Array<{
    id: string;
    title: string;
    scope?: "project" | "global";
    chars: number;
    reason?: string | null;
    updated_at: string;
  }>;
  excluded_notes?: Array<{ id: string; title: string; reason: string }>;
  mentor_state_note_count?: number;
}

export interface Run {
  id: string;
  task_id: string;
  attempt_no: number;
  status: RunStatus;
  cli_session_id: string | null;
  permission_profile: PermissionProfile;
  prompt_version: string;
  workspace_path: string;
  context_manifest: ContextManifest;
  pid: number | null;
  started_at: string | null;
  ended_at: string | null;
  exit_code: number | null;
  cost_usd: number | null;
  usage: Record<string, unknown>;
  result_text: string | null;
  error_type: string | null;
  error_message: string | null;
  created_at: string;
}

export interface RunEvent {
  id: number;
  run_id: string;
  seq: number;
  kind: string;
  created_at: string;
  payload: unknown;
  truncated: number;
}

export interface Note {
  id: string;
  project_id?: string;
  task_id?: string | null;
  source_run_id?: string | null;
  kind:
    | "outcome"
    | "decision"
    | "note"
    | "research"
    | "goal"
    | "capability"
    | "blind_spot"
    | "progress";
  status: "draft" | "accepted" | "archived";
  title: string;
  content_md: string;
  aliases: string[];
  pinned: boolean;
  use_count?: number;
  last_used_at?: string | null;
  scope?: "project" | "global";
  created_at: string;
  updated_at: string;
  accepted_at: string | null;
}

export interface ContextNote extends Note {
  scope: "project" | "global";
  recommended: boolean;
  reason:
    | "pinned"
    | "matched"
    | "recent"
    | "handoff"
    | "mentor_state"
    | "budget"
    | "not_relevant";
  score: number;
  matched: boolean;
  handoff?: boolean;
  search_rank: number | null;
}

export interface Role {
  id: TaskRole;
  name: string;
  description: string;
  default_profile: PermissionProfile;
  allowed_profiles: PermissionProfile[];
}

export interface ResearchSubtask {
  id: string;
  job_id: string;
  seq: number;
  question: string;
  status: "queued" | "running" | "succeeded" | "failed" | "canceled" | "interrupted";
  result_text: string | null;
  sources: string[];
  attempts: number;
  error: string | null;
  started_at: string | null;
  ended_at: string | null;
}

export interface ResearchJob {
  id: string;
  task_id: string;
  status: ResearchStatus;
  allow_web: boolean;
  max_concurrency: number;
  plan: string[];
  synthesis_note_id: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  subtasks: ResearchSubtask[];
}

export interface ContextPreview {
  task_id: string;
  project_id: string;
  role: TaskRole;
  source_task_id: string | null;
  project_brief: string;
  budget_chars: number;
  budget_tokens: number;
  estimated_tokens: number;
  selected_chars: number;
  query_terms: string[];
  notes: ContextNote[];
  selected_note_ids: string[];
  execute_allowed: boolean;
  security_warnings: string[];
}

export interface BackupInfo {
  name: string;
  path: string;
  size: number;
  created_at: string;
}

export interface Health {
  status: string;
  data_dir: string;
  db_path: string;
  host: string;
  project_count?: number;
  cli: {
    installed: boolean;
    version: string | null;
    auth_ok: boolean | null;
    auth_method: string | null;
    api_provider: string | null;
  };
}
