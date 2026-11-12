"""Regression checks for the fail-closed GitHub Actions security hold.

This is repository static evidence, not authenticated GitHub/production proof.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


class WorkflowSecurityHoldTests(unittest.TestCase):
    def read_workflow(self, name):
        return (WORKFLOWS / name).read_text(encoding="utf-8")

    def test_no_pr_automation_can_merge_or_push(self):
        for name in ("lequtis-engineering-gate.yml", "lequtis-pr-gate.yml"):
            with self.subTest(name=name):
                source = self.read_workflow(name)
                self.assertNotIn("gh pr merge", source)
                self.assertNotIn("git push origin", source)
                self.assertNotIn("contents: write", source)
                self.assertNotIn("pull-requests: write", source)
                self.assertNotIn("issues: write", source)

    def test_engineering_assessor_has_no_production_secrets(self):
        source = self.read_workflow("lequtis-engineering-gate.yml")
        self.assertNotIn("secrets.", source)
        self.assertNotIn("  merge:", source)
        self.assertNotIn("  repair:", source)
        self.assertNotIn("name: Post the receipt", source)
        self.assertNotIn("name: Sync the needs-human label", source)

    def test_legacy_gate_does_not_fail_open_on_missing_checks(self):
        source = self.read_workflow("lequtis-pr-gate.yml")
        self.assertNotIn("No failing required checks after wait", source)
        self.assertNotIn("pass|success|skipping", source)

    def test_reviewer_executes_trusted_base_not_pr_head(self):
        source = self.read_workflow("lequtis-independent-review.yml")
        self.assertIn("  pull_request_target:", source)
        self.assertNotIn("  pull_request:", source)
        self.assertIn("ref: ${{ github.event.pull_request.base.sha }}", source)
        self.assertIn('git diff "HEAD...${HEAD_SHA}"', source)
        self.assertNotIn("ref: ${{ github.event.pull_request.head.sha }}", source)


if __name__ == "__main__":
    unittest.main()
