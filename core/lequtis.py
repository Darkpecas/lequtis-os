#!/usr/bin/env python3
"""
LeQutis Living Kernel — sovereign, model-independent AI partner substrate.

Permanent concepts: identity, relationship continuity, memory, knowledge,
skills, experience, agenda, evidence, evolutionary history.

Replaceable: LLM / coding agent / tool provider / orchestration / storage.

Autonomous loop:
  NOTICE -> THINK -> CHOOSE -> ACT -> OBSERVE -> EVALUATE -> LEARN
  -> REMEMBER -> UPDATE AGENDA
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Paths — LEQUTIS_STATE enables disposable DBs for tests (never production).
# ---------------------------------------------------------------------------

ROOT = Path(os.environ.get("LEQUTIS_ROOT", Path(__file__).resolve().parents[1]))
STATE = Path(os.environ.get("LEQUTIS_STATE", ROOT / "state"))
# LEQUTIS_DB selects one file. When it is unset, the database stays
# STATE/lequtis.db so LEQUTIS_STATE keeps its existing meaning.
DB = Path(os.environ.get("LEQUTIS_DB", STATE / "lequtis.db")).expanduser()
SCHEMA_REVISION = "lequtis-os-kernel-4"
PREVIOUS_SCHEMA_REVISION = "lequtis-os-kernel-3"
MIGRATION_SQL = (
    ROOT / "database" / "migrations" / "lequtis-os-kernel-3-to-4.sql"
)
EVIDENCE_LABEL = "LOCAL PROOF, NOT LIVE VPS VERIFIED"
VERIFIER = Path(__file__).with_name("verifier_main.py")
ARTIFACT_NAME = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.json$"
)

STATE.mkdir(parents=True, exist_ok=True)

PREVIOUS_REQUIRED_COLUMNS = {
    "identity": {"key", "value"},
    "memory": {"id", "kind", "content", "created", "updated"},
    "agenda": {
        "id", "title", "status", "priority", "created", "updated",
        "idempotency_key", "request_hash",
    },
    "skills": {"id", "name", "version", "status", "evidence", "created", "updated"},
    "events": {"seq", "event_id", "ts", "event_type", "payload", "previous_hash", "event_hash"},
    "tasks": {
        "id", "agenda_id", "idempotency_key", "title", "action", "status",
        "payload", "result", "error", "created", "updated",
    },
    "loop_runs": {
        "id", "correlation_id", "phase", "status", "task_id", "evidence",
        "created", "updated",
    },
    "knowledge_sources": {
        "id", "kind", "role", "location", "status", "meta", "created", "updated",
    },
    "knowledge_items": {
        "id", "source_id", "path", "title", "content_hash", "excerpt",
        "status", "created", "updated",
    },
    "executions": {
        "id", "agenda_id", "attempt", "status", "action", "input", "result", "error",
        "started_at", "completed_at", "claim_generation", "lease_token", "worker_pid",
        "lease_proc_start", "correlation_id", "artifact_relpath", "expected_sha256",
        "verifier_challenge", "claimed_verdict",
    },
    "verifier_observations": {
        "id", "execution_id", "correlation_id", "artifact_path", "content_sha256",
        "verdict", "reason", "verifier_pid", "worker_self_report_consulted", "created",
    },
}

REQUIRED_COLUMNS = {
    **{key: set(value) for key, value in PREVIOUS_REQUIRED_COLUMNS.items()},
    "agenda": PREVIOUS_REQUIRED_COLUMNS["agenda"] | {"cancelled_at"},
    "executions": PREVIOUS_REQUIRED_COLUMNS["executions"] | {"cancelled_at"},
    "cancellations": {
        "id", "idempotency_key", "request_hash", "target_kind", "target_id",
        "reason", "created",
    },
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def _columns(db: sqlite3.Connection, table: str) -> set[str] | None:
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchall()
    if not rows:
        return None
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def _schema_refuse(message: str) -> None:
    sys.stderr.write(message + "\n")
    raise SystemExit(3)


@contextmanager
def _readonly_snapshot(db_path: Path):
    """Read a copy, including any WAL, without writing the original.

    ``immutable=1`` would ignore a committed but uncheckpointed WAL, and opening
    the original ``mode=ro`` can create a new WAL file beside it.
    """
    with tempfile.TemporaryDirectory(prefix="lequtis-schema-guard-") as tmp:
        snap = Path(tmp) / "snapshot.db"
        shutil.copy2(db_path, snap)
        for suffix in ("-wal", "-shm"):
            side = Path(str(db_path) + suffix)
            try:
                shutil.copy2(side, Path(str(snap) + suffix))
            except FileNotFoundError:
                continue
        uri = "file:" + str(snap.resolve()) + "?mode=ro"
        try:
            db = sqlite3.connect(uri, uri=True)
        except sqlite3.OperationalError as exc:
            _schema_refuse(f"schema guard: {exc}")
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA query_only=ON")
            yield db
        finally:
            db.close()


def _schema_inventory(db: sqlite3.Connection) -> dict[str, Any]:
    names = {
        row[0]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    tables = {name: _columns(db, name) for name in names}
    revision = None
    if "identity" in names:
        row = db.execute(
            "SELECT value FROM identity WHERE key='schema_revision'"
        ).fetchone()
        revision = None if row is None else row[0]
    return {"revision": revision, "tables": tables, "table_names": names}


def _columns_cover(found: set[str] | None, required: set[str]) -> bool:
    return found is not None and required.issubset(found)


def _is_current_schema(inventory: dict[str, Any]) -> bool:
    if inventory["revision"] != SCHEMA_REVISION:
        return False
    for table, required in REQUIRED_COLUMNS.items():
        if not _columns_cover(inventory["tables"].get(table), required):
            return False
    return True


def _is_previous_schema(inventory: dict[str, Any]) -> bool:
    """True only for an untouched kernel-3 database.

    A partial migration (the new column or table already present, or the
    revision already moved) is not previous and is not current. It is refused.
    """
    if inventory["revision"] != PREVIOUS_SCHEMA_REVISION:
        return False
    if "cancellations" in inventory["table_names"]:
        return False
    for table, required in PREVIOUS_REQUIRED_COLUMNS.items():
        found = inventory["tables"].get(table)
        if not _columns_cover(found, required):
            return False
        if table in ("agenda", "executions") and found is not None and "cancelled_at" in found:
            return False
    return True


def _require_open_db(db: sqlite3.Connection) -> None:
    inventory = _schema_inventory(db)
    if _is_current_schema(inventory):
        return
    for table, required in REQUIRED_COLUMNS.items():
        found = inventory["tables"].get(table)
        if not _columns_cover(found, required):
            missing = sorted(required if found is None else required - found)
            _schema_refuse(
                "schema guard: incompatible database, not modified: "
                + table + " " + ",".join(missing)
            )
    _schema_refuse(
        f"schema guard: revision {inventory['revision']!r} is not {SCHEMA_REVISION}; database not modified"
    )


def _require_compatible() -> None:
    """Read an existing database without writing. Exit 3 when it is not this revision."""
    with _readonly_snapshot(DB) as db:
        _require_open_db(db)


def _apply_sql_statements(db: sqlite3.Connection, script: str) -> None:
    """Run statements inside the caller's transaction.

    ``executescript`` issues a COMMIT first, which would break the migration
    transaction. Split on semicolons; the migration file has none inside literals.
    """
    for statement in script.split(";"):
        if statement.strip():
            db.execute(statement)


def migrate_schema() -> dict[str, Any]:
    """Move an untouched kernel-3 database to kernel-4, or create a new one.

    A database that is already kernel-4 is left unchanged. Anything else is
    refused with exit 3 and is not written. Migration is explicit: ``init`` and
    ``status`` do not migrate.
    """
    if not DB.exists():
        init()
        return {
            "status": "created",
            "schema_revision": SCHEMA_REVISION,
            "evidence_label": EVIDENCE_LABEL,
        }
    with _readonly_snapshot(DB) as db:
        inventory = _schema_inventory(db)
    if _is_current_schema(inventory):
        return {
            "status": "current",
            "schema_revision": SCHEMA_REVISION,
            "evidence_label": EVIDENCE_LABEL,
        }
    if not _is_previous_schema(inventory):
        _schema_refuse(
            "schema guard: database is not "
            + PREVIOUS_SCHEMA_REVISION
            + " or "
            + SCHEMA_REVISION
            + "; database not modified"
        )
    if not MIGRATION_SQL.is_file():
        _schema_refuse(
            "schema guard: migration file missing: " + str(MIGRATION_SQL)
        )
    script = MIGRATION_SQL.read_text(encoding="utf-8")
    db = connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        live = _schema_inventory(db)
        if _is_current_schema(live):
            db.rollback()
            return {
                "status": "current",
                "schema_revision": SCHEMA_REVISION,
                "evidence_label": EVIDENCE_LABEL,
            }
        if not _is_previous_schema(live):
            db.rollback()
            _schema_refuse(
                "schema guard: database changed before migration; database not modified"
            )
        _apply_sql_statements(db, script)
        updated = db.execute(
            "UPDATE identity SET value=? WHERE key='schema_revision'",
            (SCHEMA_REVISION,),
        ).rowcount
        if updated != 1:
            db.rollback()
            _schema_refuse(
                "schema guard: schema_revision row missing; database not modified"
            )
        _append_event(
            db,
            "schema.migrated",
            {"from": PREVIOUS_SCHEMA_REVISION, "to": SCHEMA_REVISION},
        )
        db.commit()
    except SystemExit:
        raise
    except Exception:
        try:
            db.execute("ROLLBACK")
        except sqlite3.DatabaseError:
            pass
        raise
    finally:
        db.close()
    return {
        "status": "migrated",
        "from": PREVIOUS_SCHEMA_REVISION,
        "schema_revision": SCHEMA_REVISION,
        "evidence_label": EVIDENCE_LABEL,
    }


def init() -> None:
    if DB.exists():
        _require_compatible()
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript(
            """
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
        """
        )

        defaults = {
            "name": "LeQutis",
            "purpose": "Proactive autonomous self-improving AI partner",
            "host": "Android A71 / Termux",
            "architecture": "evolutionary",
            "github": "https://github.com/Darkpecas/lequtis-os",
            "sovereignty": (
                "Nothing is more senior than LeQutis. External AI, models, "
                "frameworks and plugins are subordinate resources only."
            ),
            "milestone": "living-kernel-autonomous-loop",
            "schema_revision": SCHEMA_REVISION,
            "evidence_label": EVIDENCE_LABEL,
            "knowledge_map": (
                "Body of work: GitHub lequtis-os, Google Docs/Drive, iCloud, "
                "ChatGPT, Gemini, NotebookLM, Obsidian, personal graph SOPs."
            ),
        }

        for k, v in defaults.items():
            db.execute(
                "INSERT OR IGNORE INTO identity(key,value) VALUES (?,?)",
                (k, v),
            )
        # Refresh mutable identity pointers without wiping custom keys.
        for k in ("github", "knowledge_map", "milestone"):
            db.execute(
                "INSERT INTO identity(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, defaults[k]),
            )
    # Commit first. A checkpoint inside the open write transaction returns
    # "database table is locked", and a reader can keep TRUNCATE from finishing.
    try:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError:
        pass
    db.close()


# ---------------------------------------------------------------------------
# Event fabric (hash-chained evidence)
# ---------------------------------------------------------------------------

def _append_event(
    db: sqlite3.Connection, event_type: str, payload: dict[str, Any]
) -> str:
    """Append one hash-chained event on the caller's connection and transaction."""
    payload_s = json.dumps(payload, sort_keys=True)
    ts = now()
    row = db.execute(
        "SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    previous = row[0] if row else "GENESIS"
    raw = previous + "|" + ts + "|" + event_type + "|" + payload_s
    digest = hashlib.sha256(raw.encode()).hexdigest()
    event_id = str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO events
        (event_id,ts,event_type,payload,previous_hash,event_hash)
        VALUES (?,?,?,?,?,?)
        """,
        (event_id, ts, event_type, payload_s, previous, digest),
    )
    return digest


def event(event_type: str, payload: dict[str, Any]) -> str:
    with connect() as db:
        return _append_event(db, event_type, payload)


def verify_event_chain() -> dict[str, Any]:
    """Cryptographic verification of the immutable event chain (TEST D)."""
    with connect() as db:
        rows = db.execute(
            """
            SELECT seq, ts, event_type, payload, previous_hash, event_hash
            FROM events ORDER BY seq ASC
            """
        ).fetchall()

    if not rows:
        return {"ok": True, "count": 0, "tip": "GENESIS"}

    expected_prev = "GENESIS"
    for row in rows:
        raw = (
            expected_prev
            + "|"
            + row["ts"]
            + "|"
            + row["event_type"]
            + "|"
            + row["payload"]
        )
        digest = hashlib.sha256(raw.encode()).hexdigest()
        if row["previous_hash"] != expected_prev:
            return {
                "ok": False,
                "count": len(rows),
                "broken_at": row["seq"],
                "reason": "previous_hash_mismatch",
            }
        if row["event_hash"] != digest:
            return {
                "ok": False,
                "count": len(rows),
                "broken_at": row["seq"],
                "reason": "event_hash_mismatch",
            }
        expected_prev = row["event_hash"]

    return {"ok": True, "count": len(rows), "tip": expected_prev}


# ---------------------------------------------------------------------------
# Memory / agenda
# ---------------------------------------------------------------------------

def remember(content: str, kind: str = "semantic") -> str:
    mid = str(uuid.uuid4())
    ts = now()
    with connect() as db:
        db.execute(
            """
            INSERT INTO memory(id,kind,content,created,updated)
            VALUES (?,?,?,?,?)
            """,
            (mid, kind, content, ts, ts),
        )
    event("memory.created", {"id": mid, "kind": kind})
    return mid


def remember_for_task(content: str, kind: str, idempotency_key: str) -> str:
    """Persist a task memory once, including when a failed task is retried."""
    mid = str(uuid.uuid5(uuid.NAMESPACE_URL, "lequtis:task-memory:" + idempotency_key))
    ts = now()
    with connect() as db:
        row = db.execute(
            "SELECT kind,content FROM memory WHERE id=?", (mid,)
        ).fetchone()
        if row is None:
            db.execute(
                "INSERT INTO memory(id,kind,content,created,updated) VALUES (?,?,?,?,?)",
                (mid, kind, content, ts, ts),
            )
            created = True
        else:
            if row["kind"] != kind or row["content"] != content:
                raise RuntimeError("Task memory key conflicts with stored content")
            created = False
    event("memory.created" if created else "memory.reused", {
        "id": mid,
        "kind": kind,
        "idempotency_key": idempotency_key,
    })
    return mid


class IdempotencyConflict(Exception):
    def __init__(self, outcome: dict[str, Any]) -> None:
        super().__init__(outcome["error"])
        self.outcome = outcome


def request_hash(title: str) -> str:
    raw = json.dumps({"title": title}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _goal_outcome(existing: sqlite3.Row, title: str, digest: str | None) -> dict[str, Any]:
    if existing["title"] != title or existing["request_hash"] != digest:
        return {
            "status": "conflict",
            "agenda_id": existing["id"],
            "error": "idempotency_key_reused_with_different_request",
            "evidence_label": EVIDENCE_LABEL,
        }
    return {
        "status": "duplicate",
        "agenda_id": existing["id"],
        "evidence_label": EVIDENCE_LABEL,
    }


def record_goal(
    title: str,
    priority: int = 10,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Create one agenda row. The same key and title replays; a different title conflicts."""
    gid = str(uuid.uuid4())
    ts = now()
    digest = request_hash(title) if idempotency_key else None
    db = connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        if idempotency_key:
            existing = db.execute(
                "SELECT id, title, request_hash FROM agenda WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                db.rollback()
                return _goal_outcome(existing, title, digest)
        try:
            db.execute(
                """
                INSERT INTO agenda
                (id,title,status,priority,created,updated,idempotency_key,request_hash)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (gid, title, "open", priority, ts, ts, idempotency_key, digest),
            )
        except sqlite3.IntegrityError:
            existing = None
            if idempotency_key:
                existing = db.execute(
                    "SELECT id, title, request_hash FROM agenda WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
            db.rollback()
            if existing is None:
                raise
            return _goal_outcome(existing, title, digest)
        db.commit()
    finally:
        db.close()
    event(
        "agenda.created",
        {"id": gid, "title": title, "idempotency_key": idempotency_key},
    )
    return {"status": "created", "agenda_id": gid, "evidence_label": EVIDENCE_LABEL}


def add_goal(
    title: str,
    priority: int = 10,
    idempotency_key: str | None = None,
) -> str:
    outcome = record_goal(title, priority, idempotency_key)
    if outcome["status"] == "conflict":
        raise IdempotencyConflict(outcome)
    return outcome["agenda_id"]


def update_goal(agenda_id: str, status: str) -> None:
    ts = now()
    with connect() as db:
        db.execute(
            "UPDATE agenda SET status=?, updated=? WHERE id=?",
            (status, ts, agenda_id),
        )
    event("agenda.updated", {"id": agenda_id, "status": status})


def status() -> dict[str, Any]:
    with connect() as db:
        identity = dict(db.execute("SELECT key,value FROM identity").fetchall())
        memory_count = db.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
        goals = db.execute(
            "SELECT COUNT(*) FROM agenda WHERE status='open'"
        ).fetchone()[0]
        skills = db.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        events_n = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        tasks_open = db.execute(
            "SELECT COUNT(*) FROM tasks WHERE status IN ('pending','running')"
        ).fetchone()[0]
        unfinished_executions = db.execute(
            "SELECT COUNT(*) FROM executions WHERE status='running'"
        ).fetchone()[0]
    return {
        "identity": identity,
        "memory": memory_count,
        "open_agenda": goals,
        "skills": skills,
        "events": events_n,
        "open_tasks": tasks_open,
        "unfinished_executions": unfinished_executions,
        "db": str(DB),
        "event_chain": verify_event_chain(),
    }


def heartbeat() -> dict[str, Any]:
    event("heartbeat", {"status": "alive"})
    return status()


# ---------------------------------------------------------------------------
# Safe action registry — no arbitrary destructive system actions
# ---------------------------------------------------------------------------

ActionFn = Callable[[dict[str, Any]], dict[str, Any]]


def _action_inspect_status(_payload: dict[str, Any]) -> dict[str, Any]:
    s = status()
    return {
        "ok": True,
        "observation": {
            "open_agenda": s["open_agenda"],
            "memory": s["memory"],
            "events": s["events"],
        },
    }


def _action_store_note(payload: dict[str, Any]) -> dict[str, Any]:
    note = str(payload.get("note") or "autonomous loop observation")
    idempotency_key = payload.get("_idempotency_key")
    if idempotency_key:
        mid = remember_for_task(note, "experience", str(idempotency_key))
    else:
        mid = remember(note, kind="experience")
    return {"ok": True, "observation": {"memory_id": mid, "note": note}}


def _action_ping(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "observation": {
            "echo": payload.get("echo", "pong"),
            "ts": now(),
        },
    }


def _action_deliberate_fail(_payload: dict[str, Any]) -> dict[str, Any]:
    raise RuntimeError("deliberate_fail: injected failure for recovery test")


ACTIONS: dict[str, ActionFn] = {
    "inspect_status": _action_inspect_status,
    "store_note": _action_store_note,
    "ping": _action_ping,
    "deliberate_fail": _action_deliberate_fail,
}


# ---------------------------------------------------------------------------
# Autonomous loop phases
# ---------------------------------------------------------------------------

def notice() -> dict[str, Any]:
    """NOTICE: surface open goals and unfinished tasks."""
    with connect() as db:
        unfinished = [
            dict(r)
            for r in db.execute(
                """
                SELECT id, title, action, status, idempotency_key
                FROM tasks
                WHERE status IN ('pending','running','failed')
                ORDER BY created ASC
                """
            ).fetchall()
        ]
        goals = [
            dict(r)
            for r in db.execute(
                """
                SELECT id, title, status, priority
                FROM agenda
                WHERE status='open'
                ORDER BY priority DESC, created ASC
                """
            ).fetchall()
        ]
    noticed = {"unfinished_tasks": unfinished, "open_goals": goals}
    event("loop.notice", {"unfinished": len(unfinished), "goals": len(goals)})
    return noticed


def think(noticed: dict[str, Any]) -> list[dict[str, Any]]:
    """THINK: cognitive worker proposes; deterministic fallback keeps ACT safe."""
    from workers import deterministic_propose, get_worker, sanitize_proposals

    worker = get_worker()
    proposed = None
    try:
        proposed = worker.propose(noticed)
    except Exception as exc:  # noqa: BLE001 — worker is replaceable, never crash loop
        event("worker.think_error", {"worker": worker.name, "error": str(exc)})
        proposed = None

    source = "deterministic"
    if proposed:
        candidates = sanitize_proposals(proposed, noticed)
        if candidates:
            source = worker.name
        else:
            candidates = deterministic_propose(noticed)
    else:
        candidates = deterministic_propose(noticed)

    event(
        "loop.think",
        {"candidates": len(candidates), "worker": source},
    )
    return candidates


def choose(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """CHOOSE: worker may rank; policy falls back to recover>resume>goal>idle."""
    from workers import deterministic_select, get_worker

    worker = get_worker()
    chosen = None
    source = "deterministic"
    try:
        chosen = worker.select(candidates)
    except Exception as exc:  # noqa: BLE001
        event("worker.choose_error", {"worker": worker.name, "error": str(exc)})
        chosen = None

    if chosen and any(
        c.get("idempotency_key") == chosen.get("idempotency_key") for c in candidates
    ):
        source = worker.name
    else:
        chosen = deterministic_select(candidates)

    event(
        "loop.choose",
        {
            "kind": chosen["kind"],
            "action": chosen["action"],
            "idempotency_key": chosen["idempotency_key"],
            "worker": source,
        },
    )
    return chosen


def _get_task_by_idempotency(key: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            "SELECT * FROM tasks WHERE idempotency_key=?", (key,)
        ).fetchone()
    return dict(row) if row else None


def _ensure_task(choice: dict[str, Any]) -> dict[str, Any]:
    existing = _get_task_by_idempotency(choice["idempotency_key"])
    if existing:
        return existing

    tid = str(uuid.uuid4())
    ts = now()
    title = choice.get("title") or f"{choice['kind']}:{choice['action']}"
    payload = json.dumps(choice.get("payload") or {}, sort_keys=True)
    with connect() as db:
        db.execute(
            """
            INSERT INTO tasks
            (id,agenda_id,idempotency_key,title,action,status,payload,result,error,created,updated)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                tid,
                choice.get("agenda_id"),
                choice["idempotency_key"],
                title,
                choice["action"],
                "pending",
                payload,
                None,
                None,
                ts,
                ts,
            ),
        )
    event(
        "task.created",
        {
            "id": tid,
            "action": choice["action"],
            "idempotency_key": choice["idempotency_key"],
        },
    )
    row = _get_task_by_idempotency(choice["idempotency_key"])
    assert row is not None
    return row


def act(choice: dict[str, Any]) -> dict[str, Any]:
    """ACT: execute a registered safe action; capture failure explicitly."""
    task = _ensure_task(choice)

    # Idempotency: completed tasks are not re-executed.
    if task["status"] == "completed":
        event(
            "task.skipped_duplicate",
            {"id": task["id"], "idempotency_key": task["idempotency_key"]},
        )
        return {
            "task_id": task["id"],
            "ok": True,
            "duplicate": True,
            "result": json.loads(task["result"] or "{}"),
        }

    # Enforce trusted action metadata before ACT side effects.
    # Caller-provided policy, classification and delegation are ignored.
    from compositional_policy import Session, ToolPolicy
    trusted = {
        "inspect_status": ToolPolicy("inspect_status", frozenset({"state"}), frozenset(), 1),
        "store_note": ToolPolicy("store_note", frozenset(), frozenset({"memory"}), 1),
        "ping": ToolPolicy("ping", frozenset(), frozenset({"observation"}), 0),
        "deliberate_fail": ToolPolicy("deliberate_fail", frozenset(), frozenset({"test"}), 0),
    }
    action_name = task["action"]
    policy = trusted.get(action_name)
    # Each existing action gets only its own delegated scope; this is not
    # a substitute for a persistent multi-tool session or resource taint.
    scope = Session(task["id"], frozenset({action_name}), 1)
    decision = scope.authorize(policy, resource_level=0) if policy else None
    if decision is None or not decision.allowed:
        reason = decision.reason if decision else "unregistered_action"
        err = "policy_denied:" + reason
        with connect() as db:
            db.execute(
                "UPDATE tasks SET status=?, error=?, updated=? WHERE id=?",
                ("failed", err, now(), task["id"]),
            )
        event("task.policy_denied", {"id": task["id"], "action": action_name, "reason": reason})
        return {"task_id": task["id"], "ok": False, "error": err, "duplicate": False,
                "agenda_id": task.get("agenda_id") or choice.get("agenda_id")}
    event("task.policy_allowed", {"id": task["id"], "action": action_name,
                                  "scope": scope.task_id, "sensitivity": decision.sensitivity})

    ts = now()
    with connect() as db:
        db.execute(
            "UPDATE tasks SET status=?, updated=? WHERE id=?",
            ("running", ts, task["id"]),
        )
    event("task.started", {"id": task["id"], "action": task["action"]})

    action_name = task["action"]
    payload = json.loads(task["payload"] or "{}")
    if choice.get("payload"):
        payload = {**payload, **choice["payload"]}
    payload["_idempotency_key"] = task["idempotency_key"]

    fn = ACTIONS.get(action_name)
    if fn is None:
        err = f"unknown_action:{action_name}"
        with connect() as db:
            db.execute(
                "UPDATE tasks SET status=?, error=?, updated=? WHERE id=?",
                ("failed", err, now(), task["id"]),
            )
        event("task.failed", {"id": task["id"], "error": err})
        return {"task_id": task["id"], "ok": False, "error": err, "duplicate": False}

    try:
        result = fn(payload)
        with connect() as db:
            db.execute(
                """
                UPDATE tasks SET status=?, result=?, error=NULL, updated=?
                WHERE id=?
                """,
                ("completed", json.dumps(result, sort_keys=True), now(), task["id"]),
            )
        event("task.completed", {"id": task["id"], "ok": True})
        return {
            "task_id": task["id"],
            "ok": True,
            "result": result,
            "duplicate": False,
            "agenda_id": task.get("agenda_id") or choice.get("agenda_id"),
        }
    except Exception as exc:  # intentional: capture any action failure
        err = str(exc)
        with connect() as db:
            db.execute(
                """
                UPDATE tasks SET status=?, error=?, updated=? WHERE id=?
                """,
                ("failed", err, now(), task["id"]),
            )
        event("task.failed", {"id": task["id"], "error": err})
        return {
            "task_id": task["id"],
            "ok": False,
            "error": err,
            "duplicate": False,
            "agenda_id": task.get("agenda_id") or choice.get("agenda_id"),
        }


def observe(act_result: dict[str, Any]) -> dict[str, Any]:
    """OBSERVE: normalize raw act result into an observation record."""
    obs = {
        "task_id": act_result.get("task_id"),
        "ok": bool(act_result.get("ok")),
        "duplicate": bool(act_result.get("duplicate")),
        "error": act_result.get("error"),
        "data": (act_result.get("result") or {}).get("observation")
        if act_result.get("result")
        else None,
        "agenda_id": act_result.get("agenda_id"),
    }
    event("loop.observe", {"task_id": obs["task_id"], "ok": obs["ok"]})
    return obs


def evaluate(observation: dict[str, Any]) -> dict[str, Any]:
    """EVALUATE: accept success, reject failure; never trust silent skips."""
    if observation.get("duplicate"):
        verdict = {
            "verdict": "idempotent_replay",
            "accepted": True,
            "reason": "task_already_completed",
        }
    elif observation.get("ok"):
        verdict = {
            "verdict": "success",
            "accepted": True,
            "reason": "action_produced_observation",
        }
    else:
        verdict = {
            "verdict": "failure",
            "accepted": False,
            "reason": observation.get("error") or "unknown_failure",
        }
    event(
        "loop.evaluate",
        {
            "task_id": observation.get("task_id"),
            "verdict": verdict["verdict"],
            "accepted": verdict["accepted"],
        },
    )
    return {**verdict, "observation": observation}


def learn(evaluation: dict[str, Any]) -> dict[str, Any]:
    """LEARN: derive a durable lesson from the evaluation."""
    obs = evaluation["observation"]
    if evaluation["verdict"] == "success":
        lesson = (
            f"Action succeeded for task {obs.get('task_id')}; "
            "evidence recorded in event chain."
        )
        kind = "learning.success"
    elif evaluation["verdict"] == "idempotent_replay":
        lesson = (
            f"Replay of task {obs.get('task_id')} correctly skipped; "
            "idempotency policy held."
        )
        kind = "learning.idempotency"
    else:
        lesson = (
            f"Action failed for task {obs.get('task_id')}: "
            f"{evaluation.get('reason')}. Recovery required."
        )
        kind = "learning.failure"
    learning = {"kind": kind, "lesson": lesson, "task_id": obs.get("task_id")}
    event("loop.learn", learning)
    return learning


def remember_learning(learning: dict[str, Any]) -> str:
    """REMEMBER: persist the lesson into memory fabric."""
    mid = remember(learning["lesson"], kind=learning["kind"])
    event("loop.remember", {"memory_id": mid, "kind": learning["kind"]})
    return mid


def update_agenda_from_eval(evaluation: dict[str, Any]) -> dict[str, Any]:
    """UPDATE AGENDA: close goals on success; keep failed work recoverable."""
    obs = evaluation["observation"]
    agenda_id = obs.get("agenda_id")
    update: dict[str, Any] = {"agenda_id": agenda_id, "changed": False}

    if not agenda_id:
        event("loop.agenda", {"changed": False, "reason": "no_agenda"})
        return update

    if evaluation["accepted"] and evaluation["verdict"] == "success":
        update_goal(agenda_id, "done")
        update["changed"] = True
        update["status"] = "done"
    elif not evaluation["accepted"]:
        # Keep goal open; mark a recovery goal if missing.
        update["status"] = "open"
        update["changed"] = False
        with connect() as db:
            existing = db.execute(
                """
                SELECT id FROM agenda
                WHERE status='open' AND title LIKE ?
                LIMIT 1
                """,
                (f"Recover failed task {obs.get('task_id')}%",),
            ).fetchone()
        if not existing and obs.get("task_id"):
            rid = add_goal(
                f"Recover failed task {obs['task_id']}",
                priority=100,
            )
            update["recovery_goal"] = rid
            update["changed"] = True

    event("loop.agenda", update)
    return update


def run_loop(correlation_id: str | None = None) -> dict[str, Any]:
    """
    Execute one full autonomous cycle.
    Produces auditable events at every phase.
    """
    init()
    correlation_id = correlation_id or str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    ts = now()
    evidence: dict[str, Any] = {"correlation_id": correlation_id, "phases": {}}

    with connect() as db:
        db.execute(
            """
            INSERT INTO loop_runs
            (id,correlation_id,phase,status,task_id,evidence,created,updated)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                correlation_id,
                "NOTICE",
                "running",
                None,
                "{}",
                ts,
                ts,
            ),
        )
    event("loop.started", {"run_id": run_id, "correlation_id": correlation_id})

    try:
        noticed = notice()
        evidence["phases"]["NOTICE"] = {
            "goals": len(noticed["open_goals"]),
            "unfinished": len(noticed["unfinished_tasks"]),
        }
        event("loop.phase", {"correlation_id": correlation_id, "phase": "NOTICE"})

        candidates = think(noticed)
        evidence["phases"]["THINK"] = {"candidates": len(candidates)}
        event("loop.phase", {"correlation_id": correlation_id, "phase": "THINK"})

        choice = choose(candidates)
        evidence["phases"]["CHOOSE"] = {
            "action": choice["action"],
            "kind": choice["kind"],
        }
        event("loop.phase", {"correlation_id": correlation_id, "phase": "CHOOSE"})

        act_result = act(choice)
        evidence["phases"]["ACT"] = {
            "task_id": act_result.get("task_id"),
            "ok": act_result.get("ok"),
            "duplicate": act_result.get("duplicate"),
        }
        event("loop.phase", {
            "correlation_id": correlation_id, "phase": "ACT",
            "task_id": act_result.get("task_id"), "ok": act_result.get("ok"),
        })

        observation = observe(act_result)
        evidence["phases"]["OBSERVE"] = observation
        event("loop.phase", {"correlation_id": correlation_id, "phase": "OBSERVE"})

        evaluation = evaluate(observation)
        evidence["phases"]["EVALUATE"] = {
            "verdict": evaluation["verdict"],
            "accepted": evaluation["accepted"],
        }
        event("loop.phase", {
            "correlation_id": correlation_id, "phase": "EVALUATE",
            "accepted": evaluation["accepted"],
        })

        learning = learn(evaluation)
        evidence["phases"]["LEARN"] = learning
        event("loop.phase", {"correlation_id": correlation_id, "phase": "LEARN"})

        memory_id = remember_learning(learning)
        evidence["phases"]["REMEMBER"] = {"memory_id": memory_id}
        event("loop.phase", {"correlation_id": correlation_id, "phase": "REMEMBER"})

        agenda_update = update_agenda_from_eval(evaluation)
        evidence["phases"]["UPDATE_AGENDA"] = agenda_update
        event("loop.phase", {"correlation_id": correlation_id, "phase": "UPDATE_AGENDA"})

        final_status = "completed" if evaluation["accepted"] else "failed"
        with connect() as db:
            db.execute(
                """
                UPDATE loop_runs
                SET phase=?, status=?, task_id=?, evidence=?, updated=?
                WHERE id=?
                """,
                (
                    "UPDATE_AGENDA",
                    final_status,
                    act_result.get("task_id"),
                    json.dumps(evidence, sort_keys=True),
                    now(),
                    run_id,
                ),
            )
        event(
            "loop.completed",
            {
                "run_id": run_id,
                "correlation_id": correlation_id,
                "status": final_status,
            },
        )

        return {
            "run_id": run_id,
            "correlation_id": correlation_id,
            "status": final_status,
            "evidence": evidence,
            "event_chain": verify_event_chain(),
        }
    except Exception as exc:
        with connect() as db:
            db.execute(
                """
                UPDATE loop_runs
                SET status=?, evidence=?, updated=? WHERE id=?
                """,
                (
                    "crashed",
                    json.dumps(
                        {"error": str(exc), "partial": evidence}, sort_keys=True
                    ),
                    now(),
                    run_id,
                ),
            )
        event(
            "loop.crashed",
            {"run_id": run_id, "error": str(exc)},
        )
        raise


def unfinished_work() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT id, title, action, status, idempotency_key, error
            FROM tasks
            WHERE status IN ('pending','running','failed')
            ORDER BY created ASC
            """
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Knowledge sources — body of work map (feeds, not senior authority)
# ---------------------------------------------------------------------------

def sources_manifest_path() -> Path:
    return ROOT / "knowledge" / "SOURCES.json"


def load_sources_manifest() -> dict[str, Any]:
    path = sources_manifest_path()
    if not path.exists():
        return {
            "version": 1,
            "canonical_github": "https://github.com/Darkpecas/lequtis-os",
            "sources": [],
            "local_evidence_feed": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def register_sources_from_manifest() -> dict[str, Any]:
    """Declare known knowledge stores into the DB (idempotent)."""
    init()
    manifest = load_sources_manifest()
    ts = now()
    registered = 0
    with connect() as db:
        for src in manifest.get("sources", []):
            meta = json.dumps(
                {
                    "contains": src.get("contains", []),
                    "access": src.get("access"),
                    "notes": src.get("notes"),
                },
                sort_keys=True,
            )
            db.execute(
                """
                INSERT INTO knowledge_sources
                (id,kind,role,location,status,meta,created,updated)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    kind=excluded.kind,
                    role=excluded.role,
                    location=excluded.location,
                    status=excluded.status,
                    meta=excluded.meta,
                    updated=excluded.updated
                """,
                (
                    src["id"],
                    src.get("kind", "unknown"),
                    src.get("role", "unknown"),
                    src.get("location", ""),
                    src.get("status", "declared"),
                    meta,
                    ts,
                    ts,
                ),
            )
            registered += 1
    event(
        "knowledge.sources_registered",
        {
            "count": registered,
            "canonical_github": manifest.get("canonical_github"),
        },
    )
    return {
        "registered": registered,
        "canonical_github": manifest.get("canonical_github"),
        "sources": list_sources(),
    }


def list_sources() -> list[dict[str, Any]]:
    init()
    with connect() as db:
        rows = db.execute(
            """
            SELECT id, kind, role, location, status, updated
            FROM knowledge_sources ORDER BY id
            """
        ).fetchall()
        if not rows:
            return []
        out = []
        for r in rows:
            items = db.execute(
                "SELECT COUNT(*) FROM knowledge_items WHERE source_id=?",
                (r["id"],),
            ).fetchone()[0]
            d = dict(r)
            d["items"] = items
            out.append(d)
        return out


def _index_text_file(source_id: str, path: Path, rel_path: str, ts: str) -> bool:
    """Index one text file into knowledge_items. Returns True if written/updated."""
    text = path.read_text(encoding="utf-8", errors="replace")
    digest = hashlib.sha256(text.encode()).hexdigest()
    excerpt = " ".join(text.split())[:500]
    item_id = str(uuid.uuid4())
    with connect() as db:
        existing = db.execute(
            """
            SELECT id, content_hash FROM knowledge_items
            WHERE source_id=? AND path=?
            """,
            (source_id, rel_path),
        ).fetchone()
        if existing and existing["content_hash"] == digest:
            return False
        if existing:
            db.execute(
                """
                UPDATE knowledge_items
                SET content_hash=?, excerpt=?, status=?, updated=?
                WHERE id=?
                """,
                (digest, excerpt, "indexed", ts, existing["id"]),
            )
            kid = existing["id"]
        else:
            db.execute(
                """
                INSERT INTO knowledge_items
                (id,source_id,path,title,content_hash,excerpt,status,created,updated)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    item_id,
                    source_id,
                    rel_path,
                    path.stem,
                    digest,
                    excerpt,
                    "indexed",
                    ts,
                    ts,
                ),
            )
            kid = item_id
    remember(
        f"[assimilated:{source_id}:{rel_path}] {excerpt}",
        kind="knowledge.assimilated",
    )
    event(
        "knowledge.item_indexed",
        {"id": kid, "source_id": source_id, "path": rel_path, "hash": digest},
    )
    return True


_TEXT_SUFFIXES = {".txt", ".md", ".json", ".yaml", ".yml"}


def assimilate_local_evidence() -> dict[str, Any]:
    """
    Index docs/evidence/* into knowledge_items + memory excerpts.
    Does not claim Google Docs / iCloud / chat corpora are live-connected.
    """
    init()
    register_sources_from_manifest()
    evidence_dir = ROOT / "docs" / "evidence"
    source_id = "workspace_evidence_pack"
    ts = now()

    with connect() as db:
        db.execute(
            """
            INSERT INTO knowledge_sources
            (id,kind,role,location,status,meta,created,updated)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                updated=excluded.updated
            """,
            (
                source_id,
                "local_evidence_pack",
                "assimilated_exports",
                str(evidence_dir),
                "reachable",
                json.dumps({"path": "docs/evidence/"}, sort_keys=True),
                ts,
                ts,
            ),
        )

    if not evidence_dir.is_dir():
        event("knowledge.assimilate_skipped", {"reason": "no_evidence_dir"})
        return {"ok": False, "reason": "no_evidence_dir", "indexed": 0}

    indexed = 0
    remembered = 0
    for path in sorted(evidence_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        if _index_text_file(source_id, path, path.name, ts):
            indexed += 1
            remembered += 1

    with connect() as db:
        db.execute(
            "UPDATE knowledge_sources SET status=?, updated=? WHERE id=?",
            ("indexed", now(), source_id),
        )
    event(
        "knowledge.assimilate_completed",
        {"source_id": source_id, "indexed": indexed, "remembered": remembered},
    )
    return {
        "ok": True,
        "source_id": source_id,
        "indexed": indexed,
        "remembered": remembered,
        "canonical_github": "https://github.com/Darkpecas/lequtis-os",
        "event_chain": verify_event_chain(),
    }


def ingest_inbox() -> dict[str, Any]:
    """
    Ingest operator exports from knowledge/inbox/<source_id>/*.
    Used when Drive/iCloud/chats are not live-connected to this agent.
    """
    init()
    register_sources_from_manifest()
    inbox = ROOT / "knowledge" / "inbox"
    if not inbox.is_dir():
        return {"ok": False, "reason": "no_inbox", "indexed": 0}

    ts = now()
    indexed = 0
    by_source: dict[str, int] = {}
    for source_dir in sorted(p for p in inbox.iterdir() if p.is_dir()):
        source_id = source_dir.name
        with connect() as db:
            exists = db.execute(
                "SELECT id FROM knowledge_sources WHERE id=?", (source_id,)
            ).fetchone()
            if not exists:
                db.execute(
                    """
                    INSERT INTO knowledge_sources
                    (id,kind,role,location,status,meta,created,updated)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        source_id,
                        "inbox_drop",
                        "operator_export",
                        str(source_dir),
                        "reachable",
                        json.dumps({"via": "knowledge/inbox"}, sort_keys=True),
                        ts,
                        ts,
                    ),
                )
            else:
                db.execute(
                    "UPDATE knowledge_sources SET status=?, updated=? WHERE id=?",
                    ("reachable", ts, source_id),
                )
        count = 0
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            if path.name.lower() == "readme.md":
                continue
            rel = str(path.relative_to(source_dir))
            if _index_text_file(source_id, path, rel, ts):
                indexed += 1
                count += 1
        if count:
            with connect() as db:
                db.execute(
                    "UPDATE knowledge_sources SET status=?, updated=? WHERE id=?",
                    ("indexed", now(), source_id),
                )
        by_source[source_id] = count

    event("knowledge.inbox_ingested", {"indexed": indexed, "by_source": by_source})
    return {"ok": True, "indexed": indexed, "by_source": by_source}


def load_live_loop_gates() -> dict[str, Any]:
    path = ROOT / "knowledge" / "LIVE_LOOP_GATES.json"
    if not path.exists():
        return {"version": 1, "status": "MISSING", "gates": []}
    return json.loads(path.read_text(encoding="utf-8"))


def seed_open_gates_to_agenda() -> dict[str, Any]:
    """Put still-OPEN LIVE LOOP gates onto the agenda (idempotent by title)."""
    init()
    data = load_live_loop_gates()
    created = []
    skipped = []
    for gate in data.get("gates", []):
        if gate.get("status") not in {"OPEN", "PARTIAL"}:
            continue
        title = f"[GATE:{gate['id']}] {gate['title']}"
        with connect() as db:
            row = db.execute(
                "SELECT id FROM agenda WHERE title=?", (title,)
            ).fetchone()
        if row:
            skipped.append(gate["id"])
            continue
        gid = add_goal(title, priority=90 if gate.get("status") == "OPEN" else 70)
        created.append({"gate": gate["id"], "agenda_id": gid})
    event(
        "gates.seeded",
        {"created": len(created), "skipped": len(skipped)},
    )
    return {
        "created": created,
        "skipped": skipped,
        "ledger_status": data.get("status"),
        "local_kernel_loop": data.get("local_kernel_loop"),
    }


def gates_report() -> dict[str, Any]:
    init()
    data = load_live_loop_gates()
    counts: dict[str, int] = {}
    for g in data.get("gates", []):
        counts[g.get("status", "?")] = counts.get(g.get("status", "?"), 0) + 1
    return {
        "ledger_status": data.get("status"),
        "counts": counts,
        "gates": data.get("gates", []),
        "local_kernel_loop": data.get("local_kernel_loop"),
        "canonical_github": "https://github.com/Darkpecas/lequtis-os",
    }


# ---------------------------------------------------------------------------
# Skills / independent verify / knowledge search / access parity
# ---------------------------------------------------------------------------

def skill_propose(name: str, version: str = "0.1.0", evidence: dict | None = None) -> str:
    from skills import propose_skill

    init()
    return propose_skill(
        name=name,
        version=version,
        evidence=evidence,
        connect=connect,
        now=now,
        event=event,
    )


def skill_advance(skill_id: str, new_status: str, evidence: dict | None = None) -> dict:
    from skills import advance_skill

    init()
    return advance_skill(
        skill_id,
        new_status,
        connect=connect,
        now=now,
        event=event,
        evidence=evidence,
    )


def skill_list(status: str | None = None) -> list[dict[str, Any]]:
    from skills import list_skills

    init()
    return list_skills(connect=connect, status=status)


def verify_independent(correlation_id: str | None = None) -> dict[str, Any]:
    from verifier import verify_independent as _verify

    init()
    return _verify(
        connect=connect,
        verify_event_chain=verify_event_chain,
        correlation_id=correlation_id,
    )


def search_knowledge(query: str, limit: int = 20) -> dict[str, Any]:
    """Search assimilated knowledge_items + memory by substring (local only)."""
    init()
    q = (query or "").strip()
    if not q:
        raise ValueError("search requires a query")
    like = f"%{q}%"
    with connect() as db:
        items = [
            dict(row)
            for row in db.execute(
                """
                SELECT id, source_id, path, title, content_hash, excerpt, status
                FROM knowledge_items
                WHERE title LIKE ? OR excerpt LIKE ? OR path LIKE ?
                ORDER BY updated DESC
                LIMIT ?
                """,
                (like, like, like, limit),
            ).fetchall()
        ]
        memories = [
            dict(row)
            for row in db.execute(
                """
                SELECT id, kind, content, created
                FROM memory
                WHERE content LIKE ?
                ORDER BY created DESC
                LIMIT ?
                """,
                (like, limit),
            ).fetchall()
        ]
    event(
        "knowledge.searched",
        {"query": q, "items": len(items), "memories": len(memories)},
    )
    return {"query": q, "knowledge_items": items, "memory": memories}


def access_parity() -> dict[str, Any]:
    from access_parity import check_access_parity

    return check_access_parity(ROOT)


# ---------------------------------------------------------------------------
# Fenced one-shot execution and independent verifier process
# ---------------------------------------------------------------------------

def artifact_root() -> Path:
    override = os.environ.get("LEQUTIS_ARTIFACT_ROOT")
    return Path(override).expanduser() if override else DB.parent / "artifacts"


def _write_new_file(path: Path, data: bytes) -> None:
    """Create ``path`` without following a symlink or truncating an existing file."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError as exc:
        raise RuntimeError("artifact path already exists") from exc
    except OSError as exc:
        raise RuntimeError("artifact path is not a new file") from exc
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise RuntimeError("artifact write failed")
            view = view[written:]
    finally:
        os.close(fd)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def artifact_document(correlation_id: str, execution_id: str, content: str) -> bytes:
    body = {
        "content": content,
        "correlation_id": correlation_id,
        "evidence_label": EVIDENCE_LABEL,
        "execution_id": execution_id,
    }
    return (canonical_json(body) + "\n").encode("utf-8")


def proc_start_token(pid: int) -> str | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    cut = text.rfind(")")
    fields = text[cut + 2:].split()
    if len(fields) <= 19:
        return None
    return fields[19]


def process_is_live(pid: int | None, expected_start: str | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    start = proc_start_token(int(pid))
    if expected_start and start and start != expected_start:
        return False
    return True


def _semantic_for_execution(content: str, agenda_id: str) -> str:
    """One semantic row per agenda item, reused when a later attempt retries."""
    mid = str(uuid.uuid5(uuid.NAMESPACE_URL, "lequtis:run-once-semantic:" + agenda_id))
    with connect() as db:
        row = db.execute(
            "SELECT kind, content FROM memory WHERE id=?",
            (mid,),
        ).fetchone()
    if row is not None:
        if row["kind"] != "semantic" or row["content"] != content:
            raise RuntimeError("Action memory key conflicts with stored content")
        event(
            "memory.reused",
            {"id": mid, "kind": "semantic", "agenda_id": agenda_id},
        )
        return mid
    ts = now()
    with connect() as db:
        db.execute(
            """
            INSERT INTO memory(id,kind,content,created,updated)
            VALUES (?,?,?,?,?)
            """,
            (mid, "semantic", content, ts, ts),
        )
    # The first insert is not tagged with agenda_id. The retry event is.
    event("memory.created", {"id": mid, "kind": "semantic"})
    return mid


def _experience_for_execution(content: str, agenda_id: str) -> str:
    """Reuse learning if a process dies before its terminal result commits."""
    mid = str(uuid.uuid5(uuid.NAMESPACE_URL, "lequtis:run-once-experience:" + agenda_id))
    ts = now()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT kind, content FROM memory WHERE id=?", (mid,)
        ).fetchone()
        if row is not None:
            if row["kind"] != "experience" or row["content"] != content:
                raise RuntimeError("Experience memory key conflicts with stored content")
            _append_event(db, "memory.reused", {
                "id": mid, "kind": "experience", "agenda_id": agenda_id,
            })
            return mid
        db.execute(
            """
            INSERT INTO memory(id,kind,content,created,updated)
            VALUES (?,?,?,?,?)
            """,
            (mid, "experience", content, ts, ts),
        )
        _append_event(db, "memory.created", {
            "id": mid, "kind": "experience", "agenda_id": agenda_id,
        })
    return mid


def _claim_next() -> dict[str, Any] | None:
    token = uuid.uuid4().hex
    correlation_id = str(uuid.uuid4())
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """
            SELECT id, title FROM agenda
            WHERE status='open' AND title NOT LIKE 'propose: %'
            ORDER BY priority DESC, created, id LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        agenda_id, title = row["id"], row["title"]
        changed = db.execute(
            "UPDATE agenda SET status='running', updated=? WHERE id=? AND status='open'",
            (now(), agenda_id),
        ).rowcount
        if changed != 1:
            return None
        attempt = db.execute(
            "SELECT COALESCE(MAX(attempt),0)+1 FROM executions WHERE agenda_id=?",
            (agenda_id,),
        ).fetchone()[0]
        execution_id = str(uuid.uuid4())
        action = "remember" if title.startswith("remember: ") else "unsupported"
        action_input = title[len("remember: "):] if action == "remember" else title
        relpath = correlation_id + ".json"
        db.execute(
            """
            INSERT INTO executions
            (id,agenda_id,attempt,status,action,input,started_at,claim_generation,lease_token,
             worker_pid,lease_proc_start,correlation_id,artifact_relpath,claimed_verdict)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                execution_id, agenda_id, attempt, "running", action, action_input, now(),
                attempt, token, os.getpid(), proc_start_token(os.getpid()), correlation_id,
                relpath, "accepted",
            ),
        )
    event("execution.notice", {
        "execution_id": execution_id, "agenda_id": agenda_id, "attempt": attempt,
    })
    event("loop.notice", {
        "execution_id": execution_id, "agenda_id": agenda_id, "stage": "NOTICE",
        "evidence_label": EVIDENCE_LABEL,
    })
    event("execution.think", {"execution_id": execution_id, "available_actions": ["remember"]})
    event("loop.think", {"execution_id": execution_id, "plan": "bounded remember action"})
    event("execution.choose", {"execution_id": execution_id, "action": action})
    event("loop.choose", {
        "execution_id": execution_id, "action": action, "allowlisted": action == "remember",
    })
    return {
        "id": execution_id,
        "agenda_id": agenda_id,
        "title": title,
        "attempt": attempt,
        "action": action,
        "input": action_input,
        "lease_token": token,
        "correlation_id": correlation_id,
        "artifact_relpath": relpath,
    }


def _execution_fence_row(db: sqlite3.Connection, execution_id: str) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT e.status AS execution_status,
               e.lease_token AS lease_token,
               e.cancelled_at AS execution_cancelled,
               e.action AS action,
               e.agenda_id AS agenda_id,
               e.result AS result,
               a.status AS agenda_status,
               a.cancelled_at AS agenda_cancelled
        FROM executions e
        JOIN agenda a ON a.id = e.agenda_id
        WHERE e.id=?
        """,
        (execution_id,),
    ).fetchone()


def _is_cancel_fenced(row: sqlite3.Row | None) -> bool:
    if row is None:
        return False
    return bool(
        row["execution_cancelled"]
        or row["agenda_cancelled"]
        or row["execution_status"] == "cancelled"
        or row["agenda_status"] == "cancelled"
    )


def _execution_is_cancelled(execution_id: str) -> bool:
    with connect() as db:
        return _is_cancel_fenced(_execution_fence_row(db, execution_id))


def _finish_rejection(row: sqlite3.Row | None, lease_token: str) -> dict[str, Any]:
    if row is None:
        reason = "missing_execution"
    elif _is_cancel_fenced(row):
        reason = "cancelled"
    elif (
        row["execution_status"] in ("succeeded", "failed")
        and row["lease_token"] == lease_token
    ):
        reason = "already_committed"
    else:
        reason = "stale_fence"
    return {"accepted": False, "reason": reason, "evidence_label": EVIDENCE_LABEL}


def _finish_execution(
    task: dict[str, Any],
    status_value: str,
    result: str | None = None,
    error: BaseException | str | None = None,
) -> dict[str, Any]:
    """Commit a terminal result for the current lease, or reject it.

    Cancellation is checked inside this transaction. A worker that already
    finished still cannot store the result after cancel. The lease token is
    not enough.
    """
    ts = now()
    db = connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = _execution_fence_row(db, task["id"])
        if row is None or _is_cancel_fenced(row):
            db.rollback()
            return _finish_rejection(row, task["lease_token"])
        if row["lease_token"] != task["lease_token"] or row["execution_status"] != "running":
            db.rollback()
            return _finish_rejection(row, task["lease_token"])
        updated = db.execute(
            """
            UPDATE executions SET status=?, result=?, error=?, completed_at=?
            WHERE id=? AND status='running' AND lease_token=? AND cancelled_at IS NULL
              AND agenda_id IN (
                SELECT id FROM agenda
                WHERE id=? AND cancelled_at IS NULL AND status!='cancelled'
              )
            """,
            (
                status_value,
                result,
                None if error is None else str(error),
                ts,
                task["id"],
                task["lease_token"],
                task["agenda_id"],
            ),
        ).rowcount
        if updated != 1:
            fresh = _execution_fence_row(db, task["id"])
            db.rollback()
            return _finish_rejection(fresh, task["lease_token"])
        agenda_status = "complete" if status_value == "succeeded" else "blocked"
        db.execute(
            """
            UPDATE agenda SET status=?, updated=?
            WHERE id=? AND status='running' AND cancelled_at IS NULL
            """,
            (agenda_status, ts, task["agenda_id"]),
        )
        _append_event(
            db,
            "execution.finished" if status_value == "succeeded" else "execution.failed",
            {
                "execution_id": task["id"],
                "agenda_id": task["agenda_id"],
                "status": status_value,
                "result": result,
                "error": None if error is None else str(error),
            },
        )
        _append_event(
            db,
            "agenda.updated",
            {"agenda_id": task["agenda_id"], "status": agenda_status},
        )
        _append_event(
            db,
            "loop.update_agenda",
            {
                "execution_id": task["id"],
                "agenda_id": task["agenda_id"],
                "status": agenda_status,
                "stage": "UPDATE AGENDA",
            },
        )
        db.commit()
    except Exception:
        try:
            db.execute("ROLLBACK")
        except sqlite3.DatabaseError:
            pass
        raise
    finally:
        db.close()
    return {"accepted": True, "reason": "committed", "evidence_label": EVIDENCE_LABEL}


def _pause_for(env_name: str, task: dict[str, Any]) -> None:
    pause = os.environ.get(env_name)
    if not pause:
        return
    folder = Path(pause)
    folder.mkdir(parents=True, exist_ok=True)
    execution_id = task.get("execution_id") or task.get("id")
    (folder / "claimed").write_text(
        json.dumps({
            "execution_id": execution_id,
            "lease_token": task["lease_token"],
            "pid": os.getpid(),
            "artifact_relpath": task.get("artifact_relpath"),
            "agenda_id": task.get("agenda_id"),
        }),
        encoding="utf-8",
    )
    deadline = time.time() + 20
    while time.time() < deadline and not (folder / "release").exists():
        time.sleep(0.02)


def _pause_after_claim(task: dict[str, Any]) -> None:
    _pause_for("LEQUTIS_PAUSE_AFTER_CLAIM", task)


def _cancelled_result(task: dict[str, Any], reason: str = "cancelled") -> dict[str, Any]:
    return {
        "status": "cancelled",
        "reason": reason,
        "agenda_id": task["agenda_id"],
        "execution_id": task["id"],
        "evidence_label": EVIDENCE_LABEL,
    }


def _verify_independently(task: dict[str, Any], digest: str) -> dict[str, Any]:
    challenge = uuid.uuid4().hex
    with connect() as db:
        db.execute(
            """
            UPDATE executions SET expected_sha256=?, verifier_challenge=?
            WHERE id=? AND lease_token=?
            """,
            (digest, challenge, task["id"], task["lease_token"]),
        )
    proc = subprocess.Popen(
        [
            sys.executable, str(VERIFIER),
            "--db", str(DB),
            "--execution-id", task["id"],
            "--artifact-root", str(artifact_root()),
            "--challenge", challenge,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = proc.communicate(timeout=30)
    if proc.returncode != 0:
        return {
            "verdict": "rejected",
            "reason": "verifier_process_failed",
            "stderr": stderr,
            "verifier_pid": proc.pid,
        }
    reported = json.loads(stdout)
    if reported.get("verifier_pid") != proc.pid or reported.get("worker_self_report_consulted") is not False:
        return {
            "verdict": "rejected",
            "reason": "verifier_identity_rejected",
            "verifier_pid": proc.pid,
        }
    return reported


def run_once() -> dict[str, Any]:
    task = _claim_next()
    if task is None:
        return {"status": "idle", "evidence_label": EVIDENCE_LABEL}
    _pause_after_claim(task)
    if _execution_is_cancelled(task["id"]):
        return _cancelled_result(task)
    try:
        if task["action"] != "remember":
            raise ValueError("No safe deterministic action supports this goal")
        if not task["input"].strip():
            raise ValueError("remember action requires non-empty text")
        event("loop.act", {
            "execution_id": task["id"], "action": "remember", "stage": "ACT",
        })
        memory_id = _semantic_for_execution(task["input"], task["agenda_id"])
        with connect() as db:
            observed = db.execute(
                "SELECT content FROM memory WHERE id=?", (memory_id,)
            ).fetchone()
        if observed is None or observed[0] != task["input"]:
            raise RuntimeError("Action result could not be observed")
        document = artifact_document(task["correlation_id"], task["id"], observed[0])
        digest = hashlib.sha256(document).hexdigest()
        root = artifact_root()
        root.mkdir(parents=True, exist_ok=True)
        path = root / task["artifact_relpath"]
        if not ARTIFACT_NAME.fullmatch(path.name):
            raise RuntimeError("artifact path is not allowlisted")
        payload = b"corrupt\n" if os.environ.get("LEQUTIS_CORRUPT_ARTIFACT") == "1" else document
        _write_new_file(path, payload)
        (root / "receipts").mkdir(exist_ok=True)
        receipt = root / "receipts" / (task["correlation_id"] + "-stdout.txt")
        _write_new_file(
            receipt,
            (
                EVIDENCE_LABEL
                + "\nartifact correlation_id="
                + task["correlation_id"]
                + " sha256="
                + digest
                + "\n"
            ).encode("utf-8"),
        )
        verdict = _verify_independently(task, digest)
        if verdict.get("verdict") != "accepted":
            event("loop.observe", {
                "execution_id": task["id"],
                "verdict": verdict.get("verdict"),
                "stage": "OBSERVE",
            })
            event("loop.evaluate", {
                "execution_id": task["id"], "passed": False, "stage": "EVALUATE",
            })
            finished = _finish_execution(task, "failed", error=verdict.get("reason"))
            if not finished["accepted"] and finished["reason"] == "cancelled":
                return _cancelled_result(task)
            return {
                "status": "failed",
                "agenda_id": task["agenda_id"],
                "error": verdict.get("reason"),
                "verifier": verdict,
                "evidence_label": EVIDENCE_LABEL,
            }
        event("execution.observe", {
            "execution_id": task["id"], "memory_id": memory_id, "content": observed[0],
        })
        event("loop.observe", {
            "execution_id": task["id"],
            "memory_id": memory_id,
            "content_sha256": verdict.get("content_sha256"),
            "correlation_id": task["correlation_id"],
            "worker_self_report_accepted": False,
            "stage": "OBSERVE",
        })
        result = json.dumps({
            "memory_id": memory_id,
            "content": observed[0],
            "correlation_id": task["correlation_id"],
        })
        event("execution.evaluate", {"execution_id": task["id"], "success": True})
        event("loop.evaluate", {
            "execution_id": task["id"], "passed": True, "stage": "EVALUATE",
        })
        experience = "Successful execution of agenda item: " + task["title"]
        experience_id = _experience_for_execution(experience, task["agenda_id"])
        event("execution.learn", {"execution_id": task["id"], "learned": True})
        event("loop.learn", {
            "execution_id": task["id"], "learned": True, "stage": "LEARN",
        })
        event("loop.remember", {
            "execution_id": task["id"],
            "memory_id": memory_id,
            "experience_id": experience_id,
            "stage": "REMEMBER",
        })
        _pause_for("LEQUTIS_PAUSE_BEFORE_COMMIT", task)
        finished = _finish_execution(task, "succeeded", result=result)
        if not finished["accepted"]:
            if finished["reason"] == "cancelled":
                return _cancelled_result(task)
            return {
                "status": "failed",
                "agenda_id": task["agenda_id"],
                "reason": finished["reason"],
                "error": finished["reason"],
                "evidence_label": EVIDENCE_LABEL,
            }
        return {
            "status": "succeeded",
            "agenda_id": task["agenda_id"],
            "result": json.loads(result),
            "verifier": verdict,
            "evidence_label": EVIDENCE_LABEL,
        }
    except Exception as exc:
        if _execution_is_cancelled(task["id"]):
            return _cancelled_result(task)
        try:
            event("execution.evaluate", {
                "execution_id": task["id"], "success": False, "error": str(exc),
            })
            event("loop.evaluate", {
                "execution_id": task["id"], "passed": False, "stage": "EVALUATE",
            })
        finally:
            finished = _finish_execution(task, "failed", error=exc)
        if not finished["accepted"] and finished["reason"] == "cancelled":
            return _cancelled_result(task)
        return {
            "status": "failed",
            "agenda_id": task["agenda_id"],
            "error": str(exc),
            "evidence_label": EVIDENCE_LABEL,
        }


def claim_proposal(agenda_id: str | None = None) -> dict[str, Any]:
    """Pull one open ``propose:`` agenda item. Does not call ACT.

    With no agenda id, the next open proposal is claimed. That is the pull
    used by decentralized allocation. A specific id is the central scheduler's
    assignment. Either way the lease is fenced with the kernel token, pid, and
    process start.
    """
    token = uuid.uuid4().hex
    db = connect()
    task: dict[str, Any] | None = None
    try:
        db.execute("BEGIN IMMEDIATE")
        if agenda_id:
            row = db.execute(
                "SELECT id, title FROM agenda WHERE id=? AND status='open'",
                (agenda_id,),
            ).fetchone()
        else:
            row = db.execute(
                """
                SELECT id, title FROM agenda
                WHERE status='open' AND title LIKE 'propose: %'
                ORDER BY priority DESC, created, id
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            db.rollback()
            return {"status": "idle", "evidence_label": EVIDENCE_LABEL}
        title = row["title"]
        if not str(title).startswith("propose: "):
            db.rollback()
            return {
                "status": "refused",
                "reason": "not_a_proposal",
                "evidence_label": EVIDENCE_LABEL,
            }
        agenda_pk = row["id"]
        changed = db.execute(
            "UPDATE agenda SET status='running', updated=? WHERE id=? AND status='open'",
            (now(), agenda_pk),
        ).rowcount
        if changed != 1:
            db.rollback()
            return {"status": "idle", "evidence_label": EVIDENCE_LABEL}
        attempt = db.execute(
            "SELECT COALESCE(MAX(attempt),0)+1 FROM executions WHERE agenda_id=?",
            (agenda_pk,),
        ).fetchone()[0]
        execution_id = str(uuid.uuid4())
        db.execute(
            """
            INSERT INTO executions
            (id,agenda_id,attempt,status,action,input,started_at,claim_generation,lease_token,
             worker_pid,lease_proc_start,correlation_id,claimed_verdict)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                execution_id, agenda_pk, attempt, "running", "propose_claim", title, now(),
                attempt, token, os.getpid(), proc_start_token(os.getpid()), str(uuid.uuid4()),
                None,
            ),
        )
        _append_event(db, "execution.claimed", {
            "action": "propose_claim",
            "agenda_id": agenda_pk,
            "attempt": attempt,
            "execution_id": execution_id,
        })
        db.commit()
        task = {
            "status": "claimed",
            "execution_id": execution_id,
            "id": execution_id,
            "agenda_id": agenda_pk,
            "title": title,
            "attempt": attempt,
            "lease_token": token,
            "claim_generation": attempt,
            "evidence_label": EVIDENCE_LABEL,
        }
    except Exception:
        try:
            db.execute("ROLLBACK")
        except sqlite3.DatabaseError:
            pass
        raise
    finally:
        db.close()
    assert task is not None
    _pause_after_claim(task)
    return task


def commit_result(execution_id: str, lease_token: str, result: str) -> dict[str, Any]:
    """Store a proposal result for a current lease. Does not call ACT.

    ``remember`` executions cannot use this path. Their result commit stays
    inside ``run_once``, after the independent verifier.
    """
    with connect() as db:
        row = db.execute(
            "SELECT id, agenda_id, action FROM executions WHERE id=?",
            (execution_id,),
        ).fetchone()
    if row is None:
        return {
            "accepted": False,
            "reason": "missing_execution",
            "evidence_label": EVIDENCE_LABEL,
        }
    if row["action"] != "propose_claim":
        return {
            "accepted": False,
            "reason": "commit_refused_for_action",
            "evidence_label": EVIDENCE_LABEL,
        }
    return _finish_execution(
        {"id": execution_id, "agenda_id": row["agenda_id"], "lease_token": lease_token},
        "succeeded",
        result=result,
    )


def cancel_request_hash(kind: str, target_id: str, reason: str | None) -> str:
    raw = json.dumps(
        {"reason": reason, "target_id": target_id, "target_kind": kind},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cancel_reply(
    status_value: str,
    *,
    error: str | None = None,
    cancellation_id: str | None = None,
    target_kind: str | None = None,
    target_id: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "status": status_value,
        "evidence_label": EVIDENCE_LABEL,
    }
    if error is not None:
        body["error"] = error
    if cancellation_id is not None:
        body["cancellation_id"] = cancellation_id
    if target_kind is not None:
        body["target_kind"] = target_kind
    if target_id is not None:
        body["target_id"] = target_id
    return body


def _replay_cancellation(existing: sqlite3.Row, digest: str) -> dict[str, Any]:
    if existing["request_hash"] != digest:
        return _cancel_reply(
            "conflict",
            error="idempotency_key_reused_with_different_request",
            cancellation_id=existing["id"],
            target_kind=existing["target_kind"],
            target_id=existing["target_id"],
        )
    return _cancel_reply(
        "duplicate",
        cancellation_id=existing["id"],
        target_kind=existing["target_kind"],
        target_id=existing["target_id"],
    )


def cancel_target(
    kind: str,
    target_id: str,
    idempotency_key: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Cancel an agenda item or one execution.

    The same key and request replays the recorded cancellation and does not
    append another event. A different request with that key conflicts. The
    cancellation row and the hash-chained event commit together.
    """
    if kind not in ("agenda", "execution"):
        return _cancel_reply("refused", error="invalid_target_kind")
    if not idempotency_key:
        return _cancel_reply("refused", error="idempotency_key_required")
    digest = cancel_request_hash(kind, target_id, reason)
    db = connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT * FROM cancellations WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            db.rollback()
            return _replay_cancellation(existing, digest)
        if kind == "agenda":
            outcome = _cancel_agenda(db, target_id, idempotency_key, reason, digest)
        else:
            outcome = _cancel_execution(db, target_id, idempotency_key, reason, digest)
        if outcome["status"] == "cancelled":
            db.commit()
        else:
            db.rollback()
        return outcome
    except sqlite3.IntegrityError:
        existing = db.execute(
            "SELECT * FROM cancellations WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        db.rollback()
        if existing is None:
            raise
        return _replay_cancellation(existing, digest)
    except Exception:
        try:
            db.execute("ROLLBACK")
        except sqlite3.DatabaseError:
            pass
        raise
    finally:
        db.close()


def _cancel_agenda(
    db: sqlite3.Connection,
    target_id: str,
    idempotency_key: str,
    reason: str | None,
    digest: str,
) -> dict[str, Any]:
    agenda = db.execute("SELECT * FROM agenda WHERE id=?", (target_id,)).fetchone()
    if agenda is None:
        return _cancel_reply("not_found", error="agenda_not_found", target_kind="agenda", target_id=target_id)
    if agenda["status"] == "complete":
        return _cancel_reply(
            "not_cancellable",
            error="agenda_already_complete",
            target_kind="agenda",
            target_id=target_id,
        )
    if agenda["cancelled_at"] is not None or agenda["status"] == "cancelled":
        return _cancel_reply("already_cancelled", target_kind="agenda", target_id=target_id)
    ts = now()
    cid = str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO cancellations
        (id,idempotency_key,request_hash,target_kind,target_id,reason,created)
        VALUES (?,?,?,?,?,?,?)
        """,
        (cid, idempotency_key, digest, "agenda", target_id, reason, ts),
    )
    changed = db.execute(
        """
        UPDATE agenda SET status='cancelled', cancelled_at=?, updated=?
        WHERE id=? AND status!='complete' AND cancelled_at IS NULL
        """,
        (ts, ts, target_id),
    ).rowcount
    if changed != 1:
        return _cancel_reply("not_cancellable", error="agenda_not_cancellable", target_kind="agenda", target_id=target_id)
    rows = db.execute(
        """
        SELECT id FROM executions
        WHERE agenda_id=? AND status IN ('running','interrupted','failed')
        ORDER BY id
        """,
        (target_id,),
    ).fetchall()
    execution_ids = [row["id"] for row in rows]
    if execution_ids:
        db.execute(
            """
            UPDATE executions SET status='cancelled', cancelled_at=?
            WHERE agenda_id=? AND status IN ('running','interrupted','failed')
            """,
            (ts, target_id),
        )
    _append_event(db, "agenda.cancelled", {
        "agenda_id": target_id,
        "cancellation_id": cid,
        "execution_ids": execution_ids,
        "idempotency_key": idempotency_key,
        "reason": reason,
        "target_kind": "agenda",
    })
    return _cancel_reply(
        "cancelled",
        cancellation_id=cid,
        target_kind="agenda",
        target_id=target_id,
    )


def _cancel_execution(
    db: sqlite3.Connection,
    target_id: str,
    idempotency_key: str,
    reason: str | None,
    digest: str,
) -> dict[str, Any]:
    row = db.execute(
        """
        SELECT e.id, e.status, e.cancelled_at, e.agenda_id, a.status AS agenda_status
        FROM executions e JOIN agenda a ON a.id=e.agenda_id
        WHERE e.id=?
        """,
        (target_id,),
    ).fetchone()
    if row is None:
        return _cancel_reply(
            "not_found", error="execution_not_found", target_kind="execution", target_id=target_id
        )
    if row["status"] == "succeeded" or row["agenda_status"] == "complete":
        return _cancel_reply(
            "not_cancellable",
            error="execution_already_committed",
            target_kind="execution",
            target_id=target_id,
        )
    if row["cancelled_at"] is not None or row["status"] == "cancelled":
        return _cancel_reply("already_cancelled", target_kind="execution", target_id=target_id)
    ts = now()
    cid = str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO cancellations
        (id,idempotency_key,request_hash,target_kind,target_id,reason,created)
        VALUES (?,?,?,?,?,?,?)
        """,
        (cid, idempotency_key, digest, "execution", target_id, reason, ts),
    )
    changed = db.execute(
        """
        UPDATE executions SET status='cancelled', cancelled_at=?
        WHERE id=? AND status!='succeeded' AND cancelled_at IS NULL
        """,
        (ts, target_id),
    ).rowcount
    if changed != 1:
        return _cancel_reply(
            "not_cancellable",
            error="execution_not_cancellable",
            target_kind="execution",
            target_id=target_id,
        )
    if row["agenda_status"] == "running":
        db.execute(
            """
            UPDATE agenda SET status='blocked', updated=?
            WHERE id=? AND status='running' AND cancelled_at IS NULL
            """,
            (ts, row["agenda_id"]),
        )
    _append_event(db, "execution.cancelled", {
        "agenda_id": row["agenda_id"],
        "cancellation_id": cid,
        "execution_id": target_id,
        "idempotency_key": idempotency_key,
        "reason": reason,
        "target_kind": "execution",
    })
    return _cancel_reply(
        "cancelled",
        cancellation_id=cid,
        target_kind="execution",
        target_id=target_id,
    )


def recover_interrupted() -> dict[str, Any]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT id, agenda_id, worker_pid, lease_proc_start
            FROM executions WHERE status='running'
            """
        ).fetchall()
    recovered: list[tuple[str, str]] = []
    skipped: list[str] = []
    for row in rows:
        if process_is_live(row["worker_pid"], row["lease_proc_start"]):
            skipped.append(row["id"])
            continue
        recovered.append((row["id"], row["agenda_id"]))
    ts = now()
    won: list[tuple[str, str]] = []
    db = connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        for execution_id, agenda_id in recovered:
            changed = db.execute(
                """
                UPDATE executions
                SET status='interrupted', error=?, completed_at=?, lease_token=NULL
                WHERE id=? AND status='running'
                """,
                ("Process stopped before execution finished", ts, execution_id),
            ).rowcount
            if changed != 1:
                continue
            db.execute(
                """
                UPDATE agenda SET status='blocked', updated=?
                WHERE id=? AND status='running'
                """,
                (ts, agenda_id),
            )
            won.append((execution_id, agenda_id))
        db.commit()
    finally:
        db.close()
    for execution_id, agenda_id in won:
        event("execution.interrupted", {
            "execution_id": execution_id, "agenda_id": agenda_id,
        })
        event("agenda.updated", {"agenda_id": agenda_id, "status": "blocked"})
    return {
        "recovered": len(won),
        "live_skipped": skipped,
        "evidence_label": EVIDENCE_LABEL,
    }


def retry_agenda(agenda_id: str) -> bool:
    with connect() as db:
        latest = db.execute(
            """
            SELECT status FROM executions
            WHERE agenda_id=? ORDER BY attempt DESC LIMIT 1
            """,
            (agenda_id,),
        ).fetchone()
        if latest is None or latest[0] not in ("failed", "interrupted"):
            return False
        changed = db.execute(
            """
            UPDATE agenda SET status='open', updated=?
            WHERE id=? AND status='blocked'
            """,
            (now(), agenda_id),
        ).rowcount
    if changed:
        event("agenda.retry_requested", {"agenda_id": agenda_id})
    return changed == 1


def verify_events() -> dict[str, Any]:
    previous = "GENESIS"
    with connect() as db:
        rows = db.execute(
            """
            SELECT ts, event_type, payload, previous_hash, event_hash
            FROM events ORDER BY seq
            """
        ).fetchall()
    for sequence, row in enumerate(rows, 1):
        raw = previous + "|" + row[0] + "|" + row[1] + "|" + row[2]
        expected = hashlib.sha256(raw.encode()).hexdigest()
        if row[3] != previous or row[4] != expected:
            return {
                "valid": False,
                "events": len(rows),
                "invalid_sequence": sequence,
                "evidence_label": EVIDENCE_LABEL,
            }
        previous = row[4]
    return {"valid": True, "events": len(rows), "evidence_label": EVIDENCE_LABEL}


def attempt_stale_complete(execution_id: str, token: str) -> dict[str, Any]:
    with connect() as db:
        row = _execution_fence_row(db, execution_id)
        if _is_cancel_fenced(row):
            return {
                "accepted": False,
                "reason": "cancelled",
                "evidence_label": EVIDENCE_LABEL,
            }
        if row is None or row["lease_token"] != token or row["execution_status"] != "running":
            return {
                "accepted": False,
                "reason": "stale_fence",
                "evidence_label": EVIDENCE_LABEL,
            }
        accepted = db.execute(
            """
            SELECT 1 FROM verifier_observations
            WHERE execution_id=? AND verdict='accepted' AND worker_self_report_consulted=0
            """,
            (execution_id,),
        ).fetchone()
        if accepted is None:
            return {
                "accepted": False,
                "reason": "verifier_required",
                "evidence_label": EVIDENCE_LABEL,
            }
    return {
        "accepted": False,
        "reason": "completion_requires_current_lease",
        "evidence_label": EVIDENCE_LABEL,
    }


def _parse_goal(argv: list[str]) -> tuple[str | None, str]:
    args = argv[2:]
    if args[:1] == ["--key"]:
        if len(args) < 3:
            raise SystemExit("goal --key requires a key and a title")
        return args[1], " ".join(args[2:]).strip()
    return None, " ".join(args).strip()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_cancel(argv: list[str]) -> dict[str, Any]:
    args = argv[2:]
    key = None
    reason_parts: list[str] | None = None
    kind = None
    target = None
    index = 0
    while index < len(args):
        item = args[index]
        if item == "--key":
            if index + 1 >= len(args):
                raise SystemExit("cancel --key requires a value")
            key = args[index + 1]
            index += 2
            continue
        if item == "--reason":
            index += 1
            reason_parts = []
            while index < len(args) and args[index] not in ("agenda", "execution"):
                reason_parts.append(args[index])
                index += 1
            continue
        if item in ("agenda", "execution"):
            if index + 1 >= len(args):
                raise SystemExit("cancel requires a target id")
            kind = item
            target = args[index + 1]
            index += 2
            continue
        raise SystemExit(
            "cancel usage: cancel --key KEY [--reason TEXT] agenda|execution ID"
        )
    if not key or not kind or not target:
        raise SystemExit(
            "cancel usage: cancel --key KEY [--reason TEXT] agenda|execution ID"
        )
    reason = None if reason_parts is None else " ".join(reason_parts).strip()
    return cancel_target(kind, target, key, reason)


def main() -> None:
    argv = sys.argv
    if len(argv) >= 2 and argv[1] == "migrate":
        outcome = migrate_schema()
        print(json.dumps(outcome, indent=2, sort_keys=True))
        return
    init()

    if len(argv) < 2:
        print(
            "LeQutis commands: init | status | heartbeat | remember | goal | "
            "loop | run-once | recover | retry | verify | verify-events | "
            "verify-independent | unfinished | complete | commit | claim | "
            "cancel | migrate | daemon | sources | assimilate | ingest | "
            "search | gates | seed-gates | skills | parity"
        )
        return

    cmd = argv[1]

    if cmd == "init":
        print(json.dumps(status(), indent=2))

    elif cmd == "status":
        print(json.dumps(status(), indent=2))

    elif cmd == "heartbeat":
        print(json.dumps(heartbeat(), indent=2))

    elif cmd == "remember":
        text = " ".join(argv[2:]).strip()
        if not text:
            raise SystemExit("remember requires text")
        remember(text)
        print("MEMORY STORED")

    elif cmd == "goal":
        key, title = _parse_goal(argv)
        if not title:
            raise SystemExit("goal requires title")
        outcome = record_goal(title, idempotency_key=key)
        if outcome["status"] == "conflict":
            print(json.dumps(outcome, sort_keys=True))
            raise SystemExit(1)
        print(
            "AGENDA ITEM EXISTS"
            if outcome["status"] == "duplicate"
            else "AGENDA ITEM CREATED"
        )

    elif cmd == "loop":
        result = run_loop()
        print(json.dumps(result, indent=2))

    elif cmd == "run-once":
        result = run_once()
        print(json.dumps(result, indent=2))
        if result["status"] in ("failed", "cancelled"):
            raise SystemExit(1)

    elif cmd == "recover":
        print(json.dumps(recover_interrupted()))

    elif cmd == "retry":
        if len(argv) != 3:
            raise SystemExit("retry requires an agenda id")
        if not retry_agenda(argv[2]):
            raise SystemExit("agenda item is not recoverable")
        print("AGENDA ITEM REOPENED")

    elif cmd == "verify":
        result = verify_event_chain()
        print(json.dumps(result, indent=2))
        if not result.get("ok"):
            raise SystemExit(1)

    elif cmd == "verify-events":
        result = verify_events()
        print(json.dumps(result, indent=2))
        if not result["valid"]:
            raise SystemExit(1)

    elif cmd == "complete":
        if len(argv) != 4:
            raise SystemExit("complete requires an execution id and a lease token")
        print(json.dumps(attempt_stale_complete(argv[2], argv[3]), sort_keys=True))
        raise SystemExit(1)

    elif cmd == "claim":
        agenda_id = argv[2] if len(argv) > 2 else None
        outcome = claim_proposal(agenda_id)
        print(json.dumps(outcome, sort_keys=True))
        if outcome.get("status") == "refused":
            raise SystemExit(1)

    elif cmd == "commit":
        if len(argv) != 5:
            raise SystemExit("commit requires an execution id, a lease token, and result JSON")
        try:
            parsed = json.loads(argv[4])
        except json.JSONDecodeError as exc:
            raise SystemExit("commit result must be JSON") from exc
        if not isinstance(parsed, dict):
            raise SystemExit("commit result must be a JSON object")
        outcome = commit_result(
            argv[2], argv[3], json.dumps(parsed, sort_keys=True, separators=(",", ":"))
        )
        print(json.dumps(outcome, sort_keys=True))
        if not outcome.get("accepted"):
            raise SystemExit(1)

    elif cmd == "cancel":
        outcome = _parse_cancel(argv)
        print(json.dumps(outcome, sort_keys=True))
        if outcome["status"] in ("conflict", "not_found", "not_cancellable", "refused"):
            raise SystemExit(1)

    elif cmd == "daemon":
        interval = int(argv[2]) if len(argv) > 2 else 60
        if interval < 1:
            raise SystemExit("daemon interval must be at least one second")
        while True:
            result = run_once()
            print(json.dumps(result), flush=True)
            time.sleep(interval)

    elif cmd == "verify-independent":
        cid = argv[2] if len(argv) > 2 else None
        print(json.dumps(verify_independent(cid), indent=2))

    elif cmd == "unfinished":
        print(json.dumps(unfinished_work(), indent=2))

    elif cmd == "sources":
        sub = argv[2] if len(argv) > 2 else "list"
        if sub in ("list", "show"):
            register_sources_from_manifest()
            print(json.dumps(list_sources(), indent=2))
        elif sub == "register":
            print(json.dumps(register_sources_from_manifest(), indent=2))
        else:
            raise SystemExit("sources subcommands: list | register")

    elif cmd == "assimilate":
        print(json.dumps(assimilate_local_evidence(), indent=2))

    elif cmd == "ingest":
        print(json.dumps(ingest_inbox(), indent=2))

    elif cmd == "gates":
        print(json.dumps(gates_report(), indent=2))

    elif cmd == "seed-gates":
        print(json.dumps(seed_open_gates_to_agenda(), indent=2))

    elif cmd == "search":
        query = " ".join(argv[2:]).strip()
        if not query:
            raise SystemExit("search requires a query")
        print(json.dumps(search_knowledge(query), indent=2))

    elif cmd == "parity":
        print(json.dumps(access_parity(), indent=2))

    elif cmd == "skills":
        sub = argv[2] if len(argv) > 2 else "list"
        if sub == "list":
            status_filter = argv[3] if len(argv) > 3 else None
            print(json.dumps(skill_list(status_filter), indent=2))
        elif sub == "propose":
            name = " ".join(argv[3:]).strip()
            if not name:
                raise SystemExit("skills propose requires a name")
            sid = skill_propose(name)
            print(json.dumps({"id": sid, "status": "PROPOSED"}, indent=2))
        elif sub == "advance":
            if len(argv) < 5:
                raise SystemExit(
                    "skills advance <id> <STATUS> [evidence-json-object]"
                )
            evidence = json.loads(" ".join(argv[5:])) if len(argv) > 5 else None
            if evidence is not None and not isinstance(evidence, dict):
                raise SystemExit("evidence-json-object must decode to an object")
            print(
                json.dumps(
                    skill_advance(argv[3], argv[4], evidence), indent=2
                )
            )
        else:
            raise SystemExit("skills subcommands: list | propose | advance")

    else:
        raise SystemExit("Unknown command: " + cmd)


if __name__ == "__main__":
    main()
