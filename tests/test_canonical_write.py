#!/usr/bin/env python3
"""Disposable canonical write gate tests; no production state is touched."""
import importlib
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "runtime" / "hermes-stdio-connector"))


def run():
    with tempfile.TemporaryDirectory(prefix="lequtis-write-") as tmp:
        os.environ["LEQUTIS_ROOT"] = str(ROOT)
        os.environ["LEQUTIS_STATE"] = tmp
        os.environ.pop("LEQUTIS_CANONICAL_WRITE", None)
        import lequtis
        import canonical_write
        import lequtis_mcp_stdio as adapter
        lequtis.init()

        intent = {"mode": "intent", "idempotency_key": "gate-test-1",
                  "title": "Verify kernel", "action": "inspect_status", "payload": {}}
        assert canonical_write.canonical_commit(intent)["reason"] == "canonical_write_disabled"
        assert "lequtis_canonical_commit" not in adapter.handshake_once()["tools"]
        os.environ["LEQUTIS_CANONICAL_WRITE"] = "1"
        assert canonical_write.canonical_commit({**intent, "action": "shell"})["ok"] is False
        initial = canonical_write.canonical_commit(intent)
        assert initial["ok"] and not initial["duplicate"], initial
        again = canonical_write.canonical_commit(intent)
        assert again["ok"] and again["duplicate"], again
        conflict = canonical_write.canonical_commit({**intent, "title": "Changed"})
        assert conflict["reason"] == "idempotency_key_conflict", conflict
        receipt = {"mode": "receipt", "idempotency_key": "gate-test-1",
                   "receipt": {"exit_code": 0, "source": "disposable-test"},
                   "memory": "Observation awaiting independent verification"}
        rec = canonical_write.canonical_commit(receipt)
        assert rec["ok"] and not rec["duplicate"], rec
        assert canonical_write.canonical_commit(receipt)["duplicate"]
        assert canonical_write.canonical_commit({**receipt, "receipt": {"exit_code": 1}})["ok"] is False
        with lequtis.connect() as db:
            task = db.execute("SELECT status FROM tasks WHERE idempotency_key='gate-test-1'").fetchone()
            assert task["status"] == "pending"
            assert db.execute("SELECT COUNT(*) FROM memory").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
        assert lequtis.verify_event_chain()["ok"]

        # A damaged chain blocks subsequent canonical writes.
        with lequtis.connect() as db:
            db.execute("UPDATE events SET payload='tampered' WHERE seq=1")
        bad = canonical_write.canonical_commit({**intent, "idempotency_key": "gate-test-2"})
        assert bad["ok"] is False and "event_chain_invalid" in bad["reason"], bad
    print("CANONICAL WRITE DISPOSABLE TESTS: PASS")


if __name__ == "__main__":
    run()
