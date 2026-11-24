export type RoleId = "coding" | "scholar";
export type PermissionProfile = "read_only" | "edit" | "execute" | "research";
export type SessionStatus = "active" | "ended" | "archived";
export type TurnStatus =
  | "starting"
  | "running"
  | "canceling"
  | "succeeded"
  | "failed"
  | "canceled"
  | "interrupted";
export type FactScope = "global" | "workspace";
export type FactRole = RoleId | "both";
export type FactKind =
  | "preference"
  | "decision"
  | "constraint"
  | "artifact"
  | "insight"
  | "open_question"
  | "profile";
export type FactStatus = "candidate" | "accepted" | "rejected" | "archived";

export interface Workspace {
  id: string;
  name: string;
  workspace_path: string;
  brief_md: string;
  allowed_tools: string[];
  trusted_at: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  security_warnings?: string[];
  session_count?: number;
}

export interface Session {
  id: string;
  role: RoleId;
  title: string;
  project_id: string | null;
  status: SessionStatus;
  cli_session_id: string | null;
  cli_session_confirmed: boolean;
  summary_covers_turn_seq: number;
  created_at: string;
  updated_at: string;
  ended_at: string | null;
  workspace?: Workspace | null;
  latest_summary?: Summary | null;
  active_turn?: Turn | null;
  turn_count?: number;
  execution_backend?: "sdk" | "cli";
}

export type ProcessStatus =
  | "starting"
  | "running"
  | "stopping"
  | "stopped"
  | "failed";

export interface ManagedProcess {
  id: string;
  project_id: string;
  command: string;
  label: string;
  cwd: string;
  status: ProcessStatus;
  pid: number | null;
  started_at: string;
  ended_at: string | null;
  exit_code: number | null;
  error: string | null;
  seq: number;
}

export interface ProcessLogs {
  process: ManagedProcess;
  lines: Array<{ seq: number; text: string }>;
}

export interface Approval {
  id: string;
  turn_id: string;
  session_id: string;
  tool_name: string;
  input: Record<string, unknown>;
  status: "pending" | "allowed" | "denied" | "expired";
  decision: "allow" | "deny" | "always" | null;
  message: string;
  decided_by: string | null;
  created_at: string;
  decided_at: string | null;
  title?: string | null;
  description?: string | null;
}

export type ApprovalDecision = "allow" | "deny" | "always";

export interface PromptManifest {
  prompt_version?: string;
  role?: RoleId;
  mode?: "new" | "resume";
  budget_chars?: number;
  fact_budget_chars?: number;
  total_chars?: number;
  estimated_tokens?: number;
  included_facts?: Array<{
    id: string;
    title: string;
    scope: FactScope;
    kind: FactKind;
    chars: number;
    reason?: string | null;
  }>;
  excluded_facts?: Array<{
    id: string;
    title: string;
    scope: FactScope;
    reason: string;
  }>;
  summary_included?: boolean;
  summary_chars?: number;
  user_message_chars?: number;
  fact_selection?: "auto" | "manual";
  [key: string]: unknown;
}

