"""Seal tracked kernel files, refuse overwrite, and verify an isolated clone."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
sys.path.insert(0, str(CORE))

import golden_master  # noqa: E402


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


def make_kernel_repo(path: Path) -> None:
    path.mkdir()
    (path / "core").mkdir()
    (path / "database").mkdir()
    (path / "core" / "sample.py").write_text("print('kernel')\n", encoding="utf-8")
    (path / "database" / "schema.sql").write_text("PRAGMA journal_mode = WAL;\n", encoding="utf-8")
    (path / "notes.txt").write_text("not a kernel file\n", encoding="utf-8")
    git(path, "init", "-b", "main")
    git(path, "add", "core", "database", "notes.txt")
    git(path, "commit", "-m", "kernel fixture")


class GoldenMasterTests(unittest.TestCase):
    def test_seal_verify_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            origin = Path(tmp) / "origin"
            make_kernel_repo(origin)
            out = origin / "GOLDEN_MASTER.json"
            sealed = golden_master.seal(origin, out)
            self.assertEqual(sealed["schema"], golden_master.SCHEMA)
            self.assertEqual(len(sealed["files"]), 2)
            self.assertTrue(out.is_file())
            self.assertEqual(out.stat().st_mode & 0o777, 0o444)
            first = out.read_bytes()
            checked = golden_master.verify(origin, out)
            self.assertTrue(checked["ok"], checked)
            os.chmod(out, 0o644)
            with self.assertRaises(golden_master.GoldenMasterError):
                golden_master.seal(origin, out)
            self.assertEqual(out.read_bytes(), first)

    def test_tampered_clone_fails_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            origin = Path(tmp) / "origin"
            make_kernel_repo(origin)
            out = origin / "GOLDEN_MASTER.json"
            golden_master.seal(origin, out)
            (origin / "core" / "sample.py").write_text("print('changed')\n", encoding="utf-8")
            checked = golden_master.verify(origin, out)
            self.assertFalse(checked["ok"])
            self.assertEqual(checked["reason"], "manifest_mismatch")

    def test_seal_uses_an_isolated_clone_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            origin = Path(tmp) / "origin"
            make_kernel_repo(origin)
            clone = Path(tmp) / "clone"
            result = subprocess.run(
                ["git", "clone", "--no-local", str(origin), str(clone)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            out = clone / "GOLDEN_MASTER.json"
            sealed = golden_master.seal(clone, out)
            self.assertTrue(golden_master.verify(clone, out)["ok"])
            self.assertFalse((origin / "GOLDEN_MASTER.json").exists())
            self.assertEqual(
                {item["path"] for item in sealed["files"]},
                {"core/sample.py", "database/schema.sql"},
            )
            shutil.rmtree(clone)

    def test_committed_seal_matches_this_worktree(self):
        seal_path = ROOT / "GOLDEN_MASTER.json"
        self.assertTrue(seal_path.is_file(), "GOLDEN_MASTER.json is missing")
        checked = golden_master.verify(ROOT, seal_path)
        self.assertTrue(checked["ok"], checked)
        document = json.loads(seal_path.read_text(encoding="utf-8"))
        self.assertNotIn("GOLDEN_MASTER.json", {item["path"] for item in document["files"]})


if __name__ == "__main__":
    unittest.main()
