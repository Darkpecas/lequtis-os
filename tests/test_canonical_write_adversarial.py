#!/usr/bin/env python3
"""Adversarial disposable tests for canonical writer; never touch production state."""
from __future__ import annotations
import os
import sys
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "runtime" / "hermes-stdio-connector"))

class CanonicalWriteAdversarial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="lequtis-adversarial-")
        cls.prior = {k: os.environ.get(k) for k in ("LEQUTIS_ROOT", "LEQUTIS_STATE", "LEQUTIS_CANONICAL_WRITE", "LEQUTIS_TRUSTED_LOCAL_TRANSPORT")}
        os.environ["LEQUTIS_ROOT"] = str(ROOT)
        os.environ["LEQUTIS_STATE"] = cls.scratch.name
        os.environ["LEQUTIS_CANONICAL_WRITE"] = "1"
        os.environ["LEQUTIS_TRUSTED_LOCAL_TRANSPORT"] = "1"
        import lequtis, canonical_write
        cls.L = lequtis
        cls.W = canonical_write
        lequtis.init()

    @classmethod
    def tearDownClass(cls):
        for key, val in cls.prior.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
        cls.scratch.cleanup()

    def intent(self, key):
        return {"mode": "intent", "idempotency_key": key,
                "title": "Harmless status inspection", "action": "inspect_status", "payload": {}}

    def test_01_missing_intent_rejects_receipt(self):
        before = self.counts()
        res = self.W.canonical_commit({"mode": "receipt", "idempotency_key": "no-such-intent",
                                       "receipt": {"observation": "claim"}})
        self.assertFalse(res["ok"], res)
        self.assertEqual(self.counts(), before)

    def test_02_disabled_write_changes_nothing(self):
        before = self.counts()
        os.environ["LEQUTIS_CANONICAL_WRITE"] = "0"
        try:
            result = self.W.canonical_commit(self.intent("disabled-adversarial"))
            self.assertFalse(result["ok"], result)
            self.assertEqual(self.counts(), before)
        finally:
            os.environ["LEQUTIS_CANONICAL_WRITE"] = "1"

    def test_025_missing_explicit_state_refuses_write(self):
        before = self.counts()
        previous = os.environ.pop("LEQUTIS_STATE", None)
        try:
            result = self.W.canonical_commit(self.intent("implicit-state-adversarial"))
            self.assertFalse(result["ok"], result)
            self.assertEqual(result["reason"], "explicit_state_required")
        finally:
            if previous is not None:
                os.environ["LEQUTIS_STATE"] = previous
        self.assertEqual(self.counts(), before)

    def test_025_untrusted_transport_changes_nothing(self):
        before = self.counts()
        os.environ["LEQUTIS_TRUSTED_LOCAL_TRANSPORT"] = "0"
        try:
            result = self.W.canonical_commit(self.intent("untrusted-transport"))
            self.assertEqual(result["reason"], "trusted_transport_not_attested")
            self.assertEqual(self.counts(), before)
        finally:
            os.environ["LEQUTIS_TRUSTED_LOCAL_TRANSPORT"] = "1"

    def test_026_symlinked_canonical_database_rejected(self):
        # A path supplied through LEQUTIS_STATE must not redirect writes
        # into a different database, even when the linked file exists.
        target = self.L.DB
        old_db = self.L.DB
        before = self.counts()
        with tempfile.TemporaryDirectory(prefix="lequtis-symlink-") as scratch:
            redirected = Path(scratch) / "lequtis.db"
            redirected.symlink_to(target)
            self.L.DB = redirected
            try:
                result = self.W.canonical_commit(self.intent("symlink-adversarial"))
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["reason"], "canonical_database_symlink_rejected")
            finally:
                self.L.DB = old_db
        self.assertEqual(self.counts(), before)

    def test_03_concurrent_replay_one_event(self):
        packet = self.intent("concurrency-adversarial")
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(self.W.canonical_commit, [packet] * 6))
        self.assertTrue(all(r["ok"] for r in results), results)
        self.assertEqual(sum(not r["duplicate"] for r in results), 1)
        with self.L.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM tasks WHERE idempotency_key=?", 
                                        (packet["idempotency_key"],)).fetchone()[0], 1)
        self.assertTrue(self.L.verify_event_chain()["ok"])

    def test_04_receipt_cannot_complete_task(self):
        packet = self.intent("unverified-receipt-adversarial")
        self.assertTrue(self.W.canonical_commit(packet)["ok"])
        result = self.W.canonical_commit({"mode": "receipt", "idempotency_key": packet["idempotency_key"],
                "receipt": {"success": True, "source": "untrusted caller"}, "memory": "unverified"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["verification"], "unverified")
        with self.L.connect() as db:
            row = db.execute("SELECT status FROM tasks WHERE idempotency_key=?", 
                             (packet["idempotency_key"],)).fetchone()
            self.assertEqual(row["status"], "pending")
            mem = db.execute("SELECT kind FROM memory WHERE content='unverified'").fetchone()
            self.assertEqual(mem["kind"], "observation_unverified")
        self.assertTrue(self.L.verify_event_chain()["ok"])

    def counts(self):
        with self.L.connect() as db:
            return tuple(db.execute("SELECT count(*) FROM " + table).fetchone()[0] 
                         for table in ("tasks", "events", "memory"))

if __name__ == "__main__":
    unittest.main()
