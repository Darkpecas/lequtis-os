"""LeQutis engineering gate: empty diffs, denylist, repair budget, receipt."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations"))

import engineering_gate as gate  # noqa: E402
import hermes_notify  # noqa: E402

GIT_ACTOR = {
    "GIT_AUTHOR_NAME": "lequtis-test",
    "GIT_AUTHOR_EMAIL": "lequtis-test@example.invalid",
    "GIT_COMMITTER_NAME": "lequtis-test",
    "GIT_COMMITTER_EMAIL": "lequtis-test@example.invalid",
}


def git(cwd: Path, *args: str) -> None:
    env = os.environ.copy()
    env.update(GIT_ACTOR)
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)


def passing_request(**overrides):
    request = {
        "files": ["docs/engineering/DISPOSABLE_AUTOMERGE_PROOF.md"],
        "diff_text": "+harmless proof\n",
        "body": (
            "task_id: disposable-automerge-proof\n\n"
            "## Acceptance criteria\n"
            "- docs/engineering/DISPOSABLE_AUTOMERGE_PROOF.md is added\n"
            "- The change is docs-only markdown\n"
            "- The change adds no credentials\n"
            "- tests pass\n"
            "- independent review passes\n"
        ),
        "checks": [
            {"name": "verify", "status": "completed", "conclusion": "success", "html_url": "https://example.test/verify"},
            {"name": "review", "status": "completed", "conclusion": "success", "html_url": "https://example.test/review"},
        ],
        "review": {"verdict": "pass", "in_scope": True, "findings": [], "head_sha": "abc", "run_url": "https://example.test/review"},
        "duplicate": False,
        "duplicate_scan": "complete",
        "repairs": [],
        "pr_url": "https://github.com/Darkpecas/lequtis-os/pull/1",
        "head_sha": "abc",
        "draft": False,
        "same_repo": True,
        "merge_commit_sha": None,
        "read_back": {"confirmed": False, "default_branch": "main", "observed_sha": None, "reason": "not_merged"},
        "secrets": {"LEQUTIS_REVIEWER_API_KEY": "present"},
        "notify": {"telegram_delivered": False, "degraded": True, "reason": "test"},
        "gate_run_url": "https://example.test/run",
    }
    request.update(overrides)
    return request


class EngineeringGateTests(unittest.TestCase):
    def test_docs_change_merges_only_when_it_is_genuinely_necessary(self):
        receipt = gate.build_receipt(passing_request())
        self.assertTrue(receipt["genuinely_necessary"])
        self.assertEqual(receipt["merge_decision"], "merge")
        self.assertEqual(receipt["merge_reason"], "allowed")
        self.assertFalse(receipt["live_hermes"])
        self.assertFalse(receipt["notify"]["telegram_delivered"])
        for key in (
            "task_id", "pr_url", "head_sha", "review", "checks", "merge_decision",
            "merge_reason", "merge_commit_sha", "read_back", "repairs",
        ):
            self.assertIn(key, receipt)
        self.assertEqual(receipt["task_id"], "disposable-automerge-proof")
        self.assertEqual(receipt["review"]["verdict"], "pass")
        self.assertTrue(all(item["met"] for item in receipt["acceptance"]))
        self.assertTrue(receipt["checks"])
        self.assertTrue(receipt["checks"][0]["run_url"])

    def test_definition_blocks_empty_duplicate_and_out_of_scope_work(self):
        empty = gate.build_receipt(passing_request(files=[], diff_text=""))
        self.assertFalse(empty["genuinely_necessary"])
        self.assertIn("empty_pr", empty["merge_reason"])
        duplicate = gate.build_receipt(passing_request(duplicate=True, duplicate_of="https://example.test/pr/9"))
        self.assertFalse(duplicate["genuinely_necessary"])
        self.assertIn("duplicate_work", duplicate["merge_reason"])
        out_of_scope = gate.build_receipt(passing_request(
            review={"verdict": "pass", "in_scope": False, "findings": [], "run_url": "https://example.test/review"},
        ))
        self.assertFalse(out_of_scope["genuinely_necessary"])
        self.assertNotEqual(out_of_scope["merge_decision"], "merge")

    def test_denylist_holds_infra_secrets_migrations_and_destructive_text(self):
        held = gate.build_receipt(passing_request(
            files=["infra/terraform/DISPOSABLE_HOLD.md"],
            diff_text="+hold fixture\n",
            body=(
                "task_id: hold\n\n## Acceptance criteria\n"
                "- infra/terraform/DISPOSABLE_HOLD.md is added\n"
            ),
        ))
        self.assertTrue(held["risk"]["needs_human"])
        self.assertEqual(held["merge_decision"], "hold")
        self.assertIn("needs_human", held["merge_reason"])
        for path in (
            ".env",
            "secrets/api.key",
            "database/migrations/001.sql",
            "database/schema.sql",
            "scripts/destroy.sh",
            "deploy/app.yml",
            ".github/workflows/lequtis-engineering-gate.yml",
        ):
            report = gate.risk_report([path], "")
            self.assertTrue(report["needs_human"], path)
        destructive = " ".join(("DROP", "TABLE events;"))
        self.assertIn("destructive_sql", gate.keyword_reasons("+" + destructive + "\n"))

    def test_missing_reviewer_secret_fails_closed_inside_the_receipt(self):
        receipt = gate.build_receipt(passing_request(
            review={
                "verdict": "fail_closed",
                "in_scope": False,
                "findings": [{"severity": "blocking", "summary": "LEQUTIS_REVIEWER_API_KEY is absent"}],
                "secret": {"LEQUTIS_REVIEWER_API_KEY": "absent"},
                "run_url": "https://example.test/review",
            },
            checks=[
                {"name": "verify", "status": "completed", "conclusion": "success", "html_url": "https://example.test/verify"},
                {"name": "review", "status": "completed", "conclusion": "failure", "html_url": "https://example.test/review"},
            ],
        ))
        self.assertEqual(receipt["merge_decision"], "hold")
        self.assertIn("independent_review_fail_closed", receipt["merge_reason"])
        self.assertIn("checks_failed", receipt["merge_reason"])

    def test_unverified_claim_and_unchecked_criterion_block_merge(self):
        claim = gate.build_receipt(passing_request(body=passing_request()["body"] + "\nVERIFIED\n"))
        self.assertIn("unverified_completion_claim", claim["merge_reason"])
        unchecked = gate.build_receipt(passing_request(body=(
            "task_id: proof\n\n## Acceptance criteria\n- [ ] tests pass\n"
        )))
        self.assertFalse(unchecked["acceptance"][0]["met"])
        self.assertIn("acceptance_unmet", unchecked["merge_reason"])

    def test_repair_budget_is_two_and_records_excerpt_and_commit(self):
        first = gate.plan_repair([], "No newline at end of file\n", {"docs/note.md": "hello"})
        self.assertTrue(first["allowed"])
        self.assertEqual(first["attempt"], 1)
        self.assertIn("No newline", first["log_excerpt"])
        self.assertIsNone(first["fix_commit"])
        self.assertTrue(first["files"]["docs/note.md"].endswith("\n"))
        existing = [{"sha": "a" * 40, "message": first["commit_message"]}]
        second = gate.plan_repair(existing, "No newline at end of file\n", {"docs/note.md": "hello"})
        self.assertEqual(second["attempt"], 2)
        recorded = gate.repairs_from_commits([
            {"sha": "a" * 40, "message": first["commit_message"]},
            {"sha": "b" * 40, "message": second["commit_message"]},
        ])
        self.assertEqual([item["fix_commit"] for item in recorded], ["a" * 40, "b" * 40])
        third = gate.plan_repair(
            [{"sha": item["fix_commit"], "message": "lequtis-repair " + str(item["attempt"]) + "/2\nexcerpt: x"} for item in recorded],
            "No newline at end of file\n",
            {"docs/note.md": "hello"},
        )
        self.assertFalse(third["allowed"])
        self.assertEqual(third["reason"], "repair_budget_exhausted")
        refused = gate.plan_repair([], "AssertionError: kernel", {"docs/note.md": "hello"})
        self.assertFalse(refused["allowed"])
        self.assertEqual(refused["reason"], "not_recoverable")
        self.assertIn("AssertionError", refused["log_excerpt"])
        secret = "super-secret-value"
        os.environ["LEQUTIS_REVIEWER_API_KEY"] = secret
        try:
            scrubbed = gate.plan_repair([], "No newline at end of file " + secret, {"docs/note.md": "hello"})
        finally:
            os.environ.pop("LEQUTIS_REVIEWER_API_KEY", None)
        self.assertNotIn(secret, json.dumps(scrubbed))

    def test_repair_refuses_a_denylisted_path(self):
        plan = gate.plan_repair([], "No newline at end of file\n", {"infra/terraform/app.tf": "x"})
        self.assertFalse(plan["allowed"])
        self.assertEqual(plan["files"], {})

    def test_read_back_requires_the_merge_commit_on_main(self):
        missing = gate.confirm_read_back("OPEN", None, False)
        self.assertFalse(missing["confirmed"])
        landed = gate.confirm_read_back("MERGED", "c" * 40, True)
        self.assertTrue(landed["confirmed"])
        self.assertEqual(landed["observed_sha"], "c" * 40)
        failed = gate.apply_merge_result(
            gate.build_receipt(passing_request()),
            1,
            "merge refused",
            missing,
        )
        self.assertEqual(failed["merge_decision"], "hold")
        self.assertIn("merge_command_failed", failed["merge_reason"])

    def test_six_canceling_commits_have_an_empty_net_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init", "-b", "main")
            (root / "note.txt").write_text("base\n", encoding="utf-8")
            git(root, "add", "note.txt")
            git(root, "commit", "-m", "base")
            git(root, "checkout", "-b", "edits")
            for number in range(1, 6):
                (root / "note.txt").write_text("edit-" + str(number) + "\n", encoding="utf-8")
                git(root, "commit", "-am", "edit-" + str(number))
            (root / "note.txt").write_text("base\n", encoding="utf-8")
            git(root, "commit", "-am", "restore")
            count = subprocess.run(
                ["git", "-C", str(root), "rev-list", "--count", "main..HEAD"],
                text=True, capture_output=True, check=True,
            )
            names = subprocess.run(
                ["git", "-C", str(root), "diff", "--name-only", "main...HEAD"],
                text=True, capture_output=True, check=True,
            )
            self.assertEqual(count.stdout.strip(), "6")
            self.assertEqual(names.stdout.strip(), "")
            shas = subprocess.run(
                ["git", "-C", str(root), "rev-list", "--reverse", "main..HEAD"],
                text=True, capture_output=True, check=True,
            )
            self.assertEqual(len(shas.stdout.split()), 6)

    def test_a_reapplied_patch_is_a_duplicate_of_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init", "-b", "main")
            (root / "note.txt").write_text("a\n", encoding="utf-8")
            git(root, "add", "note.txt")
            git(root, "commit", "-m", "base")
            (root / "note.txt").write_text("b\n", encoding="utf-8")
            git(root, "commit", "-am", "to-b")
            (root / "note.txt").write_text("a\n", encoding="utf-8")
            git(root, "commit", "-am", "back")
            git(root, "checkout", "-b", "again")
            (root / "note.txt").write_text("b\n", encoding="utf-8")
            git(root, "commit", "-am", "to-b-again")
            diff = subprocess.run(
                ["git", "-C", str(root), "diff", "main...HEAD"],
                text=True, capture_output=True, check=True,
            )
            self.assertIn("b", diff.stdout)
            self.assertTrue(gate.patch_already_on_base(diff.stdout, str(root), "main"))
            self.assertEqual(gate.find_duplicate_diff(diff.stdout, [("https://example.test/pr/3", diff.stdout)]), "https://example.test/pr/3")

    def test_core_change_waits_for_the_sovereign_loop(self):
        receipt = gate.build_receipt(passing_request(files=["core/lequtis.py"], diff_text="+# note\n"))
        self.assertIn("checks_failed", receipt["merge_reason"])
        self.assertIn("sovereign-loop", receipt["check_summary"]["missing"])

    def test_workflows_keep_the_reviewer_from_writing_code(self):
        review = (ROOT / ".github/workflows/lequtis-independent-review.yml").read_text(encoding="utf-8")
        gate_workflow = (ROOT / ".github/workflows/lequtis-engineering-gate.yml").read_text(encoding="utf-8")
        old = (ROOT / ".github/workflows/lequtis-pr-gate.yml").read_text(encoding="utf-8")
        self.assertIn("contents: read", review)
        self.assertNotIn("contents: write", review)
        self.assertIn("persist-credentials: false", review)
        self.assertIn("LEQUTIS_REVIEWER_API_KEY", review)
        self.assertIn("gemini-3.8-flash", (ROOT / "integrations/independent_reviewer.py").read_text(encoding="utf-8"))
        self.assertIn("contents: write", gate_workflow)
        self.assertIn("Require the free Gemini review before merge", old)
        self.assertIn("steps.gemini.outputs.allow == 'true'", old)
        definition = (ROOT / "docs/engineering/ENGINEERING_GATE.md").read_text(encoding="utf-8")
        self.assertIn("non-empty net diff", definition)
        self.assertIn("no duplicate", definition)
        self.assertIn("in scope", definition)

    def test_hermes_summary_degrades_and_hides_secret_values(self):
        secret = "tunnel-secret-value"
        os.environ["LEQUTIS_TUNNEL_API_KEY"] = secret
        try:
            report = hermes_notify.deliver("status " + secret)
        finally:
            os.environ.pop("LEQUTIS_TUNNEL_API_KEY", None)
        encoded = json.dumps(report)
        self.assertFalse(report["telegram_delivered"])
        self.assertFalse(report["live_host"])
        self.assertTrue(report["degraded"])
        self.assertEqual(report["presence"]["LEQUTIS_TUNNEL_API_KEY"], "present")
        self.assertNotIn(secret, encoded)


if __name__ == "__main__":
    unittest.main()
