"""Same idempotency key does not duplicate; an altered title conflicts."""
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


class IdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "disposable.db"
        self.env = os.environ.copy()
        self.env["LEQUTIS_DB"] = str(self.db)
        self.env["LEQUTIS_ARTIFACT_ROOT"] = str(Path(self.temp.name) / "artifacts")

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, str(CLI), *args], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_same_key_does_not_duplicate(self):
        self.run_cli("goal", "--key", "same-1", "remember: one local fact")
        first = json.loads(self.run_cli("run-once").stdout)
        self.assertEqual(first["status"], "succeeded")
        self.run_cli("goal", "--key", "same-1", "remember: one local fact")
        second = json.loads(self.run_cli("run-once").stdout)
        self.assertEqual(second["status"], "idle")
        with sqlite3.connect(self.db) as db:
            agendas = db.execute("SELECT COUNT(*) FROM agenda").fetchone()[0]
            semantic = db.execute("SELECT COUNT(*) FROM memory WHERE kind='semantic'").fetchone()[0]
            executions = db.execute("SELECT COUNT(*) FROM executions WHERE status='succeeded'").fetchone()[0]
        self.assertEqual(agendas, 1)
        self.assertEqual(semantic, 1)
        self.assertEqual(executions, 1)

    def test_altered_payload_with_same_key_is_rejected(self):
        self.run_cli("goal", "--key", "same-2", "remember: original")
        self.run_cli("run-once")
        with sqlite3.connect(self.db) as db:
            before = db.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
            agendas = db.execute("SELECT COUNT(*) FROM agenda").fetchone()[0]
        conflict = self.run_cli("goal", "--key", "same-2", "remember: altered", expected=1)
        body = json.loads(conflict.stdout)
        self.assertEqual(body["status"], "conflict")
        self.assertEqual(body["error"], "idempotency_key_reused_with_different_request")
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM memory").fetchone()[0], before)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM agenda").fetchone()[0], agendas)


if __name__ == "__main__":
    unittest.main()
