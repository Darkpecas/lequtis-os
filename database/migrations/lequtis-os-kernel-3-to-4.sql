-- Migrate lequtis-os-kernel-3 to lequtis-os-kernel-4.
-- Applied only by core/lequtis.py migrate, inside one transaction, after the
-- schema guard has identified an untouched kernel-3 database.
-- The revision row and the schema.migrated event are written by that command.

ALTER TABLE agenda ADD COLUMN cancelled_at TEXT;

ALTER TABLE executions ADD COLUMN cancelled_at TEXT;

CREATE TABLE IF NOT EXISTS cancellations (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_hash TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    reason TEXT,
    created TEXT NOT NULL
);
