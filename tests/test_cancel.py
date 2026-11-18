"""Cancellation is a hash-chained, idempotent fence on result commit."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "core" / "lequtis.py"


class CancelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "disposable.db"
        self.env = os.environ.copy()
        self.env["LEQUTIS_DB"] = str(self.db)
        self.env["LEQUTIS_ARTIFACT_ROOT"] = str(Path(self.temp.name) / "artifacts")

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, expected=0, env=None):
        result = subprocess.run(
            [sys.executable, str(CLI), *args],
            env=self.env if env is None else env,
            text=True,
            capture_output=True,
        )
        self.assertEqual(
            result.returncode,
            expected,
            msg=f"{args!r}\n{result.stdout}\n{result.stderr}",
        )
        return result

    def query(self, sql, parameters=()):
        with sqlite3.connect(self.db) as db:
            return db.execute(sql, parameters).fetchall()

    def event_types(self):
        return [row[0] for row in self.query("SELECT event_type FROM events ORDER BY seq")]

    def test_cancel_is_idempotent_and_conflicts_on_a_different_request(self):
        self.run_cli("goal", "--key", "g1", "remember: leave this open")
        agenda_id = self.query("SELECT id FROM agenda")[0][0]
        first = json.loads(self.run_cli(
            "cancel", "--key", "cancel-1", "--reason", "operator stop", "agenda", agenda_id
        ).stdout)
        self.assertEqual(first["status"], "cancelled")
        self.assertEqual(self.event_types().count("agenda.cancelled"), 1)
        duplicate = json.loads(self.run_cli(
            "cancel", "--key", "cancel-1", "--reason", "operator stop", "agenda", agenda_id
        ).stdout)
        self.assertEqual(duplicate["status"], "duplicate")
        self.assertEqual(duplicate["cancellation_id"], first["cancellation_id"])
        self.assertEqual(self.event_types().count("agenda.cancelled"), 1)
        conflict = json.loads(self.run_cli(
            "cancel", "--key", "cancel-1", "--reason", "different reason", "agenda", agenda_id,
            expected=1,
        ).stdout)
        self.assertEqual(conflict["status"], "conflict")
        self.assertEqual(conflict["error"], "idempotency_key_reused_with_different_request")
        self.assertEqual(self.query("SELECT COUNT(*) FROM cancellations")[0][0], 1)
        missing = json.loads(self.run_cli(
            "cancel", "--key", "cancel-missing", "agenda", "missing-agenda", expected=1
        ).stdout)
        self.assertEqual(missing["status"], "not_found")
        verified = json.loads(self.run_cli("verify").stdout)
        self.assertTrue(verified["ok"])
        self.assertEqual(self.query("SELECT status FROM agenda")[0][0], "cancelled")
        self.assertEqual(json.loads(self.run_cli("run-once").stdout)["status"], "idle")

    def test_run_once_stops_before_act_when_cancelled_during_claim(self):
        pause = Path(self.temp.name) / "pause"
        env = self.env.copy()
        env["LEQUTIS_PAUSE_AFTER_CLAIM"] = str(pause)
        self.run_cli("goal", "remember: do not store this fact")
        proc = subprocess.Popen(
            [sys.executable, str(CLI), "run-once"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        claimed = pause / "claimed"
        deadline = time.time() + 15
        while time.time() < deadline and not claimed.exists():
            self.assertIsNone(proc.poll())
            time.sleep(0.02)
        self.assertTrue(claimed.exists(), "worker did not reach the claim pause")
        info = json.loads(claimed.read_text(encoding="utf-8"))
        cancelled = json.loads(self.run_cli(
            "cancel", "--key", "cancel-coop", "execution", info["execution_id"]
        ).stdout)
        self.assertEqual(cancelled["status"], "cancelled")
        (pause / "release").write_text("go", encoding="utf-8")
        stdout, stderr = proc.communicate(timeout=15)
        self.assertEqual(proc.returncode, 1, stdout + stderr)
        body = json.loads(stdout)
        self.assertEqual(body["status"], "cancelled")
        self.assertEqual(body["reason"], "cancelled")
        self.assertEqual(self.query("SELECT COUNT(*) FROM memory")[0][0], 0)
        status, result = self.query("SELECT status, result FROM executions")[0]
        self.assertEqual(status, "cancelled")
        self.assertIsNone(result)
        self.assertNotEqual(self.query("SELECT status FROM agenda")[0][0], "complete")
        self.assertTrue(json.loads(self.run_cli("verify").stdout)["ok"])

    def test_finished_worker_cannot_commit_a_cancelled_execution(self):
        pause = Path(self.temp.name) / "before-commit"
        env = self.env.copy()
        env["LEQUTIS_PAUSE_BEFORE_COMMIT"] = str(pause)
        self.run_cli("goal", "remember: the worker already did the work")
        proc = subprocess.Popen(
            [sys.executable, str(CLI), "run-once"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        claimed = pause / "claimed"
        deadline = time.time() + 15
        while time.time() < deadline and not claimed.exists():
            self.assertIsNone(proc.poll())
            time.sleep(0.02)
        self.assertTrue(claimed.exists(), proc.communicate(timeout=1) if proc.poll() else "no pause")
        info = json.loads(claimed.read_text(encoding="utf-8"))
        self.assertGreater(self.query("SELECT COUNT(*) FROM memory")[0][0], 0)
        self.run_cli("cancel", "--key", "cancel-late", "execution", info["execution_id"])
        (pause / "release").write_text("go", encoding="utf-8")
        stdout, stderr = proc.communicate(timeout=15)
        self.assertEqual(proc.returncode, 1, stdout + stderr)
        body = json.loads(stdout)
        self.assertEqual(body["status"], "cancelled")
        self.assertEqual(body["reason"], "cancelled")
        status, result = self.query("SELECT status, result FROM executions")[0]
        self.assertEqual(status, "cancelled")
        self.assertIsNone(result)
        self.assertNotEqual(self.query("SELECT status FROM agenda")[0][0], "complete")
        stale = json.loads(self.run_cli(
            "complete", info["execution_id"], info["lease_token"], expected=1
        ).stdout)
        self.assertFalse(stale["accepted"])
        self.assertEqual(stale["reason"], "cancelled")
        self.assertTrue(json.loads(self.run_cli("verify").stdout)["ok"])

    def test_proposal_commit_is_fenced_and_does_not_call_act(self):
        self.run_cli("goal", "--key", "packet-1", "propose: packet-1")
        claimed = json.loads(self.run_cli("claim").stdout)
        self.assertEqual(claimed["status"], "claimed")
        refused = json.loads(self.run_cli(
            "cancel", "--key", "cancel-proposal", "execution", claimed["execution_id"]
        ).stdout)
        self.assertEqual(refused["status"], "cancelled")
        late = json.loads(self.run_cli(
            "commit",
            claimed["execution_id"],
            claimed["lease_token"],
            json.dumps({"label": "SYNTHETIC", "proposition": "should not land"}),
            expected=1,
        ).stdout)
        self.assertFalse(late["accepted"])
        self.assertEqual(late["reason"], "cancelled")
        self.assertEqual(self.query("SELECT COUNT(*) FROM memory")[0][0], 0)
        status, result = self.query("SELECT status, result FROM executions")[0]
        self.assertEqual(status, "cancelled")
        self.assertIsNone(result)
        replay = json.loads(self.run_cli(
            "cancel", "--key", "cancel-proposal", "execution", claimed["execution_id"]
        ).stdout)
        self.assertEqual(replay["status"], "duplicate")
        self.assertEqual(self.event_types().count("execution.cancelled"), 1)
        idle = json.loads(self.run_cli("run-once").stdout)
        self.assertEqual(idle["status"], "idle")
        self.assertTrue(json.loads(self.run_cli("verify").stdout)["ok"])

    def test_proposal_commit_succeeds_once_without_memory(self):
        self.run_cli("goal", "--key", "packet-2", "propose: packet-2")
        claimed = json.loads(self.run_cli("claim").stdout)
        stored = json.loads(self.run_cli(
            "commit",
            claimed["execution_id"],
            claimed["lease_token"],
            json.dumps({"label": "SYNTHETIC", "proposition": "beacon = north"}),
        ).stdout)
        self.assertTrue(stored["accepted"])
        self.assertEqual(stored["reason"], "committed")
        self.assertEqual(self.query("SELECT COUNT(*) FROM memory")[0][0], 0)
        self.assertEqual(self.query("SELECT status FROM agenda")[0][0], "complete")
        result = self.query("SELECT result FROM executions")[0][0]
        self.assertIn("beacon = north", result)
        again = json.loads(self.run_cli(
            "commit",
            claimed["execution_id"],
            claimed["lease_token"],
            json.dumps({"label": "SYNTHETIC", "proposition": "beacon = north"}),
            expected=1,
        ).stdout)
        self.assertFalse(again["accepted"])
        self.assertEqual(again["reason"], "already_committed")
        self.assertEqual(self.query("SELECT COUNT(*) FROM executions WHERE status='succeeded'")[0][0], 1)

    def test_cancelling_an_old_attempt_does_not_block_the_successor(self):
        self.run_cli("goal", "--key", "packet-old", "propose: packet-old")
        first = json.loads(self.run_cli("claim").stdout)
        self.assertEqual(json.loads(self.run_cli("recover").stdout)["recovered"], 1)
        agenda_id = self.query("SELECT id FROM agenda")[0][0]
        self.run_cli("retry", agenda_id)
        second = json.loads(self.run_cli("claim").stdout)
        self.assertNotEqual(second["execution_id"], first["execution_id"])
        cancelled = json.loads(self.run_cli(
            "cancel", "--key", "cancel-old-attempt", "execution", first["execution_id"]
        ).stdout)
        self.assertEqual(cancelled["status"], "cancelled")
        stored = json.loads(self.run_cli(
            "commit",
            second["execution_id"],
            second["lease_token"],
            json.dumps({"label": "SYNTHETIC", "proposition": "kept"}),
        ).stdout)
        self.assertTrue(stored["accepted"])
        self.assertEqual(self.query("SELECT status FROM agenda")[0][0], "complete")
        rows = dict(self.query("SELECT id, status FROM executions"))
        self.assertEqual(rows[first["execution_id"]], "cancelled")
        self.assertEqual(rows[second["execution_id"]], "succeeded")

    def test_cancelled_agenda_is_not_finished_by_the_task_loop(self):
        self.run_cli("goal", "--key", "loop-goal", "remember: do not store after cancel")
        agenda_id = self.query("SELECT id FROM agenda")[0][0]
        with sqlite3.connect(self.db) as db:
            db.execute(
                """
                INSERT INTO tasks
                (id,agenda_id,idempotency_key,title,action,status,payload,created,updated)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    "pending-task",
                    agenda_id,
                    "pending-task-key",
                    "pending note",
                    "store_note",
                    "pending",
                    '{"note":"CANCELLED-NOTE-SHOULD-NOT-LAND"}',
                    "2026-11-12T00:00:00+00:00",
                    "2026-11-12T00:00:00+00:00",
                ),
            )
        self.run_cli("cancel", "--key", "cancel-loop", "agenda", agenda_id)
        loop = json.loads(self.run_cli("loop").stdout)
        self.assertEqual(loop["status"], "completed")
        self.assertEqual(self.query("SELECT status FROM agenda WHERE id=?", (agenda_id,))[0][0], "cancelled")
        notes = self.query("SELECT content FROM memory")
        self.assertNotIn(("CANCELLED-NOTE-SHOULD-NOT-LAND",), notes)
        self.assertEqual(self.query("SELECT status FROM tasks")[0][0], "cancelled")

    def test_capitalized_propose_prefix_does_not_starve_pull(self):
        self.run_cli("goal", "--key", "upper", "Propose: capitalized")
        self.run_cli("goal", "--key", "lower", "propose: ok-packet")
        claimed = json.loads(self.run_cli("claim").stdout)
        self.assertEqual(claimed["status"], "claimed")
        self.assertIn("ok-packet", claimed["title"])
        self.assertEqual(json.loads(self.run_cli("claim").stdout)["status"], "idle")

    def test_remember_goal_cannot_be_committed_as_a_proposal(self):
        self.run_cli("goal", "remember: not a proposal")
        agenda_id = self.query("SELECT id FROM agenda")[0][0]
        refused = json.loads(self.run_cli("claim", agenda_id, expected=1).stdout)
        self.assertEqual(refused["status"], "refused")
        self.assertEqual(refused["reason"], "not_a_proposal")
        self.assertEqual(self.query("SELECT status FROM agenda")[0][0], "open")


if __name__ == "__main__":
    unittest.main()
