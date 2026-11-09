#!/usr/bin/env python3
"""Disposable canonical intake acceptance: actual WAL, rollback and subprocess read-back."""
import copy
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "core"), str(ROOT / "runtime/hermes-stdio-connector")]


class CanonicalWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lequtis-intake-test-")
        self.state = Path(self.tmp.name)
        os.environ["LEQUTIS_STATE"] = str(self.state)
        os.environ["LEQUTIS_ROOT"] = str(ROOT)
        os.environ.pop("LEQUTIS_DB", None)
        os.environ.pop("LEQUTIS_CANONICAL_WRITE", None)
        os.environ.pop("LEQUTIS_WRITE_PRINCIPAL", None)
        import lequtis
        self.L = importlib.reload(lequtis)
        self.L.init()
        import canonical_write
        self.C = importlib.reload(canonical_write)
        import lequtis_mcp_stdio
        self.A = importlib.reload(lequtis_mcp_stdio)
        self.req = {
            "idempotency_key": "ios-001", "title": "Inspect status",
            "action": "inspect_status", "payload": {},
            "receipt": {"source": "ios", "claimed_status": "done"},
            "memory": {"kind": "episodic", "content": "Submitted observation"},
        }

    def tearDown(self):
        self.tmp.cleanup()

    def counts(self):
        with self.L.connect() as db:
            return [db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
                    for t in ("agenda", "tasks", "memory", "events")]

    def test_opt_in_and_principal_required(self):
        before = self.counts()
        for key in (None, "", "bad principal"):
            os.environ["LEQUTIS_CANONICAL_WRITE"] = "1"
            if key is not None:
                os.environ["LEQUTIS_WRITE_PRINCIPAL"] = key
            self.assertFalse(self.A.tool_canonical_intake(self.req)["ok"])
        self.assertEqual(before, self.counts())
        self.assertNotIn("lequtis_canonical_write", [t["name"] for t in self.A.TOOLS])

    def test_atomic_intake_and_fresh_process_readback(self):
        result = self.C.write_intake("alan", self.req)
        self.assertTrue(result["ok"])
        self.assertFalse(result["live_host"])
        self.assertEqual("awaiting_approval", result["task"]["status"])
        self.assertEqual("awaiting_approval", result["agenda"]["status"])
        self.assertEqual("submitted_episodic", result["memory"]["kind"])
        self.assertEqual("unverified_claim", result["receipt_trust"])
        code = "import canonical_write as C,json; print(json.dumps(C.read_intake('alan','ios-001')))"
        env = {**os.environ, "PYTHONPATH": str(ROOT / "core")}
        proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
        read = json.loads(proc.stdout)
        self.assertEqual(result["request_hash"], read["request_hash"])
        self.assertEqual(result["event"], read["event"])
        self.assertTrue(self.L.verify_event_chain()["ok"])

    def test_replay_and_payload_conflict(self):
        self.C.write_intake("alan", self.req)
        before = self.counts()
        self.assertEqual("duplicate", self.C.write_intake("alan", self.req)["status"])
        changed = copy.deepcopy(self.req)
        changed["payload"]["different"] = True
        with self.assertRaisesRegex(ValueError, "idempotency_key_reused"):
            self.C.write_intake("alan", changed)
        self.assertEqual(before, self.counts())

    def test_rollback_if_event_insert_fails(self):
        with self.L.connect() as db:
            db.execute("CREATE TRIGGER test_reject BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'injected'); END")
        before = self.counts()
        with self.assertRaises(Exception):
            self.C.write_intake("alan", self.req)
        self.assertEqual(before, self.counts())

    def test_concurrent_duplicate_is_one_intake(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.C.write_intake("alan", self.req), range(12)))
        self.assertEqual(1, sum(r["status"] == "created" for r in results))
        self.assertEqual([1, 1, 1], self.counts()[:3])
        self.assertTrue(self.L.verify_event_chain()["ok"])

    def test_validation_and_principal_isolation(self):
        before = self.counts()
        for change in ({"action": "shell"}, {"principal": "admin"}, {"title": " "}, {"receipt": float("nan")}):
            with self.assertRaises((ValueError, TypeError)):
                self.C.write_intake("alan", {**self.req, **change})
        self.assertEqual(before, self.counts())
        self.C.write_intake("alan", self.req)
        self.assertFalse(self.C.read_intake("other", "ios-001")["ok"])

    def test_no_database_creation_and_schema_refusal(self):
        original = self.L.DB
        self.L.DB = self.state / "absent.db"
        with self.assertRaises(Exception):
            self.C.write_intake("alan", self.req)
        self.assertFalse(self.L.DB.exists())
        self.L.DB = original
        with self.L.connect() as db:
            db.execute("UPDATE identity SET value='older' WHERE key='schema_revision'")
        before = self.counts()
        with self.assertRaisesRegex(ValueError, "schema_incompatible"):
            self.C.write_intake("alan", self.req)
        self.assertEqual(before, self.counts())

    def test_tampered_event_and_memory_refused(self):
        result = self.C.write_intake("alan", self.req)
        with self.L.connect() as db:
            db.execute("UPDATE memory SET content='changed' WHERE id=?", (result["memory"]["id"],))
        with self.assertRaisesRegex(ValueError, "binding_mismatch"):
            self.C.read_intake("alan", "ios-001")
        with self.L.connect() as db:
            db.execute("UPDATE events SET payload='{}' WHERE event_id=?", (result["event"]["event_id"],))
        with self.assertRaisesRegex(ValueError, "event_chain_invalid"):
            self.C.write_intake("alan", {**self.req, "idempotency_key": "next"})

    def test_enabled_mcp_wire_path(self):
        env = {**os.environ, "LEQUTIS_CANONICAL_WRITE": "1", "LEQUTIS_WRITE_PRINCIPAL": "alan"}
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "lequtis_canonical_write", "arguments": self.req}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "lequtis_canonical_read", "arguments": {"idempotency_key": "ios-001"}}}]
        proc = subprocess.run([sys.executable, str(ROOT / "runtime/hermes-stdio-connector/lequtis_mcp_stdio.py")],
                              input="".join(json.dumps(m) + "\n" for m in messages),
                              text=True, capture_output=True, env=env, check=True)
        replies = [json.loads(s)["result"] for s in proc.stdout.splitlines()]
        self.assertFalse(replies[0]["isError"])
        self.assertFalse(replies[1]["isError"])
        self.assertEqual(replies[0]["structuredContent"]["event"], replies[1]["structuredContent"]["event"])

    def test_intake_is_held_across_both_loop_engines_and_replay(self):
        # A harmless inspection must not imply an arbitrary requested goal done.
        request = {**self.req, "title": "Build an impressive agent OS",
                   "memory": {"kind": "working", "content": "Submitted build request"}}
        original = self.C.write_intake("alan", request)
        for _ in range(2):
            loop = self.L.run_loop()
            self.assertEqual("idle", loop["evidence"]["phases"]["CHOOSE"]["kind"])
            self.assertEqual("idle", self.L.run_once()["status"])
        read = self.C.read_intake("alan", request["idempotency_key"])
        self.assertEqual("awaiting_approval", read["task"]["status"])
        self.assertEqual("awaiting_approval", read["agenda"]["status"])
        self.assertEqual(original["event"], read["event"])
        self.assertEqual("duplicate", self.C.write_intake("alan", request)["status"])
        with self.L.connect() as db:
            self.assertEqual(1, db.execute("SELECT COUNT(*) FROM tasks WHERE agenda_id=?",
                             (read["agenda"]["id"],)).fetchone()[0])
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM executions WHERE agenda_id=?",
                             (read["agenda"]["id"],)).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
