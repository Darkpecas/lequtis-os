"""A live lease is not stolen. A killed process cannot complete with its old token."""
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "core" / "lequtis.py"


class FenceTests(unittest.TestCase):
    def test_killed_process_is_fenced_and_live_lease_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "disposable.db"
            pause = root / "pause"
            env = os.environ.copy()
            env["LEQUTIS_DB"] = str(db)
            env["LEQUTIS_ARTIFACT_ROOT"] = str(root / "artifacts")
            env["LEQUTIS_PAUSE_AFTER_CLAIM"] = str(pause)
            subprocess.run(
                [sys.executable, str(CLI), "goal", "remember: hold the lease"],
                env=env, check=True, text=True, capture_output=True,
            )
            proc = subprocess.Popen(
                [sys.executable, str(CLI), "run-once"],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            deadline = time.time() + 15
            claimed = pause / "claimed"
            while time.time() < deadline and not claimed.exists():
                self.assertIsNone(proc.poll())
                time.sleep(0.02)
            self.assertTrue(claimed.exists())
            info = json.loads(claimed.read_text(encoding="utf-8"))
            held = subprocess.run([sys.executable, str(CLI), "recover"], env=env, text=True, capture_output=True, check=True)
            self.assertEqual(json.loads(held.stdout)["recovered"], 0)
            self.assertIn(info["execution_id"], json.loads(held.stdout)["live_skipped"])
            os.kill(proc.pid, signal.SIGKILL)
            proc.communicate(timeout=5)
            self.assertLess(proc.returncode, 0)
            recovered = subprocess.run([sys.executable, str(CLI), "recover"], env=env, text=True, capture_output=True, check=True)
            self.assertEqual(json.loads(recovered.stdout)["recovered"], 1)
            stale = subprocess.run(
                [sys.executable, str(CLI), "complete", info["execution_id"], info["lease_token"]],
                env=env, text=True, capture_output=True,
            )
            self.assertEqual(stale.returncode, 1)
            self.assertEqual(json.loads(stale.stdout)["reason"], "stale_fence")
            with sqlite3.connect(db) as handle:
                agenda, execution = handle.execute(
                    "SELECT a.status, e.status FROM agenda a JOIN executions e ON e.agenda_id=a.id"
                ).fetchone()
            self.assertEqual(agenda, "blocked")
            self.assertEqual(execution, "interrupted")


if __name__ == "__main__":
    unittest.main()
