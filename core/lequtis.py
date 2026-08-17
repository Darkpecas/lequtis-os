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
DB = STATE / "lequtis.db"

STATE.mkdir(parents=True, exist_ok=True)

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

    return {
        "identity": identity,
        "memory": memory_count,
        "open_agenda": goals,
        "skills": skills,
        "events": events,
        "db": str(DB),
    }

def heartbeat():
    event("heartbeat", {"status": "alive", "host": "A71"})
    print(json.dumps(status(), indent=2))

def main():
    init()

    if len(os.sys.argv) < 2:
        print("LeQutis commands: init | status | heartbeat | remember | goal")
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

    else:
        raise SystemExit("Unknown command: " + cmd)

if __name__ == "__main__":
    main()
