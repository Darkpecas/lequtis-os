"""Governed canonical completion candidate for the existing LeQutis kernel.

NO LIVE HOST PROOF. Disabled unless host enables explicit local gates.
An independently keyed verifier attests to evidence; signatures alone do
not establish that the verifier actually observed Hostinger/Hermes.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

MAX_BYTES = 16384
REQUIRED = frozenset({
    "task_id", "idempotency_key", "correlation_id", "executor_id",
    "verifier_id", "receipt_sha256", "external_evidence_sha256",
    "verdict", "observed_utc",
})


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _reject(reason):
    return {"ok": False, "reason": reason, "live_verified": False}


def _chain_tip(db):
    previous = "GENESIS"
    for row in db.execute("SELECT seq,ts,event_type,payload,previous_hash,event_hash FROM events ORDER BY seq"):
        digest = hashlib.sha256((previous + "|" + row["ts"] + "|" + row["event_type"] + "|" + row["payload"]).encode()).hexdigest()
        if row["previous_hash"] != previous or row["event_hash"] != digest:
            raise ValueError("event_chain_invalid_at_" + str(row["seq"]))
        previous = digest
    return previous


def _append(db, event_id, timestamp, name, payload, previous):
    raw = _canonical(payload)
    digest = hashlib.sha256((previous + "|" + timestamp + "|" + name + "|" + raw).encode()).hexdigest()
    db.execute(
        "INSERT INTO events(event_id,ts,event_type,payload,previous_hash,event_hash) VALUES (?,?,?,?,?,?)",
        (event_id, timestamp, name, raw, previous, digest),
    )
    return digest


def complete_with_verifier_attestation(envelope, *, key=None):
    """Commit separately attested evaluation, learning and agenda as one transaction.

    The independently issued HMAC key is injected by a trusted local verifier
    controller, NOT supplied through MCP arguments. A signature proves key
    possession only. It is not standalone evidence of external execution.
    """
    if os.environ.get("LEQUTIS_CANONICAL_WRITE") != "1":
        return _reject("canonical_write_disabled")
    if os.environ.get("LEQUTIS_TRUSTED_LOCAL_TRANSPORT") != "1":
        return _reject("trusted_transport_not_attested")
    if os.environ.get("LEQUTIS_VERIFIER_COMPLETION") != "1":
        return _reject("verifier_completion_disabled")
    if not os.environ.get("LEQUTIS_STATE"):
        return _reject("explicit_state_required")
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
        return _reject("invalid_envelope")
    payload = envelope["payload"]
    if not isinstance(payload, dict) or set(payload) != REQUIRED:
        return _reject("invalid_payload")
    if any(not isinstance(v, str) or not v or len(v) > 256 for v in payload.values()):
        return _reject("invalid_field")
    if payload["verdict"] not in {"success", "failure"}:
        return _reject("invalid_verdict")
    if payload["executor_id"] == payload["verifier_id"]:
        return _reject("verifier_not_independent")
    for field in ("receipt_sha256", "external_evidence_sha256"):
        value = payload[field]
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            return _reject("invalid_evidence_digest")
    try:
        observed = datetime.fromisoformat(payload["observed_utc"].replace("Z", "+00:00"))
        if observed.tzinfo is None:
            return _reject("naive_observation_time")
        delta = (datetime.now(timezone.utc) - observed).total_seconds()
        if delta > 3600 or delta < -60:
            return _reject("stale_or_future_attestation")
    except (ValueError, OverflowError):
        return _reject("bad_observation_time")

    material = key if key is not None else os.environ.get("LEQUTIS_VERIFIER_HMAC_KEY", "").encode()
    if not isinstance(material, bytes) or len(material) < 32:
        return _reject("verifier_key_unavailable")
    if len(_canonical(payload).encode()) > MAX_BYTES:
        return _reject("payload_too_large")
    expected = hmac.new(material, _canonical(payload).encode("utf-8"), hashlib.sha256).hexdigest()
    if not isinstance(envelope["signature"], str) or not hmac.compare_digest(envelope["signature"], expected):
        return _reject("invalid_verifier_signature")

    import lequtis as L
    if not L.DB.is_file():
        return _reject("canonical_database_missing")
    db = L.connect()
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN IMMEDIATE")
        previous = _chain_tip(db)
        task = db.execute(
            "SELECT id,idempotency_key,title,action,status,payload,agenda_id FROM tasks WHERE id=?",
            (payload["task_id"],),
        ).fetchone()
        if task is None or task["idempotency_key"] != payload["idempotency_key"]:
            raise ValueError("task_identity_mismatch")
        verification_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "lequtis:verification:" + payload["idempotency_key"]))
        old = db.execute("SELECT payload,event_hash FROM events WHERE event_id=?", (verification_id,)).fetchone()
        attested_raw = _canonical(payload)
        if old is not None:
            if old["payload"] != attested_raw:
                raise ValueError("verification_conflict")
            db.commit()
            return {"ok": True, "duplicate": True, "event_hash": old["event_hash"],
                    "verification": "cryptographic_attestation_only", "live_verified": False}
        if task["status"] != "pending":
            raise ValueError("task_not_pending")
        # Match an existing unverified receipt written by the canonical writer.
        receipt_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "lequtis:canonical:receipt:" + payload["idempotency_key"]))
        receipt_row = db.execute(
            "SELECT payload FROM events WHERE event_id=? AND event_type='adapter.receipt_recorded'",
            (receipt_id,),
        ).fetchone()
        if receipt_row is None:
            raise ValueError("missing_recorded_receipt")
        receipt_record = json.loads(receipt_row["payload"])
        if receipt_record.get("mode") != "receipt" or receipt_record.get("idempotency_key") != payload["idempotency_key"]:
            raise ValueError("receipt_identity_mismatch")
        if _digest(receipt_record["receipt"]) != payload["receipt_sha256"]:
            raise ValueError("receipt_digest_mismatch")
        # Prevent a caller's signed assertion from becoming a claim of verified
        # external execution; downstream release gates must validate provenance.
        verdict = payload["verdict"]
        now = L.now()
        db.execute(
            "UPDATE tasks SET status=?,result=?,error=?,updated=? WHERE id=? AND status='pending'",
            ("completed" if verdict == "success" else "failed",
             _canonical({"verdict": verdict, "verification": "attested_not_live",
                         "external_evidence_sha256": payload["external_evidence_sha256"]}),
             None if verdict == "success" else "independently_attested_failure", now, task["id"]),
        )
        memory_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "lequtis:verified-memory:" + payload["idempotency_key"]))
        db.execute(
            "INSERT INTO memory(id,kind,content,created,updated) VALUES (?,?,?,?,?)",
            (memory_id, "learning.attested_not_live",
             _canonical({"task_id": task["id"], "verdict": verdict,
                         "evidence": payload["external_evidence_sha256"],
                         "verifier": payload["verifier_id"]}), now, now),
        )
        if task["agenda_id"] is not None and verdict == "success":
            row = db.execute("SELECT status FROM agenda WHERE id=?", (task["agenda_id"],)).fetchone()
            if row is None or row["status"] != "open":
                raise ValueError("agenda_not_open")
            db.execute("UPDATE agenda SET status='done',updated=? WHERE id=?", (now, task["agenda_id"]))
        tip = _append(db, verification_id, now, "adapter.verification_attested", payload, previous)
        tip = _append(db, str(uuid.uuid5(uuid.NAMESPACE_URL, "lequtis:learning-event:" + payload["idempotency_key"])),
                      now, "loop.learn_attested", {"task_id": task["id"], "memory_id": memory_id}, tip)
        tip = _append(db, str(uuid.uuid5(uuid.NAMESPACE_URL, "lequtis:agenda-event:" + payload["idempotency_key"])),
                      now, "loop.agenda_attested", {"agenda_id": task["agenda_id"], "verdict": verdict}, tip)
        db.commit()
        return {"ok": True, "duplicate": False, "task_id": task["id"],
                "memory_id": memory_id, "event_hash": tip,
                "verification": "cryptographic_attestation_only", "live_verified": False}
    except (sqlite3.Error, ValueError, TypeError, KeyError) as error:
        if db.in_transaction:
            db.rollback()
        return _reject(str(error))
    finally:
        db.close()
