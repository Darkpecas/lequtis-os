"""ACT integration regression tests, disposable state only."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
import lequtis as L

class ActPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lq-act-policy-")
        self.old = (L.STATE, L.DB)
        L.STATE = Path(self.tmp.name)
        L.DB = L.STATE / "lequtis.db"
        L.init()

    def tearDown(self):
        L.STATE, L.DB = self.old
        self.tmp.cleanup()

    def choice(self, action, key):
        return {"kind": "goal", "action": action, "idempotency_key": key,
                "agenda_id": None, "payload": {}}

    def test_authorized_action_receipt(self):
        result = L.act(self.choice("ping", "policy-ping"))
        self.assertTrue(result["ok"], result)
        with L.connect() as db:
            names = [row[0] for row in db.execute("SELECT event_type FROM events")]
        self.assertIn("task.policy_allowed", names)
        self.assertIn("task.completed", names)
        self.assertTrue(L.verify_event_chain()["ok"])

    def test_unregistered_action_blocked_before_execution(self):
        executed = []
        L.ACTIONS["untrusted"] = lambda payload: executed.append(payload)
        try:
            result = L.act(self.choice("untrusted", "policy-deny"))
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "policy_denied:unregistered_action")
            self.assertFalse(executed)
            with L.connect() as db:
                names = [row[0] for row in db.execute("SELECT event_type FROM events")]
            self.assertIn("task.policy_denied", names)
            self.assertNotIn("task.started", names)
            self.assertTrue(L.verify_event_chain()["ok"])
        finally:
            L.ACTIONS.pop("untrusted", None)

    def test_caller_policy_cannot_override_registry(self):
        c = self.choice("untrusted", "policy-spoof")
        c["payload"] = {"clearance": 99, "policy": "allow", "resource_level": 0}
        self.assertFalse(L.act(c)["ok"])

if __name__ == "__main__":
    unittest.main()
