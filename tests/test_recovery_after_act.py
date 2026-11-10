"""Real SIGKILL after ACT/LEARN must not duplicate durable memory on retry."""
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

CLI = Path(__file__).resolve().parents[1] / "core" / "lequtis.py"


class RecoveryAfterActTests(unittest.TestCase):
    def test_killed_after_learning_reuses_both_memories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "state" / "disposable.db"
            env = os.environ.copy()
            env.update(LEQUTIS_DB=str(db), LEQUTIS_STATE=str(db.parent),
                       LEQUTIS_ARTIFACT_ROOT=str(root / "artifacts"))

            def run(*args, expected=0):
                p = subprocess.run([sys.executable, str(CLI), *args], env=env,
                                   capture_output=True, text=True, timeout=30)
                self.assertEqual(p.returncode, expected, p.stdout + p.stderr)
                return json.loads(p.stdout) if p.stdout.lstrip().startswith("{") else p.stdout

            def rows(sql):
                with sqlite3.connect(db) as handle:
                    return handle.execute(sql).fetchall()

            run("goal", "--key", "kill-after-act", "remember: retain exactly one fact")
            pause = root / "before-commit"
            paused_env = dict(env, LEQUTIS_PAUSE_BEFORE_COMMIT=str(pause))
            proc = subprocess.Popen([sys.executable, str(CLI), "run-once"],
                                    env=paused_env, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 15
                while not (pause / "claimed").exists() and time.monotonic() < deadline:
                    self.assertIsNone(proc.poll(), "worker exited before pause")
                    time.sleep(0.02)
                self.assertTrue((pause / "claimed").exists())
                info = json.loads((pause / "claimed").read_text())
                before = rows("SELECT kind,id,content FROM memory ORDER BY kind")
                self.assertEqual([r[0] for r in before], ["experience", "semantic"])
                self.assertEqual(run("recover")["recovered"], 0)
                os.kill(proc.pid, signal.SIGKILL)
                proc.communicate(timeout=5)
                self.assertEqual(proc.returncode, -signal.SIGKILL)
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.communicate(timeout=5)

            self.assertEqual(run("recover")["recovered"], 1)
            stale = run("complete", info["execution_id"], info["lease_token"], expected=1)
            self.assertEqual(stale["reason"], "stale_fence")
            run("retry", info["agenda_id"])
            self.assertEqual(run("run-once")["status"], "succeeded")
            self.assertEqual(rows("SELECT kind,id,content FROM memory ORDER BY kind"), before)
            self.assertEqual(rows("SELECT attempt,status FROM executions ORDER BY attempt"),
                             [(1, "interrupted"), (2, "succeeded")])
            self.assertEqual(rows("SELECT COUNT(*) FROM executions WHERE result IS NOT NULL"), [(1,)])
            self.assertEqual(run("run-once")["status"], "idle")
            self.assertTrue(run("verify")["ok"])


if __name__ == "__main__":
    unittest.main()
