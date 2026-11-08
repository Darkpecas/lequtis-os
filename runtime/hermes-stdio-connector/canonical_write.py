"""Idempotent, opt-in canonical write. Host authentication is mandatory upstream.

Stores task intent, caller-supplied (UNVERIFIED) receipt and optional memory in
one SQLite transaction, then appends an event using the existing hash formula.
This is not a remote transport or independent verification mechanism.
"""
import hashlib
import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def commit_record(key, title, receipt, memory="", memory_kind="observation"):
    if os.environ.get("LEQUTIS_CANONICAL_WRITE") != "1":
        return {"ok": False, "reason": "write_disabled"}
    if os.environ.get("LEQUTIS_TRUSTED_LOCAL_TRANSPORT") != "1":
        return {"ok": False, "reason": "trusted_transport_not_attested"}
    if not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z0-9._:-]{8,128}", key):
        return {"ok": False, "reason": "invalid_key"}
    if not isinstance(title, str) or not 0 < len(title.strip()) <= 256:
        return {"ok": False, "reason": "invalid_title"}
    if not isinstance(receipt, dict) or len(canonical(receipt)) > 16384:
        return {"ok": False, "reason": "invalid_receipt"}
    if not isinstance(memory, str) or len(memory) > 8192 or memory_kind not in {"observation", "learning", "research", "operational"}:
        return {"ok": False, "reason": "invalid_memory"}
    state = os.environ.get("LEQUTIS_STATE")
    if not state:
        return {"ok": False, "reason": "explicit_state_required"}
    path = Path(state) / "lequtis.db"
    if path.is_symlink() or not path.is_file():
        return {"ok": False, "reason": "existing_database_required"}
    request_hash = hashlib.sha256(canonical([key, title, receipt, memory, memory_kind]).encode()).hexdigest()
    task_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "lequtis:adapter-task:" + key))
    memory_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "lequtis:adapter-memory:" + key)) if memory else None
    ts = datetime.now(timezone.utc).isoformat()
    db = sqlite3.connect(f"file:{path.resolve()}?mode=rw", uri=True, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"tasks", "events", "memory"} <= tables:
            db.execute("ROLLBACK")
            return {"ok": False, "reason": "schema_mismatch"}
        prior = db.execute("SELECT id,payload FROM tasks WHERE idempotency_key=?", (key,)).fetchone()
        if prior:
            db.execute("ROLLBACK")
            try:
                same = json.loads(prior["payload"]).get("write_digest") == request_hash
            except (ValueError, TypeError, AttributeError):
                same = False
            return ({"ok": True, "replay": True, "task_id": prior["id"], "memory_id": memory_id, "verified": False, "live_host": False}
                    if same else {"ok": False, "reason": "idempotency_conflict"})
        db.execute("INSERT INTO tasks(id,agenda_id,idempotency_key,title,action,status,payload,result,error,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (task_id, None, key, title.strip(), "record_observation", "recorded_unverified",
                    canonical({"write_digest": request_hash}), canonical(receipt), None, ts, ts))
        if memory:
            db.execute("INSERT INTO memory(id,kind,content,created,updated) VALUES(?,?,?,?,?)",
                       (memory_id, memory_kind, memory, ts, ts))
        tip = db.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        previous = tip[0] if tip else "GENESIS"
        event_type = "adapter.recorded_unverified"
        payload = canonical({"task_id": task_id, "write_digest": request_hash, "memory_id": memory_id,
                             "receipt_status": "unverified"})
        digest = hashlib.sha256((previous + "|" + ts + "|" + event_type + "|" + payload).encode()).hexdigest()
        event_id = str(uuid.uuid4())
        db.execute("INSERT INTO events(event_id,ts,event_type,payload,previous_hash,event_hash) VALUES (?,?,?,?,?,?)",
                   (event_id, ts, event_type, payload, previous, digest))
        db.execute("COMMIT")
        return {"ok": True, "replay": False, "task_id": task_id, "event_id": event_id,
                "event_hash": digest, "memory_id": memory_id, "write_digest": request_hash,
                "verified": False, "live_host": False}
    except sqlite3.Error as exc:
        if db.in_transaction:
            db.execute("ROLLBACK")
        return {"ok": False, "reason": "sqlite_error", "error_type": type(exc).__name__}
    finally:
        db.close()
