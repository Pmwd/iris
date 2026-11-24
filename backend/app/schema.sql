PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    workspace_path TEXT NOT NULL,
    brief_md TEXT NOT NULL DEFAULT '',
    allowed_tools_json TEXT NOT NULL DEFAULT '[]',
    trusted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    goal_md TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'coding',
    source_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    current_session_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    attempt_no INTEGER NOT NULL,
    status TEXT NOT NULL,
    cli_session_id TEXT,
    permission_profile TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    workspace_path TEXT NOT NULL,
    context_manifest_json TEXT NOT NULL DEFAULT '{}',
    pid INTEGER,
    started_at TEXT,
    ended_at TEXT,
    exit_code INTEGER,
    cost_usd REAL,
    usage_json TEXT,
    result_text TEXT,
    error_type TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_task ON runs(task_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    truncated INTEGER NOT NULL DEFAULT 0,
    UNIQUE(run_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_run_events_run_seq ON run_events(run_id, seq);

CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    source_run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    content_md TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    pinned INTEGER NOT NULL DEFAULT 0,
    use_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    accepted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_notes_project_status ON notes(project_id, status);

CREATE TABLE IF NOT EXISTS global_notes (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    content_md TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    pinned INTEGER NOT NULL DEFAULT 0,
    use_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    accepted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_global_notes_status ON global_notes(status);

CREATE TABLE IF NOT EXISTS research_jobs (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    allow_web INTEGER NOT NULL DEFAULT 0,
    max_concurrency INTEGER NOT NULL DEFAULT 2,
    plan_json TEXT NOT NULL DEFAULT '[]',
    synthesis_note_id TEXT REFERENCES notes(id) ON DELETE SET NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_research_jobs_task ON research_jobs(task_id);

CREATE TABLE IF NOT EXISTS research_subtasks (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES research_jobs(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    question TEXT NOT NULL,
    status TEXT NOT NULL,
    session_id TEXT,
    result_text TEXT,
    sources_json TEXT NOT NULL DEFAULT '[]',
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    started_at TEXT,
    ended_at TEXT,
    UNIQUE(job_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_research_subtasks_job ON research_subtasks(job_id);

CREATE TABLE IF NOT EXISTS research_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES research_jobs(id) ON DELETE CASCADE,
    subtask_id TEXT,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_events_job ON research_events(job_id, id);

-- ----------------------------------------------------------------------
-- Schema v7: session-oriented workbench + three-layer memory.
-- Legacy tables above stay read-only; new code only uses the tables below.
-- ----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    title TEXT NOT NULL,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'active',
    cli_session_id TEXT,
    cli_session_confirmed INTEGER NOT NULL DEFAULT 0,
    summary_covers_turn_seq INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_role ON sessions(role, updated_at);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);

CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    mode TEXT NOT NULL,
    permission_profile TEXT NOT NULL,
    cli_session_id TEXT,
    prompt_manifest_json TEXT NOT NULL DEFAULT '{}',
    pid INTEGER,
    raw_log_path TEXT,
    started_at TEXT,
    ended_at TEXT,
    exit_code INTEGER,
    cost_usd REAL,
    usage_json TEXT,
    result_text TEXT,
    error_type TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_turns_status ON turns(status);

-- One active turn per session, and one active coding turn per workspace.
-- These indexes are the backstop for the application-level checks.
CREATE UNIQUE INDEX IF NOT EXISTS uq_turns_active_session
    ON turns(session_id)
    WHERE status IN ('starting', 'running', 'canceling');
CREATE UNIQUE INDEX IF NOT EXISTS uq_turns_active_code_workspace
    ON turns(project_id)
    WHERE project_id IS NOT NULL
      AND role = 'coding'
      AND status IN ('starting', 'running', 'canceling');

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_id TEXT REFERENCES turns(id) ON DELETE SET NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(session_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, seq);

CREATE TABLE IF NOT EXISTS turn_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    truncated INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(turn_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_turn_events_turn ON turn_events(turn_id, seq);

CREATE TABLE IF NOT EXISTS session_summaries (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    covers_through_turn_seq INTEGER NOT NULL DEFAULT 0,
    content_md TEXT NOT NULL DEFAULT '',
    model TEXT,
    cost_usd REAL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_session_summaries_session
    ON session_summaries(session_id, status);

CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'both',
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    content_md TEXT NOT NULL DEFAULT '',
    aliases_json TEXT NOT NULL DEFAULT '[]',
    pinned INTEGER NOT NULL DEFAULT 0,
    use_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    source_session_ids_json TEXT NOT NULL DEFAULT '[]',
    evidence_md TEXT NOT NULL DEFAULT '',
    confidence REAL,
    supersedes_id TEXT REFERENCES facts(id) ON DELETE SET NULL,
    extracted_at TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_facts_status ON facts(status, scope);
CREATE INDEX IF NOT EXISTS idx_facts_project ON facts(project_id);

CREATE TABLE IF NOT EXISTS fact_extractions (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    scope_json TEXT NOT NULL DEFAULT '{}',
    candidate_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_fact_extractions_status
    ON fact_extractions(status);

-- ----------------------------------------------------------------------
-- Schema v8: interactive tool approvals for the Claude Agent SDK runner.
-- ----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS turn_approvals (
    id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    input_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    decision TEXT,
    message TEXT NOT NULL DEFAULT '',
    decided_by TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_turn_approvals_turn
    ON turn_approvals(turn_id, created_at);
CREATE INDEX IF NOT EXISTS idx_turn_approvals_status
    ON turn_approvals(status);

CREATE TABLE IF NOT EXISTS permission_rules (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    match_type TEXT NOT NULL,
    match_value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, tool_name, match_type, match_value)
);

CREATE INDEX IF NOT EXISTS idx_permission_rules_session
    ON permission_rules(session_id, tool_name);

-- ----------------------------------------------------------------------
-- Schema v9: metric rollups for the dashboard.
-- ----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS metric_rollups (
    bucket_start TEXT NOT NULL,
    bucket_size TEXT NOT NULL,
    metric TEXT NOT NULL,
    dimensions_json TEXT NOT NULL DEFAULT '{}',
    value REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (bucket_start, bucket_size, metric, dimensions_json)
);

CREATE INDEX IF NOT EXISTS idx_metric_rollups_lookup
    ON metric_rollups(metric, bucket_size, dimensions_json, bucket_start);
