"""Engineering workflow receipts link task → PR → review → tests → merge."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integrations.engineering_workflow import (  # noqa: E402
    SCHEMA,
    build_receipt,
    event_payload,
    update_merge_outcome,
    write_receipt,
)


class EngineeringWorkflowTests(unittest.TestCase):
    def test_receipt_links_stages_without_claiming_live_infra(self):
        receipt = build_receipt(
            task_id="gate-demo",
            pr_number=99,
            pr_url="https://github.com/Darkpecas/lequtis-os/pull/99",
            head_sha="abc",
            base_ref="main",
            gate_verdict={"merge_allowed": False, "blocking": ["not_harmless"]},
            static_audit={"status": "findings", "findings": [{"code": "workflow_change"}]},
            ai_review="pass",
            tests_passed=True,
            test_attempts=1,
            actions_run_url="https://github.com/Darkpecas/lequtis-os/actions/runs/1",
        )
        self.assertEqual(receipt["schema"], SCHEMA)
        self.assertEqual(receipt["authority"], "LeQutis")
        self.assertFalse(receipt["live_hermes"])
        self.assertFalse(receipt["live_hostinger"])
        self.assertFalse(receipt["live_telegram"])
        self.assertEqual(receipt["stages"]["pull_request"]["number"], 99)
        self.assertEqual(receipt["stages"]["independent_review"]["ai_review"], "pass")
        self.assertEqual(receipt["stages"]["tests"]["status"], "pass")
        self.assertFalse(receipt["stages"]["verify"]["merge_allowed"])
        self.assertTrue(receipt["receipt_sha256"])
        payload = event_payload(receipt)
        self.assertEqual(payload["correlation_id"], receipt["correlation_id"])
        self.assertFalse(payload["live_hermes"])

    def test_write_receipt_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            receipt = build_receipt(task_id="t1", tests_passed=True, test_attempts=1)
            write_receipt(path, receipt)
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["task_id"], "t1")
            self.assertEqual(loaded["receipt_sha256"], receipt["receipt_sha256"])

    def test_update_merge_outcome_preserves_correlation_id(self):
        receipt = build_receipt(
            task_id="t1",
            tests_passed=True,
            test_attempts=1,
            correlation_id="eng-fixed-id",
        )
        updated = update_merge_outcome(
            receipt, merge_attempted=True, merge_result="merged"
        )
        self.assertEqual(updated["correlation_id"], "eng-fixed-id")
        self.assertTrue(updated["stages"]["auto_merge"]["attempted"])
        self.assertEqual(updated["stages"]["auto_merge"]["result"], "merged")
        self.assertNotEqual(updated["receipt_sha256"], receipt["receipt_sha256"])


if __name__ == "__main__":
    unittest.main()