export interface Turn {
  id: string;
  session_id: string;
  seq: number;
  role: RoleId;
  project_id: string | null;
  status: TurnStatus;
  mode: "new" | "resume";
  permission_profile: PermissionProfile;
  cli_session_id: string | null;
  prompt_manifest: PromptManifest;
  pid: number | null;
  raw_log_path: string | null;
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

export interface Message {
  id: string;
  session_id: string;
  turn_id: string | null;
  seq: number;
  role: "user" | "assistant" | "system";
  kind: "text" | "result" | "error";
  content: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface TurnEvent {
  id: number;
  turn_id: string;
  seq: number;
  kind: string;
  payload: unknown;
  truncated: number;
  created_at: string;
}

export interface Summary {
  id: string;
  session_id: string;
  kind: "auto" | "final" | "manual" | "compact";
  status: "pending" | "running" | "succeeded" | "failed";
  covers_through_turn_seq: number;
  content_md: string;
  model: string | null;
  cost_usd: number | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface Fact {
  id: string;
  scope: FactScope;
  project_id: string | null;
  role: FactRole;
  kind: FactKind;
  status: FactStatus;
  title: string;
  content_md: string;
  aliases: string[];
  pinned: boolean;
  use_count: number;
  last_used_at: string | null;
  source_session_ids: string[];
  evidence_md: string;
  confidence: number | null;
  supersedes_id: string | null;
  extracted_at: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Extraction {
  id: string;
  status: "running" | "succeeded" | "failed";
  scope: {
    role?: RoleId | null;
    project_id?: string | null;
    session_ids?: string[];
    max_sessions?: number;
  };
  candidate_count: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
}

export interface Role {
  id: RoleId;
  name: string;
  description: string;
  default_profile: PermissionProfile;
  allowed_profiles: PermissionProfile[];
  requires_workspace: boolean;
}

export interface SummaryResponse {
  summary: Summary | null;
  active: Summary | null;
  items: Summary[];
}

export interface MetricsTurns {
  total: number;
  active: number;
  stuck: number;
  succeeded: number;
  failed: number;
  canceled: number;
  interrupted: number;
  success_rate: number | null;
  duration_p50_seconds: number | null;
  duration_p95_seconds: number | null;
  queue_wait_p95_seconds: number | null;
  resume_rate: number | null;
  resume_failure_rate: number | null;
  cancel_rate: number | null;
}

export interface MetricsOverview {
  generated_at: string;
  range: string;
  since: string;
  filters: { role: RoleId | null; project_id: string | null };
  turns: MetricsTurns;
  cost: {
    total_usd: number;
    per_success_usd: number | null;
    by_session: Array<{
      session_id: string;
      title: string;
      cost_usd: number;
      turns: number;
    }>;
  };
  tools: {
    calls: number;
    denials: number;
    calls_per_turn: number | null;
    top: Array<{ name: string; calls: number }>;
  };
  memory: {
    summary_lag: number;
    summary_failure_rate: number | null;
    summary_coverage: number | null;
    fact_candidates_pending: number;
    fact_accept_rate: number | null;
    fact_injection_rate: number | null;
    fact_use_top: Fact[];
    extraction_success_rate: number | null;
  };
  errors: {
    top: Array<{ error_type: string; count: number }>;
    failed_turns: number;
  };
  storage: {
    db_bytes: number;
    raw_log_bytes: number;
    workspace_log_bytes: number;
    backup_age_seconds: number | null;
    disk_free_bytes: number | null;
  };
}

export interface MetricsHealth {
  generated_at: string;
  status: string;
  db_ok: boolean;
  execution_backend: string;
  sdk_cli_path: string | null;
  turns: { active: number; stuck: number };
  queues: {
    summaries_pending: number;
    summaries_running: number;
    extractions_running: number;
  };
  cli: Health["cli"];
}

export interface MetricsError {
  turn_id: string;
  session_id: string;
  role: RoleId;
  project_id: string | null;
  error_type: string;
  error_message: string;
  created_at: string;
  ended_at: string | null;
  cost_usd: number | null;
}

export interface DashboardAlert {
  level: "info" | "warning" | "critical";
  rule: string;
  message: string;
}

export interface DashboardOverviewResponse {
  generated_at: string;
  range: string;
  filters: { role: RoleId | null; project_id: string | null };
  health: MetricsHealth;
  overview: MetricsOverview;
  alerts: DashboardAlert[];
  recent_errors: MetricsError[];
}

export interface TimeseriesPoint {
  bucket_start: string;
  value: number;
}

export interface MetricTimeseries {
  metric: string;
  bucket: "hour" | "day";
  range: string;
  filters: { role: RoleId | null; project_id: string | null };
  points: TimeseriesPoint[];
}

export interface Health {
  status: string;
  data_dir: string;
  db_path: string;
  host: string;
  workspace_count?: number;
  cli: {
    installed: boolean;
    version: string | null;
    auth_ok: boolean | null;
    auth_method: string | null;
    api_provider: string | null;
  };
}

export interface BackupInfo {
  name: string;
  path: string;
  size: number;
  created_at: string;
}
