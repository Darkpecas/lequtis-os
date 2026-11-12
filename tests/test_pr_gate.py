"""The PR gate refuses empty, duplicate, dangerous, and unverified changes."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integrations.pr_gate import decide, git_files  # noqa: E402


class PrGateTests(unittest.TestCase):
    def test_harmless_docs_can_merge_only_when_review_and_tests_pass(self):
        allowed = decide(
            files=["docs/engineering/HARMLESS_AUTOMERGE_PROOF.md"],
            tests_passed=True,
            ai_review="pass",
            static_audit="pass",
            duplicate=False,
        )
        self.assertTrue(allowed["merge_allowed"])
        self.assertEqual(allowed["blocking"], [])
        self.assertFalse(allowed["live_hermes"])
        self.assertFalse(allowed["live_telegram"])

    def test_empty_and_duplicate_prs_are_blocked(self):
        empty = decide(files=[], tests_passed=True, ai_review="pass", duplicate=False)
        self.assertIn("empty_pr", empty["blocking"])
        self.assertFalse(empty["merge_allowed"])
        duplicate = decide(
            files=["docs/note.md"], tests_passed=True, ai_review="pass", duplicate=True,
        )
        self.assertIn("duplicate_work", duplicate["blocking"])

    def test_credentials_migrations_workflows_and_destructive_text_are_blocked(self):
        cases = [
            [" .env".strip()],
            ["database/migrations/lequtis-os-kernel-3-to-4.sql"],
            [".github/workflows/lequtis-pr-gate.yml"],
            ["runtime/hermes-stdio-connector/lequtis_mcp_stdio.py"],
            ["integrations/hermes_receipt_gate.py"],
        ]
        for files in cases:
            verdict = decide(files=files, tests_passed=True, ai_review="pass", duplicate=False)
            self.assertFalse(verdict["merge_allowed"], files)
            self.assertIn("blocked_change", verdict["blocking"])
        destructive = decide(
            files=["docs/note.md"],
            diff_text="+++ b/docs/note.md\n+DROP TABLE events;\n",
            tests_passed=True,
            ai_review="pass",
            duplicate=False,
        )
        self.assertIn("DROP TABLE", destructive["destructive"])
        self.assertFalse(destructive["merge_allowed"])
        listed_only = decide(
            files=["docs/note.md"],
            diff_text="+++ b/docs/note.md\n+DESTRUCTIVE_MARKERS = (\"DROP TABLE\",)\n",
            tests_passed=True,
            ai_review="pass",
            duplicate=False,
        )
        self.assertIn("DROP TABLE", listed_only["destructive"])
        context_only = decide(
            files=["docs/note.md"],
            diff_text="+++ b/docs/note.md\n-DROP TABLE events;\n+safe text\n",
            tests_passed=True,
            ai_review="pass",
            duplicate=False,
        )
        self.assertEqual(context_only["destructive"], [])

    def test_rename_source_paths_block_harmless_docs_claim(self):
        verdict = decide(
            files=[
                "runtime/hermes-stdio-connector/lequtis_mcp_stdio.py",
                "docs/example.md",
            ],
            tests_passed=True,
            ai_review="pass",
            static_audit="pass",
            duplicate=False,
        )
        self.assertFalse(verdict["harmless"])
        self.assertIn("blocked_change", verdict["blocking"])

    def test_kernel_code_is_not_auto_merged(self):
        verdict = decide(
            files=["core/lequtis.py"],
            tests_passed=True,
            ai_review="pass",
            duplicate=False,
        )
        self.assertFalse(verdict["harmless"])
        self.assertIn("not_harmless", verdict["blocking"])

    def test_unverified_claim_and_missing_review_block_merge(self):
        claim = decide(
            files=["docs/note.md"],
            body="This is VERIFIED.",
            tests_passed=True,
            ai_review="pass",
            duplicate=False,
        )
        self.assertTrue(claim["unverified_claim"])
        self.assertIn("unverified_completion_claim", claim["blocking"])
        missing = decide(
            files=["docs/note.md"],
            tests_passed=True,
            ai_review="missing",
            duplicate=False,
        )
        self.assertIn("independent_review_missing", missing["blocking"])
        findings = decide(
            files=["docs/note.md"],
            tests_passed=False,
            ai_review="findings",
            duplicate=False,
            test_attempts=2,
        )
        self.assertTrue(findings["repair"]["attempted"])
        self.assertEqual(findings["repair"]["max_attempts"], 2)
        self.assertIn("tests_failed", findings["blocking"])

    def test_static_audit_findings_block_merge(self):
        verdict = decide(
            files=["docs/note.md"],
            tests_passed=True,
            ai_review="pass",
            static_audit="findings",
            duplicate=False,
        )
        self.assertIn("static_audit_findings", verdict["blocking"])
        self.assertFalse(verdict["merge_allowed"])

    def test_git_diff_detects_an_empty_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = os.environ.copy()
            env.update({
                "GIT_AUTHOR_NAME": "lequtis-test",
                "GIT_AUTHOR_EMAIL": "lequtis-test@example.invalid",
                "GIT_COMMITTER_NAME": "lequtis-test",
                "GIT_COMMITTER_EMAIL": "lequtis-test@example.invalid",
            })

            def git(*args: str) -> None:
                subprocess.run(
                    ["git", "-C", str(root), *args],
                    check=True,
                    env={**env},
                    capture_output=True,
                )

            git("init", "-b", "main")
            (root / "docs").mkdir()
            (root / "docs" / "note.md").write_text("one\n", encoding="utf-8")
            git("add", "docs")
            git("commit", "-m", "base")
            git("commit", "--allow-empty", "-m", "empty-one")
            git("commit", "--allow-empty", "-m", "empty-two")
            files = git_files("main", "HEAD", cwd=str(root))
            self.assertEqual(files, [])


if __name__ == "__main__":
    unittest.main()
