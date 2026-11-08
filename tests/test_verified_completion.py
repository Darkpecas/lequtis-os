#!/usr/bin/env python3
"""Disposable, actual kernel + canonical-write + attested-finalizer regression."""
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "runtime" / "hermes-stdio-connector"))
KEY = b"DISPOSABLE-VERIFIER-KEY-NOT-FOR-PRODUCTION-123456789"


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(obj):
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


class TestVerifiedCompletion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="lequtis-verified-")
        cls.prior = {k: os.environ.get(k) for k in
                     ("LEQUTIS_ROOT", "LEQUTIS_STATE", "LEQUTIS_CANONICAL_WRITE",
                      "LEQUTIS_TRUSTED_LOCAL_TRANSPORT", "LEQUTIS_VERIFIER_COMPLETION")}
        os.environ.update({
            "LEQUTIS_ROOT": str(ROOT), "LEQUTIS_STATE": cls.tmp.name,
            "LEQUTIS_CANONICAL_WRITE": "1", "LEQUTIS_TRUSTED_LOCAL_TRANSPORT": "1",
            "LEQUTIS_VERIFIER_COMPLETION": "1",
        })
        import lequtis
        import canonical_write
        import verified_completion
        cls.L, cls.W, cls.V = lequtis, canonical_write, verified_completion
        cls.L.init()

    @classmethod
    def tearDownClass(cls):
        for name, value in cls.prior.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        cls.tmp.cleanup()

    def records(self, key, *, agenda_id=None):
        intent = {"mode": "intent", "idempotency_key": key,
                  "title": "Harmless inspection", "action": "inspect_status",
                  "payload": {}, "agenda_id": agenda_id}
        recorded = self.W.canonical_commit(intent)
        self.assertTrue(recorded["ok"], recorded)
        receipt = {"returncode": 0, "observation": "fixture-only", "source": "test"}
        recorded_receipt = self.W.canonical_commit({
            "mode": "receipt", "idempotency_key": key, "receipt": receipt})
        self.assertTrue(recorded_receipt["ok"], recorded_receipt)
        p = {"task_id": recorded["task_id"], "idempotency_key": key,
             "correlation_id": "fixture-" + key, "executor_id": "fixture-executor",
             "verifier_id": "separate-fixture-verifier", "receipt_sha256": digest(receipt),
             "external_evidence_sha256": hashlib.sha256(b"separate-fixture").hexdigest(),
             "verdict": "success", "observed_utc": datetime.now(timezone.utc).isoformat()}
        return p

    def envelope(self, p, *, key=KEY):
        return {"payload": p,
                "signature": hmac.new(key, canonical(p).encode(), hashlib.sha256).hexdigest()}

    def test_01_disabled_gate_fail_closed(self):
        p = self.records("verifier-disabled")
        os.environ["LEQUTIS_VERIFIER_COMPLETION"] = "0"
        try:
            self.assertEqual(self.V.complete_with_verifier_attestation(self.envelope(p), key=KEY)["reason"],
                             "verifier_completion_disabled")
        finally:
            os.environ["LEQUTIS_VERIFIER_COMPLETION"] = "1"
        with self.L.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM tasks WHERE id=?", (p["task_id"],)).fetchone()[0],
                             "pending")

    def test_02_invalid_key_and_signature(self):
        p = self.records("verifier-invalid")
        self.assertEqual(self.V.complete_with_verifier_attestation(self.envelope(p), key=b"bad")["reason"],
                         "verifier_key_unavailable")
        wrong = self.envelope(p)
        wrong["signature"] = "0" * 64
        self.assertEqual(self.V.complete_with_verifier_attestation(wrong, key=KEY)["reason"],
                         "invalid_verifier_signature")

    def test_03_unlinked_receipt_denied(self):
        p = self.records("verifier-receipt")
        p["receipt_sha256"] = "e" * 64
        self.assertEqual(self.V.complete_with_verifier_attestation(self.envelope(p), key=KEY)["reason"],
                         "receipt_digest_mismatch")

    def test_04_distinct_verifier_required(self):
        p = self.records("verifier-identity")
        p["verifier_id"] = p["executor_id"]
        self.assertEqual(self.V.complete_with_verifier_attestation(self.envelope(p), key=KEY)["reason"],
                         "verifier_not_independent")

    def test_05_transactional_success_and_replay(self):
        p = self.records("verifier-success")
        envelope = self.envelope(p)
        first = self.V.complete_with_verifier_attestation(envelope, key=KEY)
        self.assertTrue(first["ok"], first)
        self.assertFalse(first["live_verified"])
        second = self.V.complete_with_verifier_attestation(envelope, key=KEY)
        self.assertTrue(second["ok"] and second["duplicate"], second)
        with self.L.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM tasks WHERE id=?", (p["task_id"],)).fetchone()[0],
                             "completed")
            self.assertEqual(db.execute("SELECT kind FROM memory WHERE id=?",
                                        (first["memory_id"],)).fetchone()[0],
                             "learning.attested_not_live")
        self.assertTrue(self.L.verify_event_chain()["ok"])

    def test_06_conflicting_replay_denied(self):
        p = self.records("verifier-conflict")
        self.assertTrue(self.V.complete_with_verifier_attestation(self.envelope(p), key=KEY)["ok"])
        p["external_evidence_sha256"] = "a" * 64
        self.assertEqual(self.V.complete_with_verifier_attestation(self.envelope(p), key=KEY)["reason"],
                         "verification_conflict")

    def test_07_agenda_updates_atomically(self):
        with self.L.connect() as db:
            db.execute("INSERT INTO agenda(id,title,status,priority,created,updated) VALUES(?,?,?,?,?,?)",
                       ("fixture-agenda-7", "fixture", "open", 1, self.L.now(), self.L.now()))
        p = self.records("verifier-agenda", agenda_id="fixture-agenda-7")
        r = self.V.complete_with_verifier_attestation(self.envelope(p), key=KEY)
        self.assertTrue(r["ok"], r)
        with self.L.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM agenda WHERE id='fixture-agenda-7'").fetchone()[0],
                             "done")
        self.assertTrue(self.L.verify_event_chain()["ok"])

    def test_08_failure_keeps_agenda_open(self):
        with self.L.connect() as db:
            db.execute("INSERT INTO agenda(id,title,status,priority,created,updated) VALUES(?,?,?,?,?,?)",
                       ("fixture-agenda-failure", "fixture", "open", 1, self.L.now(), self.L.now()))
        p = self.records("verifier-failure", agenda_id="fixture-agenda-failure")
        p["verdict"] = "failure"
        r = self.V.complete_with_verifier_attestation(self.envelope(p), key=KEY)
        self.assertTrue(r["ok"], r)
        with self.L.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM tasks WHERE id=?", (p["task_id"],)).fetchone()[0], "failed")
            self.assertEqual(db.execute("SELECT status FROM agenda WHERE id='fixture-agenda-failure'").fetchone()[0], "open")

    def test_09_agenda_conflict_rolls_back_everything(self):
        with self.L.connect() as db:
            db.execute("INSERT INTO agenda(id,title,status,priority,created,updated) VALUES(?,?,?,?,?,?)",
                       ("fixture-agenda-closed", "fixture", "done", 1, self.L.now(), self.L.now()))
        p = self.records("verifier-rollback", agenda_id="fixture-agenda-closed")
        with self.L.connect() as db:
            before = tuple(db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0] for t in ("events", "memory"))
        r = self.V.complete_with_verifier_attestation(self.envelope(p), key=KEY)
        self.assertEqual(r["reason"], "agenda_not_open", r)
        with self.L.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM tasks WHERE id=?", (p["task_id"],)).fetchone()[0], "pending")
            self.assertEqual(tuple(db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
                                   for t in ("events", "memory")), before)

    def test_10_fresh_process_reads_same_canonical_state(self):
        p = self.records("verifier-fresh")
        r = self.V.complete_with_verifier_attestation(self.envelope(p), key=KEY)
        self.assertTrue(r["ok"], r)
        script = """
import json, lequtis as L
with L.connect() as db:
    task = db.execute("SELECT status FROM tasks WHERE id=?", ("TASK_ID",)).fetchone()
    memory = db.execute("SELECT kind FROM memory WHERE id=?", ("MEMORY_ID",)).fetchone()
print(json.dumps({"status": task[0], "memory": memory[0], "chain": L.verify_event_chain()["ok"]}))
""".replace("TASK_ID", p["task_id"]).replace("MEMORY_ID", r["memory_id"])
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT / "core",
                                env=os.environ.copy(), capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        self.assertEqual(data, {"status": "completed", "memory": "learning.attested_not_live", "chain": True})

    def test_99_tamper_rejected_without_mutation(self):
        p = self.records("verifier-tamper")
        with self.L.connect() as db:
            db.execute("UPDATE events SET payload='tampered' WHERE seq=1")
            before = db.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
        r = self.V.complete_with_verifier_attestation(self.envelope(p), key=KEY)
        self.assertFalse(r["ok"], r)
        self.assertIn("event_chain_invalid", r["reason"])
        with self.L.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM memory").fetchone()[0], before)


if __name__ == "__main__":
    unittest.main()
