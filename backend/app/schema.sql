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
