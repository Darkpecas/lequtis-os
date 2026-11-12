"""Append-only event ledger and fail-closed `verify` exit code.

LOCAL PROOF, NOT LIVE VPS VERIFIED: every database here is disposable.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "core" / "lequtis.py"
SCHEMA = ROOT / "database" / "schema.sql"
TRIGGERS = {"events_append_only_no_update", "events_append_only_no_delete"}


class AppendOnlyLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lequtis-append-only-")
        self.db_path = Path(self.tmp.name) / "disposable.db"
        self.env = {**os.environ, "LEQUTIS_DB": str(self.db_path),
                    "LEQUTIS_STATE": self.tmp.name}
        self.cli("init")
        self.cli("goal", "remember: append-only ledger fact")
        self.cli("run-once")

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args, expected=0):
        proc = subprocess.run([sys.executable, str(CLI), *args], env=self.env,
                              text=True, capture_output=True)
        self.assertEqual(proc.returncode, expected,
                         f"{args!r}:\n{proc.stdout}\n{proc.stderr}")
        return proc

    def connect(self):
        return sqlite3.connect(self.db_path)

    def event_count(self):
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def test_init_installs_both_triggers(self):
        with self.connect() as db:
            names = {r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='events'")}
        self.assertEqual(TRIGGERS, names)

    def test_update_is_rejected_and_chain_stays_valid(self):
        with self.connect() as db:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "events_append_only"):
                db.execute("UPDATE events SET payload='{}' WHERE seq=1")
        verify = json.loads(self.cli("verify").stdout)
        self.assertTrue(verify["ok"], verify)

    def test_delete_is_rejected_and_count_unchanged(self):
        before = self.event_count()
        self.assertGreater(before, 0)
        with self.connect() as db:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "events_append_only"):
                db.execute("DELETE FROM events WHERE seq=1")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "events_append_only"):
                db.execute("DELETE FROM events")
        self.assertEqual(before, self.event_count())
        self.cli("verify")

    def test_insert_still_allowed(self):
        before = self.event_count()
        self.cli("goal", "remember: second fact")
        self.assertGreater(self.event_count(), before)
        self.cli("verify")

    def test_verify_exits_nonzero_when_payload_tampered(self):
        clean = json.loads(self.cli("verify").stdout)
        self.assertTrue(clean["ok"])
        with self.connect() as db:
            db.execute("DROP TRIGGER events_append_only_no_update")
            db.execute("UPDATE events SET payload='tampered' WHERE seq=1")
        result = json.loads(self.cli("verify", expected=1).stdout)
        self.assertFalse(result["ok"])
        self.assertEqual("event_hash_mismatch", result["reason"])
        self.assertEqual(1, result["broken_at"])

    def test_verify_exits_nonzero_when_event_deleted(self):
        with self.connect() as db:
            db.execute("DROP TRIGGER events_append_only_no_delete")
            db.execute("DELETE FROM events WHERE seq=2")
        result = json.loads(self.cli("verify", expected=1).stdout)
        self.assertFalse(result["ok"])

    def test_reinit_restores_dropped_triggers(self):
        with self.connect() as db:
            db.execute("DROP TRIGGER events_append_only_no_update")
            db.execute("DROP TRIGGER events_append_only_no_delete")
        self.cli("init")
        with self.connect() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE events SET payload='{}' WHERE seq=1")
        self.cli("verify")

    def test_reference_schema_sql_blocks_update_and_delete(self):
        db = sqlite3.connect(":memory:")
        try:
            db.executescript(SCHEMA.read_text(encoding="utf-8"))
            db.execute("INSERT INTO events(event_id,ts,event_type,payload,previous_hash,event_hash)"
                       " VALUES ('e1','t','x','{}','GENESIS','h')")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "events_append_only"):
                db.execute("UPDATE events SET payload='y'")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "events_append_only"):
                db.execute("DELETE FROM events")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
