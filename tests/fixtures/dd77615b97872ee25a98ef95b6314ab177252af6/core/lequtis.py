#!/usr/bin/env python3

import sqlite3
import json
import hashlib
import os
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
DB = Path(os.environ.get("LEQUTIS_DB", STATE / "lequtis.db")).expanduser()

DB.parent.mkdir(parents=True, exist_ok=True)

def now():
    return datetime.now(timezone.utc).isoformat()

def connect():
    db = sqlite3.connect(DB)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db

def init():
    with connect() as db:
        db.executescript("""
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
            updated TEXT NOT NULL
        );

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
            UNIQUE(agenda_id, attempt)
        );
        """)

        defaults = {
            "name": "LeQutis",
            "purpose": "Proactive autonomous self-improving AI partner",
            "host": "Android A71 / Termux",
            "architecture": "evolutionary",
        }

        for k, v in defaults.items():
            db.execute(
                "INSERT OR IGNORE INTO identity(key,value) VALUES (?,?)",
                (k, v)
            )

def event(event_type, payload):
    payload = json.dumps(payload, sort_keys=True)
    ts = now()

    with connect() as db:
        row = db.execute(
            "SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()

        previous = row[0] if row else "GENESIS"

        raw = previous + "|" + ts + "|" + event_type + "|" + payload
        digest = hashlib.sha256(raw.encode()).hexdigest()

        db.execute("""
            INSERT INTO events
            (event_id,ts,event_type,payload,previous_hash,event_hash)
            VALUES (?,?,?,?,?,?)
        """, (
            str(uuid.uuid4()),
            ts,
            event_type,
            payload,
            previous,
            digest
        ))


def remember(content, kind="semantic"):
    mid = str(uuid.uuid4())
    ts = now()

    with connect() as db:
        db.execute("""
            INSERT INTO memory(id,kind,content,created,updated)
            VALUES (?,?,?,?,?)
        """, (mid, kind, content, ts, ts))

    event("memory.created", {"id": mid, "kind": kind})
    return mid

def add_goal(title, priority=10):
    gid = str(uuid.uuid4())
    ts = now()

    with connect() as db:
        db.execute("""
            INSERT INTO agenda(id,title,status,priority,created,updated)
            VALUES (?,?,?,?,?,?)
        """, (gid, title, "open", priority, ts, ts))

    event("agenda.created", {"id": gid, "title": title})

def status():
    with connect() as db:
        identity = dict(
            db.execute("SELECT key,value FROM identity").fetchall()
        )
        memory_count = db.execute(
            "SELECT COUNT(*) FROM memory"
        ).fetchone()[0]
        goals = db.execute(
            "SELECT COUNT(*) FROM agenda WHERE status='open'"
        ).fetchone()[0]
        skills = db.execute(
            "SELECT COUNT(*) FROM skills"
        ).fetchone()[0]
        events = db.execute(
            "SELECT COUNT(*) FROM events"
        ).fetchone()[0]
        unfinished = db.execute(
            "SELECT COUNT(*) FROM executions WHERE status='running'"
        ).fetchone()[0]

    return {
        "identity": identity,
        "memory": memory_count,
        "open_agenda": goals,
        "skills": skills,
        "events": events,
        "unfinished_executions": unfinished,
        "db": str(DB),
    }


def agenda_items():
    with connect() as db:
        return db.execute("""
            SELECT id,title,status,priority,updated
            FROM agenda
            ORDER BY CASE status
                WHEN 'open' THEN 0
                WHEN 'running' THEN 1
                WHEN 'blocked' THEN 2
                ELSE 3
            END, priority DESC, created, id
        """).fetchall()


def _claim_next():
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""
            SELECT id,title FROM agenda
            WHERE status='open'
            ORDER BY priority DESC, created, id
            LIMIT 1
        """).fetchone()
        if row is None:
            return None

        agenda_id, title = row
        changed = db.execute(
            "UPDATE agenda SET status='running',updated=? "
            "WHERE id=? AND status='open'",
            (now(), agenda_id)
        ).rowcount
        if changed != 1:
            return None

        attempt = db.execute(
            "SELECT COALESCE(MAX(attempt),0)+1 FROM executions WHERE agenda_id=?",
            (agenda_id,)
        ).fetchone()[0]
        execution_id = str(uuid.uuid4())
        action = "remember" if title.startswith("remember: ") else "unsupported"
        action_input = title[len("remember: "):] if action == "remember" else title
        db.execute("""
            INSERT INTO executions
                (id,agenda_id,attempt,status,action,input,started_at)
            VALUES (?,?,?,?,?,?,?)
        """, (execution_id, agenda_id, attempt, "running", action, action_input, now()))

    event("execution.notice", {
        "execution_id": execution_id,
        "agenda_id": agenda_id,
        "attempt": attempt,
    })
    event("execution.think", {
        "execution_id": execution_id,
        "available_actions": ["remember"],
    })
    event("execution.choose", {
        "execution_id": execution_id,
        "action": action,
    })
    return {
        "id": execution_id,
        "agenda_id": agenda_id,
        "title": title,
        "attempt": attempt,
        "action": action,
        "input": action_input,
    }


def _finish_execution(task, status_value, result=None, error=None):
    ts = now()
    with connect() as db:
        db.execute("""
            UPDATE executions
            SET status=?,result=?,error=?,completed_at=?
            WHERE id=? AND status='running'
        """, (
            status_value, result,
            str(error) if error is not None else None,
            ts, task["id"]
        ))
        agenda_status = "complete" if status_value == "succeeded" else "blocked"
        db.execute(
            "UPDATE agenda SET status=?,updated=? WHERE id=? AND status='running'",
            (agenda_status, ts, task["agenda_id"])
        )
    event("execution.finished" if status_value == "succeeded" else "execution.failed", {
        "execution_id": task["id"],
        "agenda_id": task["agenda_id"],
        "status": status_value,
        "result": result,
        "error": str(error) if error is not None else None,
    })
    event("agenda.updated", {
        "agenda_id": task["agenda_id"],
        "status": agenda_status,
    })


def run_once():
    task = _claim_next()
    if task is None:
        return {"status": "idle"}

    try:
        if task["action"] != "remember":
            raise ValueError("No safe deterministic action supports this goal")
        if not task["input"].strip():
            raise ValueError("remember action requires non-empty text")

        memory_id = remember(task["input"])
        with connect() as db:
            observed = db.execute(
                "SELECT content FROM memory WHERE id=?", (memory_id,)
            ).fetchone()
        if observed is None or observed[0] != task["input"]:
            raise RuntimeError("Action result could not be observed")
        event("execution.observe", {
            "execution_id": task["id"],
            "memory_id": memory_id,
            "content": observed[0],
        })

        result = json.dumps({"memory_id": memory_id, "content": observed[0]})
        event("execution.evaluate", {
            "execution_id": task["id"],
            "success": True,
        })
        remember(
            "Successful execution of agenda item: " + task["title"],
            kind="experience"
        )
        event("execution.learn", {"execution_id": task["id"], "learned": True})
        _finish_execution(task, "succeeded", result=result)
        return {"status": "succeeded", "agenda_id": task["agenda_id"], "result": json.loads(result)}
    except Exception as exc:
        try:
            event("execution.evaluate", {
                "execution_id": task["id"],
                "success": False,
                "error": str(exc),
            })
        finally:
            _finish_execution(task, "failed", error=exc)
        return {"status": "failed", "agenda_id": task["agenda_id"], "error": str(exc)}


def recover_interrupted():
    with connect() as db:
        rows = db.execute("""
            SELECT id,agenda_id FROM executions WHERE status='running'
        """).fetchall()
        ts = now()
        for execution_id, agenda_id in rows:
            db.execute("""
                UPDATE executions
                SET status='interrupted',error=?,completed_at=?
                WHERE id=? AND status='running'
            """, ("Process stopped before execution finished", ts, execution_id))
            db.execute(
                "UPDATE agenda SET status='blocked',updated=? WHERE id=? AND status='running'",
                (ts, agenda_id)
            )
    for execution_id, agenda_id in rows:
        event("execution.interrupted", {
            "execution_id": execution_id,
            "agenda_id": agenda_id,
        })
        event("agenda.updated", {"agenda_id": agenda_id, "status": "blocked"})
    return len(rows)


def retry_agenda(agenda_id):
    with connect() as db:
        latest = db.execute("""
            SELECT status FROM executions
            WHERE agenda_id=? ORDER BY attempt DESC LIMIT 1
        """, (agenda_id,)).fetchone()
        if latest is None or latest[0] not in ("failed", "interrupted"):
            return False
        changed = db.execute("""
            UPDATE agenda SET status='open',updated=?
            WHERE id=? AND status='blocked'
        """, (now(), agenda_id)).rowcount
    if changed:
        event("agenda.retry_requested", {"agenda_id": agenda_id})
    return changed == 1


def verify_events():
    previous = "GENESIS"
    with connect() as db:
        rows = db.execute("""
            SELECT ts,event_type,payload,previous_hash,event_hash
            FROM events ORDER BY seq
        """).fetchall()
    for sequence, (ts, event_type, payload, previous_hash, event_hash) in enumerate(rows, 1):
        raw = previous + "|" + ts + "|" + event_type + "|" + payload
        expected = hashlib.sha256(raw.encode()).hexdigest()
        if previous_hash != previous or event_hash != expected:
            return {"valid": False, "events": len(rows), "invalid_sequence": sequence}
        previous = event_hash
    return {"valid": True, "events": len(rows)}


def heartbeat():
    event("heartbeat", {"status": "alive", "host": "A71"})
    print(json.dumps(status(), indent=2))

def main():
    init()

    if len(os.sys.argv) < 2:
        print("LeQutis commands: init | status | heartbeat | remember | goal | agenda | run-once | recover | retry | verify-events | daemon")
        return

    cmd = os.sys.argv[1]

    if cmd == "init":
        print(json.dumps(status(), indent=2))

    elif cmd == "status":
        print(json.dumps(status(), indent=2))

    elif cmd == "heartbeat":
        heartbeat()

    elif cmd == "remember":
        text = " ".join(os.sys.argv[2:]).strip()
        if not text:
            raise SystemExit("remember requires text")
        remember(text)
        print("MEMORY STORED")

    elif cmd == "goal":
        title = " ".join(os.sys.argv[2:]).strip()
        if not title:
            raise SystemExit("goal requires title")
        add_goal(title)
        print("AGENDA ITEM CREATED")

    elif cmd == "agenda":
        print(json.dumps([
            {"id": row[0], "title": row[1], "status": row[2],
             "priority": row[3], "updated": row[4]}
            for row in agenda_items()
        ], indent=2))

    elif cmd == "run-once":
        result = run_once()
        print(json.dumps(result, indent=2))
        if result["status"] == "failed":
            raise SystemExit(1)

    elif cmd == "recover":
        print(json.dumps({"recovered": recover_interrupted()}))

    elif cmd == "retry":
        if len(os.sys.argv) != 3:
            raise SystemExit("retry requires an agenda id")
        if not retry_agenda(os.sys.argv[2]):
            raise SystemExit("agenda item is not recoverable")
        print("AGENDA ITEM REOPENED")

    elif cmd == "verify-events":
        result = verify_events()
        print(json.dumps(result, indent=2))
        if not result["valid"]:
            raise SystemExit(1)

    elif cmd == "daemon":
        interval = int(os.sys.argv[2]) if len(os.sys.argv) > 2 else 60
        if interval < 1:
            raise SystemExit("daemon interval must be at least one second")
        while True:
            result = run_once()
            print(json.dumps(result), flush=True)
            time.sleep(interval)

    else:
        raise SystemExit("Unknown command: " + cmd)

if __name__ == "__main__":
    main()
