"""Bounded canonical intake on the existing kernel WAL database.

Records claims, not execution verdicts. No schema migration, database creation,
shell execution, completion promotion, or network access is performed here.
The stdio host authenticates its caller; ``principal`` is host configuration,
never a value accepted from the tool request.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from typing import Any

import lequtis as L
from workers import SAFE_ACTIONS

KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
KINDS = {"semantic", "episodic", "working"}
MAX_BYTES = 65536


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _validate(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict) or set(request) != {
        "idempotency_key", "title", "action", "payload", "receipt", "memory"
    }:
        raise ValueError("request_fields_invalid")
    if not isinstance(request["idempotency_key"], str) or not KEY.fullmatch(request["idempotency_key"]):
        raise ValueError("idempotency_key_invalid")
    if not isinstance(request["title"], str) or not 1 <= len(request["title"].strip()) <= 2000:
        raise ValueError("title_invalid")
    if not isinstance(request["action"], str) or request["action"] not in SAFE_ACTIONS:
        raise ValueError("action_not_allowlisted")
    if not isinstance(request["payload"], dict) or not isinstance(request["receipt"], dict):
        raise ValueError("payload_and_receipt_must_be_objects")
    memory = request["memory"]
    if not isinstance(memory, dict) or set(memory) != {"kind", "content"}:
        raise ValueError("memory_fields_invalid")
    if not isinstance(memory["kind"], str) or memory["kind"] not in KINDS:
        raise ValueError("memory_kind_invalid")
    if not isinstance(memory["content"], str) or not 1 <= len(memory["content"].strip()) <= 16000:
        raise ValueError("memory_content_invalid")
    # JSON round-trip produces an independent, finite JSON-only snapshot.
    encoded = _json(request)
    if len(encoded.encode()) > MAX_BYTES:
        raise ValueError("request_too_large")
    return json.loads(encoded)


def _open() -> sqlite3.Connection:
    # mode=rw refuses to create an alternative empty database.
    if L.DB.is_symlink():
        raise ValueError("canonical_database_symlink_rejected")
    db = sqlite3.connect(L.DB.resolve().as_uri() + "?mode=rw", uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=FULL")
    if db.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
        db.close()
        raise ValueError("canonical_database_not_wal")
    return db


def _schema(db: sqlite3.Connection) -> None:
    for table, expected in L.REQUIRED_COLUMNS.items():
        found = L._columns(db, table)
        if found is None or not expected.issubset(found):
            raise ValueError("canonical_schema_incompatible")
    row = db.execute("SELECT value FROM identity WHERE key='schema_revision'").fetchone()
    if row is None or row[0] != L.SCHEMA_REVISION:
        raise ValueError("canonical_schema_incompatible")


def _ids(principal: str, key: str) -> dict[str, str]:
    scope = _digest({"principal": principal, "key": key})
    return {
        "key": "canonical-intake:" + scope,
        **{name: str(uuid.uuid5(uuid.NAMESPACE_URL, "lequtis:intake:" + scope + ":" + name))
           for name in ("agenda_id", "task_id", "memory_id", "event_id")},
    }


def _existing(db: sqlite3.Connection, ids: dict[str, str]) -> dict[str, Any] | None:
    event = db.execute("SELECT * FROM events WHERE event_id=?", (ids["event_id"],)).fetchone()
    if event is None:
        return None
    payload = json.loads(event["payload"])
    task = db.execute("SELECT * FROM tasks WHERE id=?", (ids["task_id"],)).fetchone()
    memory = db.execute("SELECT * FROM memory WHERE id=?", (ids["memory_id"],)).fetchone()
    agenda = db.execute("SELECT * FROM agenda WHERE id=?", (ids["agenda_id"],)).fetchone()
    if task is None or memory is None or agenda is None:
        raise ValueError("canonical_intake_incomplete")
    # Bind original intake to read-back; later task state may legitimately change.
    request = payload["request"]
    if (task["idempotency_key"] != ids["key"] or task["agenda_id"] != ids["agenda_id"]
        or task["title"] != request["title"] or task["action"] != request["action"]
        or json.loads(task["payload"]) != request["payload"]
        or agenda["title"] != request["title"] or agenda["request_hash"] != payload["request_hash"]
        or memory["kind"] != "submitted_" + request["memory"]["kind"]
        or memory["content"] != request["memory"]["content"]
        or _digest(request) != payload["request_hash"]):
        raise ValueError("canonical_intake_binding_mismatch")
    return {
        "ok": True, "live_host": False, "scope": "canonical_intake_only",
        "request_hash": payload["request_hash"], "principal": payload["principal"],
        "agenda": dict(agenda), "task": dict(task), "memory": dict(memory),
        "event": dict(event), "receipt_trust": "unverified_claim",
    }


def _verify_chain(db: sqlite3.Connection) -> None:
    previous = "GENESIS"
    for row in db.execute("SELECT * FROM events ORDER BY seq"):
        raw = previous + "|" + row["ts"] + "|" + row["event_type"] + "|" + row["payload"]
        if row["previous_hash"] != previous or hashlib.sha256(raw.encode()).hexdigest() != row["event_hash"]:
            raise ValueError("canonical_event_chain_invalid")
        previous = row["event_hash"]


def read_intake(principal: str, key: str) -> dict[str, Any]:
    if not isinstance(principal, str) or not KEY.fullmatch(principal):
        raise ValueError("principal_invalid")
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise ValueError("idempotency_key_invalid")
    db = _open()
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        _schema(db)
        _verify_chain(db)
        found = _existing(db, _ids(principal, key))
        return found or {"ok": False, "live_host": False, "reason": "intake_not_found"}
    finally:
        db.close()


def write_intake(principal: str, request: Any) -> dict[str, Any]:
    if not isinstance(principal, str) or not KEY.fullmatch(principal):
        raise ValueError("principal_invalid")
    request = _validate(request)
    ids = _ids(principal, request["idempotency_key"])
    digest = _digest(request)
    db = _open()
    try:
        # Lock before inspecting the tip; concurrent intakes serialize correctly.
        db.execute("BEGIN IMMEDIATE")
        _schema(db)
        _verify_chain(db)
        existing = _existing(db, ids)
        if existing is not None:
            if existing["request_hash"] != digest:
                raise ValueError("idempotency_key_reused_with_different_request")
            db.rollback()
            return {**existing, "status": "duplicate"}
        ts = L.now()
        db.execute("INSERT INTO agenda(id,title,status,priority,created,updated,idempotency_key,request_hash) VALUES (?,?,?,?,?,?,?,?)",
                   (ids["agenda_id"], request["title"], "awaiting_approval", 10, ts, ts, ids["key"], digest))
        db.execute("INSERT INTO tasks(id,agenda_id,idempotency_key,title,action,status,payload,created,updated) VALUES (?,?,?,?,?,?,?,?,?)",
                   (ids["task_id"], ids["agenda_id"], ids["key"], request["title"], request["action"], "awaiting_approval", _json(request["payload"]), ts, ts))
        db.execute("INSERT INTO memory(id,kind,content,created,updated) VALUES (?,?,?,?,?)",
                   (ids["memory_id"], "submitted_" + request["memory"]["kind"], request["memory"]["content"], ts, ts))
        payload = _json({"principal": principal, "request_hash": digest, "request": request,
                         "ids": ids, "receipt_trust": "unverified_claim"})
        tip = db.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        previous = tip[0] if tip else "GENESIS"
        event_type = "canonical.intake"
        event_hash = hashlib.sha256((previous + "|" + ts + "|" + event_type + "|" + payload).encode()).hexdigest()
        db.execute("INSERT INTO events(event_id,ts,event_type,payload,previous_hash,event_hash) VALUES (?,?,?,?,?,?)",
                   (ids["event_id"], ts, event_type, payload, previous, event_hash))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    # New connection and read transaction, rather than echoing input as proof.
    return {**read_intake(principal, request["idempotency_key"]), "status": "created"}
