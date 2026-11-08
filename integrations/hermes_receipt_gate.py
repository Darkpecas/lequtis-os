#!/usr/bin/env python3
"""Fail-closed evidence contract for a *candidate* Hermes receipt bridge.

This module does NOT execute Hermes or claim a live integration. It verifies
a signed receipt against canonical LeQutis task rows without changing state.
Signing keys must never be stored in the repository or logs.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import sqlite3
from datetime import datetime, timezone

FIELDS = ("task_id", "correlation_id", "action", "status", "result_sha256", "timestamp")
ALLOWED = {"completed", "failed"}

def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def result_hash(result: object) -> str:
    return hashlib.sha256(canonical(result)).hexdigest()

def sign_for_disposable_test(payload: dict, key: bytes) -> str:
    """Test-fixture signing only; deployed receipts must originate from Hermes."""
    if len(key) < 32:
        raise ValueError("signing key too short")
    return hmac.new(key, canonical(payload), hashlib.sha256).hexdigest()

def verify_receipt(db_path: str, receipt: dict, key: bytes, *, max_age_seconds: int = 300,
                   now: datetime | None = None) -> dict:
    """Read-only candidate validation; positive result is NOT proof of live execution."""
    def reject(reason: str) -> dict:
        return {"ok": False, "reason": reason, "evidence_level": "receipt_contract_only"}
    if len(key) < 32:
        return reject("missing_trusted_key")
    if not isinstance(receipt, dict) or set(receipt) != {"payload", "signature"}:
        return reject("invalid_envelope")
    p = receipt["payload"]
    if not isinstance(p, dict) or set(p) != set(FIELDS):
        return reject("invalid_payload")
    if not all(isinstance(p[k], str) and p[k] for k in FIELDS):
        return reject("invalid_field")
    if p["status"] not in ALLOWED:
        return reject("invalid_status")
    try:
        timestamp = datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            return reject("naive_timestamp")
        current = now or datetime.now(timezone.utc)
        age = (current - timestamp).total_seconds()
        if age < -30 or age > max_age_seconds:
            return reject("receipt_outside_window")
    except (ValueError, TypeError, OverflowError):
        return reject("bad_timestamp")
    mac = hmac.new(key, canonical(p), hashlib.sha256).hexdigest()
    sig = receipt["signature"]
    if not isinstance(sig, str) or not hmac.compare_digest(sig, mac):
        return reject("invalid_signature")
    try:
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            row = db.execute(
                "SELECT id, action, status, result FROM tasks WHERE id=?", (p["task_id"],)
            ).fetchone()
        finally:
            db.close()
    except sqlite3.Error:
        return reject("canonical_state_unavailable")
    if row is None:
        return reject("unknown_task")
    if row["action"] != p["action"] or row["status"] != p["status"]:
        return reject("canonical_task_mismatch")
    if row["status"] == "completed":
        try:
            stored_result = json.loads(row["result"] or "null")
        except (ValueError, TypeError):
            return reject("malformed_canonical_result")
        if result_hash(stored_result) != p["result_sha256"]:
            return reject("result_hash_mismatch")
    elif p["result_sha256"] != result_hash(None):
        return reject("failed_result_hash_mismatch")
    return {
        "ok": True,
        "task_id": p["task_id"],
        "correlation_id": p["correlation_id"],
        "evidence_level": "signed_receipt_matches_canonical_state",
        "live_execution_verified": False,
    }
