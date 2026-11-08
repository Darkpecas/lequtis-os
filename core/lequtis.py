#!/usr/bin/env python3
"""LeQutis kernel extended from public commit dd77615.

LOCAL PROOF, NOT LIVE VPS VERIFIED.

The remember-only execution slice is kept. This file adds a fail-closed
schema revision, idempotency keys, an independent verifier process, and a
lease fence. It does not merge GitHub main and it does not contact a host.
"""
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE_LABEL = "LOCAL PROOF, NOT LIVE VPS VERIFIED"
SCHEMA_REVISION = "lequtis-os-kernel-3"
ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
DB = Path(os.environ.get("LEQUTIS_DB", STATE / "lequtis.db")).expanduser()
VERIFIER = Path(__file__).with_name("verifier_main.py")
ARTIFACT_NAME = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.json$"
)

REQUIRED_COLUMNS = {
    "identity": {"key", "value"},
    "memory": {"id", "kind", "content", "created", "updated"},
    "agenda": {"id", "title", "status", "priority", "created", "updated", "idempotency_key", "request_hash"},
    "skills": {"id", "name", "version", "status", "evidence", "created", "updated"},
    "events": {"seq", "event_id", "ts", "event_type", "payload", "previous_hash", "event_hash"},
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


def now():
    return datetime.now(timezone.utc).isoformat()


def artifact_root():
    override = os.environ.get("LEQUTIS_ARTIFACT_ROOT")
    return Path(override).expanduser() if override else DB.parent / "artifacts"


def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def artifact_document(correlation_id, execution_id, content):
    body = {
        "content": content,
        "correlation_id": correlation_id,
        "evidence_label": EVIDENCE_LABEL,
        "execution_id": execution_id,
    }
    return (canonical_json(body) + "\n").encode("utf-8")


def request_hash(title):
    return hashlib.sha256(canonical_json({"title": title}).encode("utf-8")).hexdigest()


def proc_start_token(pid):
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    cut = text.rfind(")")
    fields = text[cut + 2:].split()
    if len(fields) <= 19:
        return None
    return fields[19]


def process_is_live(pid, expected_start):
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


def _columns(db, table):
    rows = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchall()
    if not rows:
        return None
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def _require_compatible():
    uri = "file:" + str(DB.resolve()) + "?mode=ro&immutable=1"
    try:
        db = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as exc:
        raise SystemExit(f"schema guard: {exc}")
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        for table, required in REQUIRED_COLUMNS.items():
            found = _columns(db, table)
            if found is None or not required.issubset(found):
                missing = sorted(required if found is None else required - found)
                raise SystemExit("schema guard: incompatible database, not modified: " + table + " " + ",".join(missing))
        row = db.execute("SELECT value FROM identity WHERE key='schema_revision'").fetchone()
        if row is None or row[0] != SCHEMA_REVISION:
            found = None if row is None else row[0]
            raise SystemExit(f"schema guard: revision {found!r} is not {SCHEMA_REVISION}; database not modified")
    finally:
        db.close()


def _create_new():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript(Path(__file__).resolve().parents[1].joinpath("database", "schema.sql").read_text(encoding="utf-8"))
        defaults = {
            "name": "LeQutis",
            "purpose": "Proactive autonomous self-improving AI partner",
            "host": "Android A71 / Termux",
            "architecture": "evolutionary",
            "schema_revision": SCHEMA_REVISION,
            "evidence_label": EVIDENCE_LABEL,
        }
        for key, value in defaults.items():
            db.execute("INSERT OR IGNORE INTO identity(key,value) VALUES (?,?)", (key, value))


def init():
    if DB.exists():
        _require_compatible()
        return
    _create_new()


def event(event_type, payload):
    payload = json.dumps(payload, sort_keys=True)
    ts = now()
    with connect() as db:
        row = db.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        previous = row[0] if row else "GENESIS"
        raw = previous + "|" + ts + "|" + event_type + "|" + payload
        digest = hashlib.sha256(raw.encode()).hexdigest()
        db.execute(
            """INSERT INTO events (event_id,ts,event_type,payload,previous_hash,event_hash)
               VALUES (?,?,?,?,?,?)""",
            (str(uuid.uuid4()), ts, event_type, payload, previous, digest),
        )


def remember(content, kind="semantic"):
    mid = str(uuid.uuid4())
    ts = now()
    with connect() as db:
        db.execute(
            "INSERT INTO memory(id,kind,content,created,updated) VALUES (?,?,?,?,?)",
            (mid, kind, content, ts, ts),
        )
    event("memory.created", {"id": mid, "kind": kind})
    return mid


def add_goal(title, priority=10, idempotency_key=None):
    if idempotency_key:
        with connect() as db:
            existing = db.execute(
                "SELECT id,title,status,request_hash FROM agenda WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
        if existing is not None:
            if existing["title"] != title or existing["request_hash"] != request_hash(title):
                return {
                    "status": "conflict",
                    "agenda_id": existing["id"],
                    "error": "idempotency_key_reused_with_different_request",
                    "evidence_label": EVIDENCE_LABEL,
                }
            return {
                "status": "duplicate",
                "agenda_id": existing["id"],
                "agenda_status": existing["status"],
                "evidence_label": EVIDENCE_LABEL,
            }
    gid = str(uuid.uuid4())
    ts = now()
    with connect() as db:
        db.execute(
            """INSERT INTO agenda
               (id,title,status,priority,created,updated,idempotency_key,request_hash)
               VALUES (?,?,?,?,?,?,?,?)""",
            (gid, title, "open", priority, ts, ts, idempotency_key,
             request_hash(title) if idempotency_key else None),
        )
    event("agenda.created", {"id": gid, "title": title, "idempotency_key": idempotency_key})
    return {"status": "created", "agenda_id": gid, "evidence_label": EVIDENCE_LABEL}


def status():
    with connect() as db:
        identity = dict(db.execute("SELECT key,value FROM identity").fetchall())
        memory_count = db.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
        goals = db.execute("SELECT COUNT(*) FROM agenda WHERE status='open'").fetchone()[0]
        skills = db.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        events = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        unfinished = db.execute("SELECT COUNT(*) FROM executions WHERE status='running'").fetchone()[0]
    return {
        "identity": identity,
        "memory": memory_count,
        "open_agenda": goals,
        "skills": skills,
        "events": events,
        "unfinished_executions": unfinished,
        "db": str(DB),
        "evidence_label": EVIDENCE_LABEL,
    }


def agenda_items():
    with connect() as db:
        return db.execute(
            """SELECT id,title,status,priority,updated FROM agenda
               ORDER BY CASE status
                   WHEN 'open' THEN 0
                   WHEN 'running' THEN 1
                   WHEN 'blocked' THEN 2
                   ELSE 3
               END, priority DESC, created, id"""
        ).fetchall()


def _claim_next():
    token = uuid.uuid4().hex
    correlation_id = str(uuid.uuid4())
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """SELECT id,title FROM agenda WHERE status='open'
               ORDER BY priority DESC, created, id LIMIT 1"""
        ).fetchone()
        if row is None:
            return None
        agenda_id, title = row["id"], row["title"]
        changed = db.execute(
            "UPDATE agenda SET status='running',updated=? WHERE id=? AND status='open'",
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
            """INSERT INTO executions
               (id,agenda_id,attempt,status,action,input,started_at,claim_generation,lease_token,
                worker_pid,lease_proc_start,correlation_id,artifact_relpath,claimed_verdict)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (execution_id, agenda_id, attempt, "running", action, action_input, now(),
             attempt, token, os.getpid(), proc_start_token(os.getpid()), correlation_id, relpath,
             "accepted"),
        )
    event("execution.notice", {"execution_id": execution_id, "agenda_id": agenda_id, "attempt": attempt})
    event("loop.notice", {"execution_id": execution_id, "agenda_id": agenda_id, "stage": "NOTICE", "evidence_label": EVIDENCE_LABEL})
    event("execution.think", {"execution_id": execution_id, "available_actions": ["remember"]})
    event("loop.think", {"execution_id": execution_id, "plan": "bounded remember action"})
    event("execution.choose", {"execution_id": execution_id, "action": action})
    event("loop.choose", {"execution_id": execution_id, "action": action, "allowlisted": action == "remember"})
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


def _finish_execution(task, status_value, result=None, error=None):
    ts = now()
    with connect() as db:
        updated = db.execute(
            """UPDATE executions SET status=?,result=?,error=?,completed_at=?
               WHERE id=? AND status='running' AND lease_token=?""",
            (status_value, result, str(error) if error is not None else None, ts, task["id"], task["lease_token"]),
        ).rowcount
        if updated != 1:
            return False
        agenda_status = "complete" if status_value == "succeeded" else "blocked"
        db.execute(
            "UPDATE agenda SET status=?,updated=? WHERE id=? AND status='running'",
            (agenda_status, ts, task["agenda_id"]),
        )
    event("execution.finished" if status_value == "succeeded" else "execution.failed", {
        "execution_id": task["id"],
        "agenda_id": task["agenda_id"],
        "status": status_value,
        "result": result,
        "error": str(error) if error is not None else None,
    })
    event("agenda.updated", {"agenda_id": task["agenda_id"], "status": agenda_status})
    event("loop.update_agenda", {
        "execution_id": task["id"],
        "agenda_id": task["agenda_id"],
        "status": agenda_status,
        "stage": "UPDATE AGENDA",
    })
    return True


def _pause_after_claim(task):
    pause = os.environ.get("LEQUTIS_PAUSE_AFTER_CLAIM")
    if not pause:
        return
    folder = Path(pause)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "claimed").write_text(json.dumps({
        "execution_id": task["id"],
        "lease_token": task["lease_token"],
        "pid": os.getpid(),
    }), encoding="utf-8")
    deadline = time.time() + 20
    while time.time() < deadline and not (folder / "release").exists():
        time.sleep(0.02)


def _verify_independently(task, digest):
    challenge = uuid.uuid4().hex
    with connect() as db:
        db.execute(
            "UPDATE executions SET expected_sha256=?, verifier_challenge=? WHERE id=? AND lease_token=?",
            (digest, challenge, task["id"], task["lease_token"]),
        )
    proc = subprocess.Popen(
        [sys.executable, str(VERIFIER), "--db", str(DB), "--execution-id", task["id"],
         "--artifact-root", str(artifact_root()), "--challenge", challenge],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    stdout, stderr = proc.communicate(timeout=30)
    if proc.returncode != 0:
        return {"verdict": "rejected", "reason": "verifier_process_failed", "stderr": stderr, "verifier_pid": proc.pid}
    reported = json.loads(stdout)
    if reported.get("verifier_pid") != proc.pid or reported.get("worker_self_report_consulted") is not False:
        return {"verdict": "rejected", "reason": "verifier_identity_rejected", "verifier_pid": proc.pid}
    return reported


def run_once():
    task = _claim_next()
    if task is None:
        return {"status": "idle", "evidence_label": EVIDENCE_LABEL}
    _pause_after_claim(task)
    try:
        if task["action"] != "remember":
            raise ValueError("No safe deterministic action supports this goal")
        if not task["input"].strip():
            raise ValueError("remember action requires non-empty text")
        event("loop.act", {"execution_id": task["id"], "action": "remember", "stage": "ACT"})
        memory_id = remember(task["input"])
        with connect() as db:
            observed = db.execute("SELECT content FROM memory WHERE id=?", (memory_id,)).fetchone()
        if observed is None or observed[0] != task["input"]:
            raise RuntimeError("Action result could not be observed")
        document = artifact_document(task["correlation_id"], task["id"], observed[0])
        digest = hashlib.sha256(document).hexdigest()
        root = artifact_root()
        root.mkdir(parents=True, exist_ok=True)
        path = root / task["artifact_relpath"]
        if not ARTIFACT_NAME.fullmatch(path.name):
            raise RuntimeError("artifact path is not allowlisted")
        path.write_bytes(b"corrupt\n" if os.environ.get("LEQUTIS_CORRUPT_ARTIFACT") == "1" else document)
        (root / "receipts").mkdir(exist_ok=True)
        receipt = root / "receipts" / (task["correlation_id"] + "-stdout.txt")
        receipt.write_text(
            EVIDENCE_LABEL + "\nartifact correlation_id=" + task["correlation_id"] + " sha256=" + digest + "\n",
            encoding="utf-8",
        )
        verdict = _verify_independently(task, digest)
        if verdict.get("verdict") != "accepted":
            event("loop.observe", {"execution_id": task["id"], "verdict": verdict.get("verdict"), "stage": "OBSERVE"})
            event("loop.evaluate", {"execution_id": task["id"], "passed": False, "stage": "EVALUATE"})
            _finish_execution(task, "failed", error=verdict.get("reason"))
            return {
                "status": "failed",
                "agenda_id": task["agenda_id"],
                "error": verdict.get("reason"),
                "verifier": verdict,
                "evidence_label": EVIDENCE_LABEL,
            }
        event("execution.observe", {"execution_id": task["id"], "memory_id": memory_id, "content": observed[0]})
        event("loop.observe", {
            "execution_id": task["id"],
            "memory_id": memory_id,
            "content_sha256": verdict.get("content_sha256"),
            "correlation_id": task["correlation_id"],
            "worker_self_report_accepted": False,
            "stage": "OBSERVE",
        })
        result = json.dumps({"memory_id": memory_id, "content": observed[0], "correlation_id": task["correlation_id"]})
        event("execution.evaluate", {"execution_id": task["id"], "success": True})
        event("loop.evaluate", {"execution_id": task["id"], "passed": True, "stage": "EVALUATE"})
        experience_id = remember("Successful execution of agenda item: " + task["title"], kind="experience")
        event("execution.learn", {"execution_id": task["id"], "learned": True})
        event("loop.learn", {"execution_id": task["id"], "learned": True, "stage": "LEARN"})
        event("loop.remember", {"execution_id": task["id"], "memory_id": memory_id, "experience_id": experience_id, "stage": "REMEMBER"})
        if not _finish_execution(task, "succeeded", result=result):
            raise RuntimeError("stale fence rejected completion")
        return {
            "status": "succeeded",
            "agenda_id": task["agenda_id"],
            "result": json.loads(result),
            "verifier": verdict,
            "evidence_label": EVIDENCE_LABEL,
        }
    except Exception as exc:
        try:
            event("execution.evaluate", {"execution_id": task["id"], "success": False, "error": str(exc)})
            event("loop.evaluate", {"execution_id": task["id"], "passed": False, "stage": "EVALUATE"})
        finally:
            _finish_execution(task, "failed", error=exc)
        return {"status": "failed", "agenda_id": task["agenda_id"], "error": str(exc), "evidence_label": EVIDENCE_LABEL}


def recover_interrupted():
    with connect() as db:
        rows = db.execute(
            "SELECT id,agenda_id,worker_pid,lease_proc_start FROM executions WHERE status='running'"
        ).fetchall()
    recovered = []
    skipped = []
    for row in rows:
        if process_is_live(row["worker_pid"], row["lease_proc_start"]):
            skipped.append(row["id"])
            continue
        recovered.append((row["id"], row["agenda_id"]))
    ts = now()
    with connect() as db:
        for execution_id, agenda_id in recovered:
            db.execute(
                """UPDATE executions SET status='interrupted', error=?, completed_at=?, lease_token=NULL
                   WHERE id=? AND status='running'""",
                ("Process stopped before execution finished", ts, execution_id),
            )
            db.execute(
                "UPDATE agenda SET status='blocked', updated=? WHERE id=? AND status='running'",
                (ts, agenda_id),
            )
    for execution_id, agenda_id in recovered:
        event("execution.interrupted", {"execution_id": execution_id, "agenda_id": agenda_id})
        event("agenda.updated", {"agenda_id": agenda_id, "status": "blocked"})
    return {"recovered": len(recovered), "live_skipped": skipped, "evidence_label": EVIDENCE_LABEL}


def retry_agenda(agenda_id):
    with connect() as db:
        latest = db.execute(
            "SELECT status FROM executions WHERE agenda_id=? ORDER BY attempt DESC LIMIT 1",
            (agenda_id,),
        ).fetchone()
        if latest is None or latest[0] not in ("failed", "interrupted"):
            return False
        changed = db.execute(
            "UPDATE agenda SET status='open', updated=? WHERE id=? AND status='blocked'",
            (now(), agenda_id),
        ).rowcount
    if changed:
        event("agenda.retry_requested", {"agenda_id": agenda_id})
    return changed == 1


def verify_events():
    previous = "GENESIS"
    with connect() as db:
        rows = db.execute(
            "SELECT ts,event_type,payload,previous_hash,event_hash FROM events ORDER BY seq"
        ).fetchall()
    for sequence, row in enumerate(rows, 1):
        raw = previous + "|" + row[0] + "|" + row[1] + "|" + row[2]
        expected = hashlib.sha256(raw.encode()).hexdigest()
        if row[3] != previous or row[4] != expected:
            return {"valid": False, "events": len(rows), "invalid_sequence": sequence, "evidence_label": EVIDENCE_LABEL}
        previous = row[4]
    return {"valid": True, "events": len(rows), "evidence_label": EVIDENCE_LABEL}


def attempt_stale_complete(execution_id, token):
    with connect() as db:
        row = db.execute("SELECT status,lease_token FROM executions WHERE id=?", (execution_id,)).fetchone()
        if row is None or row["lease_token"] != token or row["status"] != "running":
            return {"accepted": False, "reason": "stale_fence", "evidence_label": EVIDENCE_LABEL}
        accepted = db.execute(
            """SELECT 1 FROM verifier_observations
               WHERE execution_id=? AND verdict='accepted' AND worker_self_report_consulted=0""",
            (execution_id,),
        ).fetchone()
        if accepted is None:
            return {"accepted": False, "reason": "verifier_required", "evidence_label": EVIDENCE_LABEL}
    return {"accepted": False, "reason": "completion_requires_current_lease", "evidence_label": EVIDENCE_LABEL}


def heartbeat():
    event("heartbeat", {"status": "alive", "host": "A71"})
    print(json.dumps(status(), indent=2))


def _parse_goal(argv):
    args = argv[2:]
    if args[:1] == ["--key"]:
        if len(args) < 3:
            raise SystemExit("goal --key requires a key and a title")
        return args[1], " ".join(args[2:]).strip()
    return None, " ".join(args).strip()


def main():
    try:
        init()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            sys.stderr.write(str(exc) + "\n")
            raise SystemExit(3)
        raise

    if len(sys.argv) < 2:
        print("LeQutis commands: init | status | heartbeat | remember | goal | agenda | run-once | recover | retry | verify-events | complete | daemon")
        return

    cmd = sys.argv[1]
    if cmd == "init":
        print(json.dumps(status(), indent=2))
    elif cmd == "status":
        print(json.dumps(status(), indent=2))
    elif cmd == "heartbeat":
        heartbeat()
    elif cmd == "remember":
        text = " ".join(sys.argv[2:]).strip()
        if not text:
            raise SystemExit("remember requires text")
        remember(text)
        print("MEMORY STORED")
    elif cmd == "goal":
        key, title = _parse_goal(sys.argv)
        if not title:
            raise SystemExit("goal requires title")
        outcome = add_goal(title, idempotency_key=key)
        if outcome["status"] == "conflict":
            print(json.dumps(outcome, sort_keys=True))
            raise SystemExit(1)
        print("AGENDA ITEM EXISTS" if outcome["status"] == "duplicate" else "AGENDA ITEM CREATED")
    elif cmd == "agenda":
        print(json.dumps([
            {"id": row[0], "title": row[1], "status": row[2], "priority": row[3], "updated": row[4]}
            for row in agenda_items()
        ], indent=2))
    elif cmd == "run-once":
        result = run_once()
        print(json.dumps(result, indent=2))
        if result["status"] == "failed":
            raise SystemExit(1)
    elif cmd == "recover":
        print(json.dumps(recover_interrupted()))
    elif cmd == "retry":
        if len(sys.argv) != 3:
            raise SystemExit("retry requires an agenda id")
        if not retry_agenda(sys.argv[2]):
            raise SystemExit("agenda item is not recoverable")
        print("AGENDA ITEM REOPENED")
    elif cmd == "verify-events":
        result = verify_events()
        print(json.dumps(result, indent=2))
        if not result["valid"]:
            raise SystemExit(1)
    elif cmd == "complete":
        if len(sys.argv) != 4:
            raise SystemExit("complete requires an execution id and a lease token")
        print(json.dumps(attempt_stale_complete(sys.argv[2], sys.argv[3]), sort_keys=True))
        raise SystemExit(1)
    elif cmd == "daemon":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 60
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
