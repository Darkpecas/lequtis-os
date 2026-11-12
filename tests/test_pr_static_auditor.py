"""Independent static auditor findings for empty, secret, and acceptance gaps."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integrations.pr_static_auditor import audit  # noqa: E402


class PrStaticAuditorTests(unittest.TestCase):
    def test_empty_diff_is_a_high_finding(self):
        result = audit(files=[], body="tests passed", title="Empty")
        self.assertEqual(result["status"], "findings")
        self.assertTrue(any(f["code"] == "empty_diff" for f in result["findings"]))
        self.assertTrue(result["independent_of_implementer"])
        self.assertFalse(result["live_hermes"])

    def test_clean_docs_pass(self):
        result = audit(
            files=["docs/engineering/note.md"],
            body="Acceptance: disposable tests and evidence/pr-gate-receipt.json",
            title="docs: note",
            diff_text="+hello\n",
        )
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["findings"], [])

    def test_secret_like_and_workflow_changes_fail(self):
        fake_key = "api_key = '" + ("k" * 20) + "'"
        secret = audit(
            files=["docs/note.md"],
            diff_text="+++ b/docs/note.md\n+" + fake_key + "\n",
            body="tests evidence",
        )
        self.assertTrue(any(f["code"] == "secret_like_diff" for f in secret["findings"]))
        ignored = audit(
            files=["tests/test_pr_static_auditor.py"],
            diff_text="+++ b/tests/test_pr_static_auditor.py\n+" + fake_key + "\n",
            body="tests evidence acceptance",
        )
        self.assertFalse(any(f["code"] == "secret_like_diff" for f in ignored["findings"]))
        workflow = audit(
            files=[".github/workflows/lequtis-pr-gate.yml"],
            body="tests evidence acceptance",
        )
        self.assertTrue(any(f["code"] == "workflow_change" for f in workflow["findings"]))

    def test_completion_without_acceptance_markers_fails(self):
        result = audit(
            files=["docs/note.md"],
            title="Complete the ship",
            body="We finished everything.",
        )
        self.assertTrue(
            any(f["code"] == "missing_acceptance_evidence" for f in result["findings"])
        )


if __name__ == "__main__":
    unittest.main()
