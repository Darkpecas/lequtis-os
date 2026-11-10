PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;

-- Canonical living-kernel schema (also created by core/lequtis.py init).
-- Revision lequtis-os-kernel-4.
-- An existing lequtis-os-kernel-3 database is not changed by init or status.
-- Migrate it explicitly: python3 core/lequtis.py migrate
-- (database/migrations/lequtis-os-kernel-3-to-4.sql).

CREATE TABLE IF NOT EXISTS identity (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agenda (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    idempotency_key TEXT,
    request_hash TEXT,
    cancelled_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agenda_idempotency
    ON agenda(idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence TEXT,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    agenda_id TEXT,
    idempotency_key TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    result TEXT,
    error TEXT,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    FOREIGN KEY(agenda_id) REFERENCES agenda(id)
);

CREATE TABLE IF NOT EXISTS loop_runs (
    id TEXT PRIMARY KEY,
    correlation_id TEXT UNIQUE NOT NULL,
    phase TEXT NOT NULL,
    status TEXT NOT NULL,
    task_id TEXT,
    evidence TEXT NOT NULL,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_sources (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    role TEXT NOT NULL,
    location TEXT NOT NULL,
    status TEXT NOT NULL,
    meta TEXT NOT NULL,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_items (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    path TEXT NOT NULL,
    title TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    status TEXT NOT NULL,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    UNIQUE(source_id, path),
    FOREIGN KEY(source_id) REFERENCES knowledge_sources(id)
);

CREATE TABLE IF NOT EXISTS executions (
    id TEXT PRIMARY KEY,
    agenda_id TEXT NOT NULL REFERENCES agenda(id),
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,
    action TEXT NOT NULL,
    input TEXT NOT NULL,
    result TEXT,
    error TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    claim_generation INTEGER NOT NULL DEFAULT 0,
    lease_token TEXT,
    worker_pid INTEGER,
    lease_proc_start TEXT,
    correlation_id TEXT,
    artifact_relpath TEXT,
    expected_sha256 TEXT,
    verifier_challenge TEXT,
    claimed_verdict TEXT,
    cancelled_at TEXT,
    UNIQUE(agenda_id, attempt)
);

CREATE TABLE IF NOT EXISTS cancellations (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_hash TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    reason TEXT,
    created TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verifier_observations (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    correlation_id TEXT,
    artifact_path TEXT,
    content_sha256 TEXT,
    verdict TEXT NOT NULL,
    reason TEXT NOT NULL,
    verifier_pid INTEGER NOT NULL,
    worker_self_report_consulted INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL
);
