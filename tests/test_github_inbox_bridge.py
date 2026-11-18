import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("bridge", str(Path(__file__).resolve().parents[1] / "runtime/chatgpt_hermes_route/github_inbox_bridge.py"))
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)

class BridgeTests(unittest.TestCase):
    def test_allowlist_and_marker(self):
        c={"id":123,"user":{"login":"Darkpecas"},"body":"/hermes-intake\\nReview ET source files","created_at":"2026-11-18"}
        self.assertIsNone(bridge.parse_comment(c, "someoneelse"))
        self.assertIsNone(bridge.parse_comment(dict(c, body="Review ET source files"), "Darkpecas"))
        c["body"]="/hermes-intake\nReview ET source files"
        item=bridge.parse_comment(c, "Darkpecas")
        self.assertEqual(item["status"], "awaiting_approval")
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(bridge.write_intake(d,item))
            self.assertFalse(bridge.write_intake(d,item))
            self.assertEqual(json.loads((Path(d)/"github-issue-123.json").read_text())["instruction"],"Review ET source files")
            changed=dict(item,instruction="different")
            with self.assertRaises(RuntimeError):
                bridge.write_intake(d,changed)
    def test_no_directory_creation(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):
                bridge.write_intake(Path(d)/"missing", {"comment_id":1})

if __name__=="__main__":
    unittest.main()
