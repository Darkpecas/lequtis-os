"""Independent PR gate. Static checks are not execution and not a live proof."""
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import pr_gate  # noqa: E402


def base(**overrides):
    report = {
        "number": 70,
        "body": "Task-Id: disposable-marker\nLOCAL PROOF, NOT LIVE VPS VERIFIED\n",
        "commits": [{"oid": "abc"}],
        "files": [
            {
                "path": "evidence/pr-gate-disposable/MARKER.md",
                "additions": 2,
                "deletions": 0,
            }
        ],
        "diff": "+harmless marker\n+LOCAL PROOF, NOT LIVE VPS VERIFIED\n",
        "draft": False,
        "same_repo": True,
        "tests_passed": True,
        "checks_state": "pass",
        "duplicate_of": None,
    }
    report.update(overrides)
    return report


class PRGateTests(unittest.TestCase):
    def test_harmless_change_can_merge_only_when_execution_passed(self):
        pending = pr_gate.assess(base(tests_passed=None, checks_state=None), for_merge=False)
        self.assertEqual(pending["decision"], "hold")
        self.assertEqual(pending["stages"]["static_validation"]["status"], "pass")
        self.assertEqual(pending["stages"]["local_execution"]["status"], "pending")
        self.assertEqual(pending["stages"]["live_end_to_end"]["status"], "not_this_job")
        self.assertFalse(pending["fails_check"])

        ready = pr_gate.assess(base(), for_merge=True)
        self.assertEqual(ready["decision"], "merge")
        self.assertEqual(ready["stages"]["local_execution"]["status"], "pass")
        self.assertNotEqual(ready["stages"]["live_end_to_end"]["status"], "passed")
        self.assertEqual(ready["task_id"], "disposable-marker")

    def test_six_commits_with_zero_files_are_not_invented_back(self):
        report = base(
            commits=[{"oid": f"c{i}"} for i in range(6)],
            files=[],
            diff="",
            body="Task-Id: git22-pr4-class\n",
        )
        receipt = pr_gate.assess(report, for_merge=True)
        self.assertEqual(receipt["decision"], "hold")
        self.assertTrue(receipt["fails_check"])
        codes = {item["code"] for item in receipt["findings"]}
        self.assertIn("empty_net_diff", codes)
        self.assertIsNone(receipt["repair"]["empty_net_diff"])
        self.assertNotIn("invent_diff_for_empty_pr", receipt["repair"]["allowed"])

    def test_duplicate_live_claim_credentials_migration_and_destruction_hold(self):
        cases = [
            base(duplicate_of=4),
            base(body="Task-Id: x\nLIVE HOSTINGER VERIFIED\n"),
            base(files=[{"path": ".env", "additions": 1, "deletions": 0}]),
            base(files=[{"path": "database/migrations/x.sql", "additions": 1, "deletions": 0}]),
            base(files=[{"path": "database/schema.sql", "additions": 1, "deletions": 0}]),
            base(diff="+please " + ("rm -rf " + "/") + "\n"),
            base(diff="+mode: " + ("pull_request" + "_target") + "\n"),
            base(diff='+LEQUTIS_HERMES_ROUTE="live"\n'),
        ]
        expected = [
            "duplicate",
            "unverified_completion_claim",
            "credentials",
            "production_migration",
            "production_migration",
            "destructive",
            "unverified_infrastructure",
            "unverified_infrastructure",
        ]
        for report, code in zip(cases, expected):
            receipt = pr_gate.assess(report, for_merge=True)
            self.assertEqual(receipt["decision"], "hold", code)
            self.assertIn(code, {item["code"] for item in receipt["findings"]})
            self.assertTrue(receipt["fails_check"], code)

    def test_gate_policy_change_does_not_auto_merge_and_does_not_fail_the_check(self):
        receipt = pr_gate.assess(
            base(files=[{"path": "core/pr_gate.py", "additions": 10, "deletions": 1}]),
            for_merge=True,
        )
        self.assertEqual(receipt["decision"], "hold")
        self.assertFalse(receipt["fails_check"])
        self.assertIn("gate_policy_change", {item["code"] for item in receipt["findings"]})

    def test_secret_material_in_an_added_line_blocks_merge(self):
        token = "ghp_" + ("a" * 20)
        receipt = pr_gate.assess(base(diff=f"+token={token}\n"), for_merge=True)
        self.assertIn("credentials", {item["code"] for item in receipt["findings"]})
        self.assertTrue(receipt["fails_check"])

    def test_fork_and_draft_are_held_without_failing_static_checks(self):
        for report in (base(draft=True), base(same_repo=False)):
            receipt = pr_gate.assess(report, for_merge=True)
            self.assertEqual(receipt["decision"], "hold")
            self.assertFalse(receipt["fails_check"])

    def test_check_interpretation_waits_fails_and_ignores_its_own_merge_job(self):
        self.assertEqual(pr_gate.interpret_checks([]), "wait")
        self.assertEqual(
            pr_gate.interpret_checks([{"name": "verify", "state": "SUCCESS", "bucket": "pass"}]),
            "pass",
        )
        self.assertEqual(
            pr_gate.interpret_checks(
                [
                    {"name": "verify", "state": "SUCCESS", "bucket": "pass"},
                    {"name": "merge", "state": "PENDING", "bucket": "pending"},
                ]
            ),
            "pass",
        )
        self.assertEqual(
            pr_gate.interpret_checks(
                [
                    {"name": "verify", "state": "PENDING", "bucket": "pending"},
                ]
            ),
            "wait",
        )
        self.assertEqual(
            pr_gate.interpret_checks(
                [
                    {"name": "verify", "state": "SUCCESS", "bucket": "pass"},
                    {"name": "Vercel", "state": "FAILURE", "bucket": "fail"},
                ]
            ),
            "fail",
        )

    def test_transient_retry_is_bounded_and_real_failures_do_not_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            counter = Path(tmp) / "n"
            script = Path(tmp) / "flaky.py"
            script.write_text(
                textwrap.dedent(
                    """\
                    import pathlib, sys
                    path = pathlib.Path(sys.argv[1])
                    count = int(path.read_text() or "0") if path.exists() else 0
                    count += 1
                    path.write_text(str(count))
                    if count < 2:
                        print("Temporary failure in name resolution")
                        raise SystemExit(1)
                    """
                ),
                encoding="utf-8",
            )
            recovered = pr_gate.run_suite([sys.executable, str(script), str(counter)])
            self.assertTrue(recovered["ok"])
            self.assertEqual(len(recovered["attempts"]), 2)
            self.assertEqual(recovered["attempts"][0]["repair"], "rerun_transient_tests")

            always = Path(tmp) / "always.py"
            always.write_text(
                'print("Temporary failure in name resolution")\nraise SystemExit(1)\n',
                encoding="utf-8",
            )
            stopped = pr_gate.run_suite([sys.executable, str(always)])
            self.assertFalse(stopped["ok"])
            self.assertEqual(len(stopped["attempts"]), pr_gate.REPAIR_MAX_ATTEMPTS)

            real = Path(tmp) / "real.py"
            real.write_text('print("AssertionError: manifest_mismatch")\nraise SystemExit(1)\n', encoding="utf-8")
            once = pr_gate.run_suite([sys.executable, str(real)])
            self.assertFalse(once["ok"])
            self.assertEqual(len(once["attempts"]), 1)
            self.assertIsNone(once["attempts"][0]["repair"])

    def test_duplicate_hash_and_findings_file_match_the_empty_diff_class(self):
        diff = "+same\n"
        others = [{"number": 4, "diff_hash": pr_gate.diff_hash(diff)}]
        self.assertEqual(pr_gate.find_duplicate(diff, others), 4)
        self.assertIsNone(pr_gate.find_duplicate("+other\n", others))
        findings = json.loads((ROOT / "knowledge" / "PR4_GIT22_FINDINGS.json").read_text(encoding="utf-8"))
        self.assertEqual(findings["reported_shape"]["commits"], 6)
        self.assertEqual(findings["reported_shape"]["net_changed_files"], 0)
        self.assertIsNone(findings["recovered_implementation"])
        self.assertIn("zero changed files", findings["why_commits_can_have_zero_files"])

    def test_acceptance_contract_is_loaded_and_a_missing_contract_fails_closed(self):
        acceptance = pr_gate.load_acceptance(ROOT)
        self.assertEqual(acceptance["repair"]["max_attempts"], 2)
        self.assertIn("credentials", acceptance["deny_auto_merge"])

        def missing():
            raise FileNotFoundError("gone")

        original = pr_gate.load_acceptance
        pr_gate.load_acceptance = missing
        try:
            receipt = pr_gate.assess(base(), for_merge=True)
        finally:
            pr_gate.load_acceptance = original
        self.assertTrue(receipt["fails_check"])
        self.assertIn("acceptance_contract_missing", {item["code"] for item in receipt["findings"]})

    def test_wait_for_checks_returns_without_merging_on_timeout(self):
        calls = {"n": 0}

        def fetch():
            calls["n"] += 1
            return [{"name": "verify", "state": "PENDING", "bucket": "pending"}]

        clock = {"t": 0.0}

        def now():
            return clock["t"]

        def sleep(seconds):
            clock["t"] += seconds

        state, _checks = pr_gate.wait_for_checks(fetch, timeout_s=30, sleep_s=15, sleep=sleep, clock=now)
        self.assertEqual(state, "wait")
        self.assertGreaterEqual(calls["n"], 2)

    def test_module_compiles(self):
        proc = subprocess.run(
            [sys.executable, "-m", "py_compile", str(ROOT / "core" / "pr_gate.py")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
