-- Runtime schema for the kernel extended from public commit
-- dd77615b97872ee25a98ef95b6314ab177252af6.
-- These are the tables core/lequtis.py creates. Revision
-- lequtis-os-kernel-3 is stored in identity by init of a new database.
-- An existing database with another revision is refused and not altered.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

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
    request_hash TEXT
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
    UNIQUE(agenda_id, attempt)
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
