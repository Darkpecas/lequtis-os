"""The independent reviewer sees only a diff and acceptance criteria."""
import json
import os
import sys
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations"))

import engineering_gate  # noqa: E402
import independent_reviewer as reviewer  # noqa: E402


class IndependentReviewerTests(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("LEQUTIS_REVIEWER_API_KEY", None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("LEQUTIS_REVIEWER_API_KEY", None)
        else:
            os.environ["LEQUTIS_REVIEWER_API_KEY"] = self._saved

    def test_prompt_rejects_extra_fields_and_drops_the_rest_of_the_body(self):
        body = (
            "SUPER_SECRET_CANARY outside the criteria\n\n"
            "## Acceptance criteria\n"
            "- docs/note.md is added\n"
        )
        criteria = engineering_gate.extract_criteria(body)
        packet = reviewer.build_packet("diff --git a/docs/note.md\n", criteria)
        prompt = reviewer.render_prompt(packet)
        self.assertNotIn("SUPER_SECRET_CANARY", prompt)
        self.assertIn("docs/note.md is added", prompt)
        self.assertIn("diff --git", prompt)
        with self.assertRaises(ValueError):
            reviewer.render_prompt({**packet, "tree": "core/lequtis.py"})

    def test_missing_key_fails_closed_without_calling_the_model(self):
        called = []

        def transport(url, payload, headers):
            called.append(url)
            return {}

        result = reviewer.review("diff --git a/docs/note.md\n+note\n", "- docs/note.md is added\n", transport=transport)
        self.assertEqual(called, [])
        self.assertEqual(result["verdict"], "fail_closed")
        self.assertFalse(result["in_scope"])
        self.assertEqual(result["secret"]["LEQUTIS_REVIEWER_API_KEY"], "absent")
        self.assertIn("LEQUTIS_REVIEWER_API_KEY", result["findings"][0]["summary"])
        self.assertEqual(result["packet_keys"], ["acceptance_criteria", "diff"])

    def test_model_pass_and_invalid_output(self):
        os.environ["LEQUTIS_REVIEWER_API_KEY"] = "reviewer-test-key"

        def transport(url, payload, headers):
            self.assertNotIn("reviewer-test-key", json.dumps(payload))
            self.assertEqual([item["role"] for item in payload["messages"]], ["system", "user"])
            self.assertNotIn("core/lequtis.py", payload["messages"][1]["content"])
            return {"choices": [{"message": {"content": json.dumps({
                "verdict": "pass",
                "in_scope": True,
                "findings": [],
            })}}]}

        result = reviewer.review("+docs only\n", "- The change is docs-only markdown\n", transport=transport)
        self.assertEqual(result["verdict"], "pass")
        self.assertTrue(result["in_scope"])

        def broken(url, payload, headers):
            return {"choices": [{"message": {"content": "not json"}}]}

        failed = reviewer.review("+docs only\n", "- tests pass\n", transport=broken)
        self.assertEqual(failed["verdict"], "fail_closed")
        self.assertNotIn("reviewer-test-key", json.dumps(failed))

    def test_default_provider_is_the_free_gemini_flash_model(self):
        self.assertEqual(reviewer.DEFAULT_MODEL, "gemini-3.8-flash")
        endpoint = reviewer.gemini_endpoint(reviewer.DEFAULT_MODEL)
        self.assertEqual(urllib.parse.urlparse(endpoint).hostname, "generativelanguage.googleapis.com")
        os.environ["LEQUTIS_REVIEWER_API_KEY"] = "gemini-test-key"
        payload = {
            "model": reviewer.DEFAULT_MODEL,
            "messages": reviewer.outbound_messages(
                reviewer.build_packet("+note\n", "- docs/note.md is added\n")
            ),
        }
        body = reviewer.gemini_body(payload)
        encoded = json.dumps(body)
        self.assertNotIn("gemini-test-key", encoded)
        self.assertNotIn("gemini-test-key", endpoint)
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertIn("DIFF:", body["contents"][0]["parts"][0]["text"])
        with self.assertRaises(RuntimeError):
            reviewer.resolve_endpoint(reviewer.DEFAULT_MODEL, "https://api.openai.com/v1/chat/completions")
        os.environ["LEQUTIS_REVIEWER_ALLOW_PAID"] = "1"
        try:
            paid = reviewer.resolve_endpoint(reviewer.DEFAULT_MODEL, "https://api.openai.com/v1/chat/completions")
        finally:
            os.environ.pop("LEQUTIS_REVIEWER_ALLOW_PAID", None)
        self.assertIn("api.openai.com", paid)

    def test_comment_is_not_an_approval(self):
        result = reviewer.review("", "")
        body = reviewer.comment_body(result, "abc")
        self.assertIn("lequtis-independent-review v1", body)
        self.assertIn("not a merge approval", body)
        self.assertNotIn('"event": "APPROVE"', body)


if __name__ == "__main__":
    unittest.main()
