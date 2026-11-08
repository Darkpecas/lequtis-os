"""Transactional, fail-closed canonical-write gate for the existing LeQutis kernel.

No new database or sovereign authority. Receipts are unverified observations,
not proof that an external action completed.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid

MAX_TEXT = 16000


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _text(value, name, maximum=MAX_TEXT):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be a nonempty string of at most {maximum} characters")
    return value


def _chain_tip(db):
    previous = "GENESIS"
    for row in db.execute(
        "SELECT seq,ts,event_type,payload,previous_hash,event_hash "
        "FROM events ORDER BY seq"
    ):
        raw = previous + "|" + row["ts"] + "|" + row["event_type"] + "|" + row["payload"]
        digest = hashlib.sha256(raw.encode()).hexdigest()
        if row["previous_hash"] != previous or row["event_hash"] != digest:
            raise RuntimeError(f"event_chain_invalid_at_{row['seq']}")
        previous = digest
    return previous


def canonical_commit(record):
    """Commit an intent or observational receipt atomically with audit evidence.

    An existing, host-authorised stdio process must explicitly opt in.
    There is no caller-selectable database path or arbitrary SQL.
    """
    if os.environ.get("LEQUTIS_CANONICAL_WRITE") != "1":
        return {"ok": False, "reason": "canonical_write_disabled"}
    if not os.environ.get("LEQUTIS_STATE"):
        return {"ok": False, "reason": "explicit_state_required"}
    # Host-side caller authentication must be independently enforced.
    # Environment attestation is defense in depth, not authentication.
    if os.environ.get("LEQUTIS_TRUSTED_LOCAL_TRANSPORT") != "1":
        return {"ok": False, "reason": "trusted_transport_not_attested"}
    if not isinstance(record, dict):
        return {"ok": False, "reason": "invalid_record"}
    try:
        import lequtis as L
        mode = record.get("mode")
        if mode not in ("intent", "receipt"):
            raise ValueError("mode must be intent or receipt")
        key = _text(record.get("idempotency_key"), "idempotency_key", 200)
        # Fail closed on a redirected state database; never follow a symlink
        # supplied through LEQUTIS_STATE to an unintended database.
        if L.DB.is_symlink():
            raise RuntimeError("canonical_database_symlink_rejected")
        if not L.DB.is_file():
            raise RuntimeError("canonical_database_missing")
        if mode == "intent":
            title = _text(record.get("title"), "title", 300)
            action = _text(record.get("action"), "action", 100)
            if action not in L.ACTIONS or action == "deliberate_fail":
                raise ValueError("action_not_approved")
            payload = record.get("payload", {})
            if not isinstance(payload, dict) or len(_json(payload)) > MAX_TEXT:
                raise ValueError("invalid_payload")
            agenda_id = record.get("agenda_id")
            if agenda_id is not None:
                _text(agenda_id, "agenda_id", 200)
            canonical = {"mode": mode, "idempotency_key": key, "title": title,
                         "action": action, "payload": payload, "agenda_id": agenda_id}
        else:
            receipt = record.get("receipt")
            if not isinstance(receipt, dict) or not receipt or len(_json(receipt)) > MAX_TEXT:
                raise ValueError("invalid_receipt")
            note = record.get("memory")
            if note is not None:
                _text(note, "memory")
            canonical = {"mode": mode, "idempotency_key": key,
                         "receipt": receipt, "memory": note}

        receipt_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "lequtis:canonical:" + mode + ":" + key))
        payload_text = _json(canonical)
        with L.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            tip = _chain_tip(db)
            existing = db.execute(
                "SELECT payload,event_hash FROM events WHERE event_id=?", (receipt_id,)
            ).fetchone()
            if existing is not None:
                if existing["payload"] != payload_text:
                    raise ValueError("idempotency_key_conflict")
                return {"ok": True, "duplicate": True, "event_hash": existing["event_hash"],
                        "event_id": receipt_id, "verification": "unverified"}
            ts = L.now()
            if mode == "intent":
                row = db.execute(
                    "SELECT id,title,action,payload,agenda_id FROM tasks WHERE idempotency_key=?",
                    (key,)
                ).fetchone()
                if row is None:
                    task_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "lequtis:canonical-task:" + key))
                    db.execute(
                        "INSERT INTO tasks (id,agenda_id,idempotency_key,title,action,status,"
                        "payload,result,error,created,updated) VALUES (?,?,?,?,?,'pending',?,NULL,NULL,?,?)",
                        (task_id, agenda_id, key, title, action, _json(payload), ts, ts)
                    )
                else:
                    if (row["title"], row["action"], row["payload"], row["agenda_id"]) != (
                        title, action, _json(payload), agenda_id
                    ):
                        raise ValueError("idempotency_key_conflict")
                    task_id = row["id"]
            else:
                row = db.execute(
                    "SELECT id FROM tasks WHERE idempotency_key=?", (key,)
                ).fetchone()
                if row is None:
                    raise ValueError("unknown_task_intent")
                task_id = row["id"]
                # Do not mark completed; the Verifier/Auditor must separately
                # establish whether the observed action actually succeeded.
                if canonical["memory"] is not None:
                    mid = str(uuid.uuid5(uuid.NAMESPACE_URL, "lequtis:canonical-memory:" + key))
                    db.execute(
                        "INSERT INTO memory(id,kind,content,created,updated) VALUES "
                        "(?,'observation_unverified',?,?,?)",
                        (mid, canonical["memory"], ts, ts)
                    )
            event_type = "adapter.intent_recorded" if mode == "intent" else "adapter.receipt_recorded"
            digest = hashlib.sha256(
                (tip + "|" + ts + "|" + event_type + "|" + payload_text).encode()
            ).hexdigest()
            db.execute(
                "INSERT INTO events(event_id,ts,event_type,payload,previous_hash,event_hash) "
                "VALUES(?,?,?,?,?,?)",
                (receipt_id, ts, event_type, payload_text, tip, digest)
            )
        return {"ok": True, "duplicate": False, "task_id": task_id,
                "event_id": receipt_id, "event_hash": digest,
                "verification": "unverified"}
    except (ValueError, RuntimeError, sqlite3.Error, TypeError) as exc:
        return {"ok": False, "reason": str(exc)}
