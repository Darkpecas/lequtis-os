#!/usr/bin/env python3
"""Isolated candidate Hermes receipt checks against the REAL LeQutis kernel."""
import copy
import importlib
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "integrations"))
from hermes_receipt_gate import result_hash, sign_for_disposable_test, verify_receipt

def main():
    checks = 0
    with tempfile.TemporaryDirectory(prefix="lequtis-hermes-contract-") as td:
        os.environ["LEQUTIS_ROOT"] = str(ROOT)
        os.environ["LEQUTIS_STATE"] = td
        os.environ["LEQUTIS_WORKER"] = "deterministic"
        L = importlib.import_module("lequtis")
        L.init()
        choice = {
            "kind": "goal", "idempotency_key": "hermes-receipt-fixture-001",
            "title": "Disposable Hermes receipt fixture", "action": "ping",
            "payload": {"value": "local-fixture"}
        }
        completed = L.act(choice)
        assert completed["ok"], completed
        assert L.verify_event_chain()["ok"]
        checks += 1
        with L.connect() as db:
            row = db.execute(
                "SELECT id, action, status, result FROM tasks WHERE id=?",
                (completed["task_id"],)
            ).fetchone()
        assert row["status"] == "completed"
        key = b"DISPOSABLE-TEST-NOT-A-LIVE-HERMES-KEY-123456789"
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "task_id": row["id"],
            "correlation_id": "test-fixture-only",
            "action": row["action"],
            "status": row["status"],
            "result_sha256": result_hash(json.loads(row["result"])),
            "timestamp": timestamp,
        }
        receipt = {"payload": payload, "signature": sign_for_disposable_test(payload, key)}
        dbpath = str(L.DB)
        accepted = verify_receipt(dbpath, receipt, key)
        assert accepted["ok"] and accepted["live_execution_verified"] is False, accepted
        checks += 1
        bad = copy.deepcopy(receipt)
        bad["payload"]["result_sha256"] = "0" * 64
        assert verify_receipt(dbpath, bad, key)["reason"] == "invalid_signature"
        checks += 1
        bad = copy.deepcopy(receipt)
        bad["signature"] = "0" * 64
        assert verify_receipt(dbpath, bad, key)["reason"] == "invalid_signature"
        checks += 1
        assert verify_receipt(dbpath, receipt, b"short")["reason"] == "missing_trusted_key"
        checks += 1
        bad = copy.deepcopy(receipt)
        bad["payload"]["task_id"] = "nonexistent"
        bad["signature"] = sign_for_disposable_test(bad["payload"], key)
        assert verify_receipt(dbpath, bad, key)["reason"] == "unknown_task"
        checks += 1
        bad = copy.deepcopy(receipt)
        bad["payload"]["timestamp"] = (datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
        bad["signature"] = sign_for_disposable_test(bad["payload"], key)
        assert verify_receipt(dbpath, bad, key)["reason"] == "receipt_outside_window"
        checks += 1
        bad = copy.deepcopy(receipt)
        bad["payload"]["result_sha256"] = "f" * 64
        bad["signature"] = sign_for_disposable_test(bad["payload"], key)
        assert verify_receipt(dbpath, bad, key)["reason"] == "result_hash_mismatch"
        checks += 1
        with L.connect() as db:
            db.execute("UPDATE tasks SET status='failed' WHERE id=?", (row["id"],))
        assert verify_receipt(dbpath, receipt, key)["reason"] == "canonical_task_mismatch"
        checks += 1
        assert L.verify_event_chain()["ok"], "task mutation does not invalidate event chain; note this limitation"
        checks += 1
    print(json.dumps({"suite": "hermes_receipt_contract", "checks": checks,
                      "status": "PASS", "live_hermes_execution": "NOT_TESTED",
                      "production_state": "UNTOUCHED"}, sort_keys=True))

if __name__ == "__main__":
    main()
