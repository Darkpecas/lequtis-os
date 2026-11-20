"""Exercise real Git changes in a disposable repository."""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "runtime" / "evolution_swarm.py"
spec = importlib.util.spec_from_file_location("evolution_swarm", MODULE)
swarm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(swarm)


class EvolutionScanTest(unittest.TestCase):
    def test_committed_dirty_untracked_and_invalid_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args):
                return subprocess.run(["git", "-C", str(root), *args], check=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            git("init", "-q")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            (root / "core").mkdir()
            (root / "core" / "worker.py").write_text("original")
            git("add", ".")
            git("commit", "-qm", "baseline")
            base = git("rev-parse", "HEAD").stdout.decode().strip()
            self.assertEqual(swarm.scan(root, base)["status"], "no_file_changes_detected")
            (root / "core" / "worker.py").write_text("changed")
            git("add", ".")
            git("commit", "-qm", "change")
            (root / "core" / "worker.py").write_text("dirty")
            (root / "new file").write_text("untracked")
            report = swarm.scan(root, base)
            by_path = {x["path"]: x for x in report["findings"]}
            self.assertEqual(by_path["core/worker.py"]["scopes"], ["committed", "worktree"])
            self.assertIn("kernel_and_state", by_path["core/worker.py"]["review_areas"])
            self.assertEqual(by_path["new file"]["scopes"], ["untracked"])
            self.assertEqual(report["verdict"], "not_assessed")
            with self.assertRaises(subprocess.CalledProcessError):
                swarm.scan(root, "nonexistent-baseline")


if __name__ == "__main__":
    unittest.main()
