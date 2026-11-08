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
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Paths — LEQUTIS_STATE enables disposable DBs for tests (never production).
# ---------------------------------------------------------------------------

ROOT = Path(os.environ.get("LEQUTIS_ROOT", Path(__file__).resolve().parents[1]))
STATE = Path(os.environ.get("LEQUTIS_STATE", ROOT / "state"))
DB = STATE / "lequtis.db"

STATE.mkdir(parents=True, exist_ok=True)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init() -> None:
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


# ---------------------------------------------------------------------------
# Event fabric (hash-chained evidence)
# ---------------------------------------------------------------------------

def event(event_type: str, payload: dict[str, Any]) -> str:
    payload_s = json.dumps(payload, sort_keys=True)
    ts = now()

    with connect() as db:
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


def add_goal(title: str, priority: int = 10) -> str:
    gid = str(uuid.uuid4())
    ts = now()
    with connect() as db:
        db.execute(
            """
            INSERT INTO agenda(id,title,status,priority,created,updated)
            VALUES (?,?,?,?,?,?)
            """,
            (gid, title, "open", priority, ts, ts),
        )
    event("agenda.created", {"id": gid, "title": title})
    return gid


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
    return {
        "identity": identity,
        "memory": memory_count,
        "open_agenda": goals,
        "skills": skills,
        "events": events_n,
        "open_tasks": tasks_open,
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

        candidates = think(noticed)
        evidence["phases"]["THINK"] = {"candidates": len(candidates)}

        choice = choose(candidates)
        evidence["phases"]["CHOOSE"] = {
            "action": choice["action"],
            "kind": choice["kind"],
        }

        act_result = act(choice)
        evidence["phases"]["ACT"] = {
            "task_id": act_result.get("task_id"),
            "ok": act_result.get("ok"),
            "duplicate": act_result.get("duplicate"),
        }

        observation = observe(act_result)
        evidence["phases"]["OBSERVE"] = observation

        evaluation = evaluate(observation)
        evidence["phases"]["EVALUATE"] = {
            "verdict": evaluation["verdict"],
            "accepted": evaluation["accepted"],
        }

        learning = learn(evaluation)
        evidence["phases"]["LEARN"] = learning

        memory_id = remember_learning(learning)
        evidence["phases"]["REMEMBER"] = {"memory_id": memory_id}

        agenda_update = update_agenda_from_eval(evaluation)
        evidence["phases"]["UPDATE_AGENDA"] = agenda_update

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
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    init()
    argv = os.sys.argv

    if len(argv) < 2:
        print(
            "LeQutis commands: init | status | heartbeat | remember | goal | "
            "loop | verify | verify-independent | unfinished | sources | "
            "assimilate | ingest | search | gates | seed-gates | skills | "
            "parity"
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
        title = " ".join(argv[2:]).strip()
        if not title:
            raise SystemExit("goal requires title")
        add_goal(title)
        print("AGENDA ITEM CREATED")

    elif cmd == "loop":
        result = run_loop()
        print(json.dumps(result, indent=2))

    elif cmd == "verify":
        print(json.dumps(verify_event_chain(), indent=2))

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
