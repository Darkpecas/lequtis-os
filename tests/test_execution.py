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


class ExecutionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "disposable.db"
        self.env = os.environ.copy()
        self.env["LEQUTIS_DB"] = str(self.db_path)
        self.run_cli("init")

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_cli(self, *args, expected=0):
        result = subprocess.run(
            [sys.executable, str(CLI), *args],
            env=self.env,
            text=True,
            capture_output=True,
        )
        self.assertEqual(
            result.returncode, expected,
            msg=f"command {args!r} failed:\n{result.stdout}\n{result.stderr}",
        )
        return result

    def query(self, sql, parameters=()):
        with sqlite3.connect(self.db_path) as db:
            return db.execute(sql, parameters).fetchall()

    def test_successful_execution_is_persisted_and_audited(self):
        self.run_cli("goal", "remember: The kernel can execute deterministic actions.")

        result = json.loads(self.run_cli("run-once").stdout)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.query("SELECT status FROM agenda"), [("complete",)])
        self.assertEqual(
            self.query("SELECT status FROM executions"), [("succeeded",)]
        )
        self.assertEqual(
            self.query("SELECT kind,content FROM memory ORDER BY rowid"),
            [
                ("semantic", "The kernel can execute deterministic actions."),
                (
                    "experience",
                    "Successful execution of agenda item: remember: "
                    "The kernel can execute deterministic actions.",
                ),
            ],
        )
        self.assertEqual(json.loads(self.run_cli("verify-events").stdout)["valid"], True)

        self.assertEqual(
            json.loads(self.run_cli("run-once").stdout)["status"], "idle"
        )
        self.assertEqual(self.query("SELECT COUNT(*) FROM executions"), [(1,)])

    def test_action_failure_is_audited_and_can_be_retried(self):
        self.run_cli("goal", "remember: retry after transient failure")
        with sqlite3.connect(self.db_path) as db:
            db.execute("""
                CREATE TRIGGER fail_semantic_memory
                BEFORE INSERT ON memory WHEN NEW.kind='semantic'
                BEGIN SELECT RAISE(ABORT, 'injected action failure'); END
            """)

        result = json.loads(self.run_cli("run-once", expected=1).stdout)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.query("SELECT status FROM agenda"), [("blocked",)])
        self.assertEqual(
            self.query("SELECT status,error FROM executions"),
            [("failed", "injected action failure")],
        )
        self.assertEqual(
            self.query("SELECT COUNT(*) FROM events WHERE event_type='execution.failed'"),
            [(1,)],
        )

        with sqlite3.connect(self.db_path) as db:
            db.execute("DROP TRIGGER fail_semantic_memory")
        agenda_id = self.query("SELECT id FROM agenda")[0][0]
        self.run_cli("retry", agenda_id)
        self.assertEqual(
            json.loads(self.run_cli("run-once").stdout)["status"], "succeeded"
        )
        self.assertEqual(
            self.query("SELECT attempt,status FROM executions ORDER BY attempt"),
            [(1, "failed"), (2, "succeeded")],
        )

    def test_interrupted_work_requires_explicit_recovery_and_retry(self):
        self.run_cli("goal", "remember: survive a process restart")
        agenda_id = self.query("SELECT id FROM agenda")[0][0]
        with sqlite3.connect(self.db_path) as db:
            db.execute("UPDATE agenda SET status='running' WHERE id=?", (agenda_id,))
            db.execute("""
                INSERT INTO executions
                    (id,agenda_id,attempt,status,action,input,started_at)
                VALUES ('interrupted-execution',?,1,'running','remember',
                        'survive a process restart','simulated')
            """, (agenda_id,))

        self.assertEqual(
            json.loads(self.run_cli("status").stdout)["unfinished_executions"], 1
        )
        self.assertEqual(
            json.loads(self.run_cli("recover").stdout)["recovered"], 1
        )
        self.assertEqual(self.query("SELECT status FROM agenda"), [("blocked",)])
        self.assertEqual(
            json.loads(self.run_cli("run-once").stdout)["status"], "idle"
        )
        self.assertEqual(self.query("SELECT COUNT(*) FROM executions"), [(1,)])

        self.run_cli("retry", agenda_id)
        self.assertEqual(
            json.loads(self.run_cli("run-once").stdout)["status"], "succeeded"
        )
        self.assertEqual(
            self.query("SELECT attempt,status FROM executions ORDER BY attempt"),
            [(1, "interrupted"), (2, "succeeded")],
        )
        self.assertEqual(json.loads(self.run_cli("verify-events").stdout)["valid"], True)

    def test_event_chain_verifier_detects_tampering(self):
        self.run_cli("goal", "remember: create auditable events")
        self.run_cli("run-once")
        with sqlite3.connect(self.db_path) as db:
            db.execute("UPDATE events SET payload='{}' WHERE seq=1")

        result = json.loads(self.run_cli("verify-events", expected=1).stdout)
        self.assertFalse(result["valid"])
        self.assertEqual(result["invalid_sequence"], 1)


if __name__ == "__main__":
    unittest.main()
