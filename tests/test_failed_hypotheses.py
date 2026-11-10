"""The failure registry appends and refuses edits, deletions, and truncation."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import failed_hypotheses  # noqa: E402


ENTRY = {
    "id": "F-LOCAL-001",
    "recorded": "2026-11-10",
    "statement": "A disposable local hypothesis used only by this test.",
    "source": "tests/test_failed_hypotheses.py",
}


class FailedHypothesisTests(unittest.TestCase):
    def test_append_load_and_refuse_edit_or_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "FAILED_HYPOTHESES.jsonl"
            self.assertEqual(failed_hypotheses.load(path), [])
            first = failed_hypotheses.append(path, ENTRY)
            second = failed_hypotheses.append(
                path,
                {
                    "id": "F-LOCAL-002",
                    "recorded": "2026-11-10",
                    "statement": "A second disposable hypothesis.",
                    "source": "tests/test_failed_hypotheses.py",
                },
            )
            self.assertEqual(first["prev_hash"], failed_hypotheses.GENESIS)
            self.assertEqual(second["prev_hash"], first["entry_hash"])
            loaded = failed_hypotheses.load(path, expected_tip=second["entry_hash"])
            self.assertEqual([item["id"] for item in loaded], ["F-LOCAL-001", "F-LOCAL-002"])
            before = path.read_bytes()
            with self.assertRaises(failed_hypotheses.RegistryError):
                failed_hypotheses.replace(path, "F-LOCAL-001", ENTRY)
            with self.assertRaises(failed_hypotheses.RegistryError):
                failed_hypotheses.delete(path, "F-LOCAL-001")
            self.assertEqual(path.read_bytes(), before)
            tampered = before.replace(b"disposable local", b"rewritten local")
            with self.assertRaises(failed_hypotheses.RegistryError):
                failed_hypotheses.assert_extension(before, tampered)
            with self.assertRaises(failed_hypotheses.RegistryError):
                failed_hypotheses.parse_registry(tampered)
            shortened = before.splitlines(keepends=True)[0]
            truncated = Path(tmp) / "truncated.jsonl"
            truncated.write_bytes(shortened)
            with self.assertRaises(failed_hypotheses.RegistryError):
                failed_hypotheses.load(truncated, expected_tip=second["entry_hash"])
            with self.assertRaises(failed_hypotheses.RegistryError):
                failed_hypotheses.append(path, ENTRY)
            self.assertEqual(path.read_bytes(), before)

    def test_shipped_registry_has_no_invented_entries(self):
        path = failed_hypotheses.registry_path(ROOT)
        records = failed_hypotheses.load(path)
        self.assertEqual(records, [])
        self.assertEqual(path.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
