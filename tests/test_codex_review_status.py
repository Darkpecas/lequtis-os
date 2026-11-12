"""Codex review status binds to the current head SHA only."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integrations.codex_review_status import status_from_payloads  # noqa: E402

BOT = {"login": "chatgpt-codex-connector[bot]"}


class CodexReviewStatusTests(unittest.TestCase):
    def test_completed_summary_without_findings_is_pass(self):
        sha = "abc123"
        body = (
            '<!-- codex-review-state:v1 {"code_review":{"commit_sha":"%s",'
            '"has_any_findings":false,"status":"completed"}} -->'
        ) % sha
        result = status_from_payloads(
            head_sha=sha,
            issue_comments=[{"user": BOT, "body": body}],
            pull_comments=[],
            reviews=[],
        )
        self.assertEqual(result, "pass")

    def test_old_head_summary_is_ignored(self):
        body = (
            '<!-- codex-review-state:v1 {"code_review":{"commit_sha":"old",'
            '"has_any_findings":false,"status":"completed"}} -->'
        )
        result = status_from_payloads(
            head_sha="new",
            issue_comments=[{"user": BOT, "body": body}],
            pull_comments=[],
            reviews=[],
        )
        self.assertEqual(result, "missing")

    def test_finding_marker_wins(self):
        sha = "abc123"
        result = status_from_payloads(
            head_sha=sha,
            issue_comments=[],
            pull_comments=[
                {
                    "user": BOT,
                    "commit_id": sha,
                    "body": "issue <!-- codex-code-review-finding:v1 -->",
                }
            ],
            reviews=[{"user": BOT, "commit_id": sha}],
        )
        self.assertEqual(result, "findings")


if __name__ == "__main__":
    unittest.main()
