"""The PR gate refuses empty, duplicate, dangerous, and unverified changes."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integrations.pr_auditor import audit, resolve_independent_review  # noqa: E402
from integrations.pr_gate import decide, git_files  # noqa: E402
from integrations.pr_workflow_receipt import build_receipt, record_merge  # noqa: E402


class PrGateTests(unittest.TestCase):
    def test_harmless_docs_can_merge_only_when_review_and_tests_pass(self):
        allowed = decide(
            files=["docs/engineering/HARMLESS_AUTOMERGE_PROOF.md"],
            tests_passed=True,
            codex_status="missing",
            duplicate=False,
            required_checks_passed=True,
            labels=[],
            labels_verified=True,
        )
        self.assertTrue(allowed["merge_allowed"])
        self.assertEqual(allowed["blocking"], [])
        self.assertEqual(allowed["review_source"], "auditor_fallback")
        self.assertFalse(allowed["live_hermes"])

    def test_codex_pass_still_requires_auditor_pass(self):
        allowed = decide(
            files=["docs/engineering/HARMLESS_AUTOMERGE_PROOF.md"],
            tests_passed=True,
            codex_status="pass",
            duplicate=False,
            labels=[],
            labels_verified=True,
        )
        self.assertTrue(allowed["merge_allowed"])
        self.assertEqual(allowed["review_source"], "codex+auditor")

    def test_empty_and_duplicate_prs_are_blocked(self):
        empty = decide(files=[], tests_passed=True, codex_status="missing", duplicate=False)
        self.assertIn("empty_pr", empty["blocking"])
        self.assertFalse(empty["merge_allowed"])
        duplicate = decide(
            files=["docs/note.md"],
            tests_passed=True,
            codex_status="missing",
            duplicate=True,
        )
        self.assertIn("duplicate_work", duplicate["blocking"])

    def test_credentials_migrations_workflows_and_destructive_added_lines_are_blocked(self):
        cases = [
            [".env"],
            ["database/migrations/lequtis-os-kernel-3-to-4.sql"],
            [".github/workflows/lequtis-pr-gate.yml"],
            ["runtime/hermes-stdio-connector/lequtis_mcp_stdio.py"],
        ]
        for files in cases:
            verdict = decide(
                files=files, tests_passed=True, codex_status="missing", duplicate=False
            )
            self.assertFalse(verdict["merge_allowed"], files)
            self.assertIn("blocked_change", verdict["blocking"])
        destructive = decide(
            files=["docs/note.md"],
            diff_text="+++ b/docs/note.md\n@@\n+DROP TABLE events;\n",
            tests_passed=True,
            codex_status="missing",
            duplicate=False,
        )
        self.assertTrue(destructive["destructive"])
        self.assertFalse(destructive["merge_allowed"])

    def test_marker_definitions_in_source_are_not_false_destructive(self):
        # The gate source itself lists markers; defining them must not block.
        diff = (
            "+++ b/integrations/pr_gate.py\n"
            "@@\n"
            '+DESTRUCTIVE_MARKERS = ("DROP TABLE", "DROP DATABASE")\n'
            '+    "hosting_websites_delete",\n'
            '+    "vps_virtual-machines_recreate",\n'
            '+    "rm -rf /",\n'
            "+SECRET_ASSIGNMENT = re.compile(\n"
            "+          GH_TOKEN: ${{ github.token }}\n"
            "+- Destructive lines (`DROP TABLE`, `rm -rf /`)\n"
        )
        auditor = audit(files=["integrations/pr_gate.py"], diff_text=diff)
        self.assertEqual(auditor["status"], "pass", auditor["findings"])
        self.assertEqual(auditor["findings"], [])

    def test_evidence_label_and_prose_do_not_trip_claim_checks(self):
        auditor = audit(
            files=["docs/note.md"],
            body=(
                "Completes the workflow. Canonical tree already contains the merged "
                "port. LOCAL PROOF, NOT LIVE VPS VERIFIED."
            ),
        )
        self.assertEqual(auditor["status"], "pass", auditor["findings"])

    def test_literal_secret_assignment_is_flagged(self):
        auditor = audit(
            files=["docs/note.md"],
            diff_text="+++ b/docs/note.md\n@@\n+API_TOKEN = 'supersecrettokenvalue'\n",
        )
        self.assertIn("credentials", {f["code"] for f in auditor["findings"]})

    def test_quoted_shell_destructive_commands_are_flagged(self):
        auditor = audit(
            files=["docs/runbook.md"],
            diff_text='+++ b/docs/runbook.md\n@@\n+bash -c "rm -rf /srv/data"\n',
        )
        self.assertIn(
            "destructive_operation", {f["code"] for f in auditor["findings"]}
        )
        self.assertFalse(
            decide(
                files=["docs/runbook.md"],
                diff_text='+++ b/docs/runbook.md\n@@\n+bash -c "rm -rf /srv/data"\n',
                tests_passed=True,
                codex_status="missing",
                duplicate=False,
            )["merge_allowed"]
        )

    def test_needs_human_mixed_and_gate_diffs_are_not_merged(self):
        labelled = decide(
            files=["docs/note.md"],
            tests_passed=True,
            codex_status="missing",
            duplicate=False,
            labels=["needs-human"],
            labels_verified=True,
        )
        self.assertFalse(labelled["merge_allowed"])
        self.assertIn("needs_human_label", labelled["blocking"])
        mixed = decide(
            files=["docs/note.md", "core/lequtis.py"],
            tests_passed=True,
            codex_status="missing",
            duplicate=False,
            labels=[],
            labels_verified=True,
        )
        self.assertFalse(mixed["merge_allowed"])
        self.assertIn("not_docs_only", mixed["blocking"])
        self.assertTrue(mixed["label_needs_human"])
        workflow = decide(
            files=[".github/workflows/lequtis-pr-gate.yml"],
            tests_passed=True,
            codex_status="missing",
            duplicate=False,
            labels=[],
            labels_verified=True,
        )
        self.assertFalse(workflow["merge_allowed"])
        self.assertTrue(workflow["label_needs_human"])
        clean = decide(
            files=["docs/note.md", "README.md"],
            tests_passed=True,
            codex_status="missing",
            duplicate=False,
            labels=[],
            labels_verified=True,
        )
        self.assertTrue(clean["merge_allowed"])
        self.assertEqual(clean["blocking"], [])
        unverified = decide(
            files=["docs/note.md"],
            tests_passed=True,
            codex_status="missing",
            duplicate=False,
        )
        self.assertFalse(unverified["merge_allowed"])
        self.assertIn("labels_unverified", unverified["blocking"])

    def test_kernel_code_is_not_auto_merged(self):
        verdict = decide(
            files=["core/lequtis.py"],
            tests_passed=True,
            codex_status="missing",
            duplicate=False,
        )
        self.assertFalse(verdict["harmless"])
        self.assertIn("not_harmless", verdict["blocking"])

    def test_unverified_claim_and_codex_findings_block_merge(self):
        claim = decide(
            files=["docs/note.md"],
            body="This is VERIFIED.",
            tests_passed=True,
            codex_status="missing",
            duplicate=False,
        )
        self.assertTrue(claim["unverified_claim"])
        self.assertIn("unverified_completion_claim", claim["blocking"])
        findings = decide(
            files=["docs/note.md"],
            tests_passed=False,
            codex_status="findings",
            duplicate=False,
            test_attempts=2,
        )
        self.assertTrue(findings["repair"]["attempted"])
        self.assertEqual(findings["repair"]["max_attempts"], 2)
        self.assertIn("tests_failed", findings["blocking"])
        self.assertIn("independent_review_findings", findings["blocking"])

    def test_required_checks_failure_blocks_merge(self):
        verdict = decide(
            files=["docs/note.md"],
            tests_passed=True,
            codex_status="missing",
            duplicate=False,
            required_checks_passed=False,
        )
        self.assertIn("required_checks_failed", verdict["blocking"])
        self.assertFalse(verdict["merge_allowed"])

    def test_resolve_independent_review_prefers_codex_findings(self):
        auditor = {"status": "pass", "findings": []}
        resolved = resolve_independent_review(codex_status="findings", auditor=auditor)
        self.assertEqual(resolved["ai_review"], "findings")

    def test_engineering_receipt_links_task_and_correlation(self):
        gate = decide(
            files=["docs/note.md"],
            tests_passed=True,
            codex_status="missing",
            duplicate=False,
        )
        receipt = build_receipt(
            pr_number=99,
            head_sha="abc123def456",
            base_ref="main",
            gate_verdict=gate,
        )
        self.assertEqual(receipt["schema"], "lequtis.engineering_workflow_receipt.v1")
        self.assertEqual(receipt["payload"]["task_id"], "eng-pr-99")
        self.assertTrue(receipt["payload"]["correlation_id"].startswith("pr-99-"))
        self.assertFalse(receipt["live_hermes"])
        merged = record_merge(receipt, "mergecafe00")
        self.assertTrue(merged["result"]["merged"])
        self.assertEqual(merged["result"]["merge_sha"], "mergecafe00")
        self.assertEqual(
            merged["payload"]["result_sha256"],
            __import__("integrations.pr_workflow_receipt", fromlist=["result_sha256"]).result_sha256(
                merged["result"]
            ),
        )

    def test_git_diff_detects_an_empty_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = os.environ.copy()
            env.update(
                {
                    "GIT_AUTHOR_NAME": "lequtis-test",
                    "GIT_AUTHOR_EMAIL": "lequtis-test@example.invalid",
                    "GIT_COMMITTER_NAME": "lequtis-test",
                    "GIT_COMMITTER_EMAIL": "lequtis-test@example.invalid",
                }
            )

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
