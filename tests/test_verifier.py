"""The verifier is a separate process and a rejection does not complete the agenda."""
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


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "disposable.db"
        self.env = os.environ.copy()
        self.env["LEQUTIS_DB"] = str(self.db)
        self.env["LEQUTIS_ARTIFACT_ROOT"] = str(Path(self.temp.name) / "artifacts")

    def tearDown(self):
        self.temp.cleanup()

    def test_verifier_process_is_independent_and_ignores_self_report(self):
        env = self.env
        subprocess.run([sys.executable, str(CLI), "goal", "remember: checked by another process"], env=env, check=True, text=True, capture_output=True)
        result = subprocess.run([sys.executable, str(CLI), "run-once"], env=env, text=True, capture_output=True, check=True)
        body = json.loads(result.stdout)
        self.assertEqual(body["status"], "succeeded")
        self.assertFalse(body["verifier"]["worker_self_report_consulted"])
        self.assertNotEqual(body["verifier"]["verifier_pid"], os.getpid())
        with sqlite3.connect(self.db) as db:
            claimed, agenda = db.execute(
                "SELECT e.claimed_verdict, a.status FROM executions e JOIN agenda a ON a.id=e.agenda_id"
            ).fetchone()
        self.assertEqual(claimed, "accepted")
        self.assertEqual(agenda, "complete")

    def test_rejected_verdict_blocks_agenda_completion(self):
        env = self.env.copy()
        env["LEQUTIS_CORRUPT_ARTIFACT"] = "1"
        subprocess.run([sys.executable, str(CLI), "goal", "remember: this artifact will not match"], env=env, check=True, text=True, capture_output=True)
        result = subprocess.run([sys.executable, str(CLI), "run-once"], env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        body = json.loads(result.stdout)
        self.assertEqual(body["status"], "failed")
        self.assertIn("content_hash_mismatch", body["error"])
        with sqlite3.connect(self.db) as db:
            claimed, execution, agenda = db.execute(
                "SELECT e.claimed_verdict, e.status, a.status FROM executions e JOIN agenda a ON a.id=e.agenda_id"
            ).fetchone()
        self.assertEqual(claimed, "accepted")
        self.assertEqual(execution, "failed")
        self.assertNotEqual(agenda, "complete")


if __name__ == "__main__":
    unittest.main()
