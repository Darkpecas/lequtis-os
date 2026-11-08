"""Fail closed when an existing database does not match this kernel revision."""
import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KERNEL = ROOT / "core" / "lequtis.py"
# Byte-for-byte core/lequtis.py from commit dd77615b97872ee25a98ef95b6314ab177252af6.
# Provenance and SHA-256: tests/fixtures/<commit>/PROVENANCE.txt. The test does not run git.
UPSTREAM_COMMIT = "dd77615b97872ee25a98ef95b6314ab177252af6"
UPSTREAM_SHA256 = "0229fe6348d3f10535f70c9f60e2ef983e789cd22baa5acd16d2c294a2ea41cc"
UPSTREAM = ROOT / "tests" / "fixtures" / UPSTREAM_COMMIT / "core" / "lequtis.py"


def fingerprint(path: Path):
    found = {}
    for candidate in sorted(path.parent.glob(path.name + "*")):
        if candidate.is_file() and not candidate.name.endswith("-shm"):
            found[candidate.name] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    return found


class SchemaGuardTests(unittest.TestCase):
    def test_recovered_kernel_database_is_refused_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "old.db"
            env = os.environ.copy()
            env["LEQUTIS_DB"] = str(db)
            self.assertEqual(
                hashlib.sha256(UPSTREAM.read_bytes()).hexdigest(),
                UPSTREAM_SHA256,
                "vendored dd77615 kernel bytes changed",
            )
            made = subprocess.run([sys.executable, str(UPSTREAM), "init"], env=env, text=True, capture_output=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            before = fingerprint(db)
            refused = subprocess.run([sys.executable, str(KERNEL), "status"], env=env, text=True, capture_output=True)
            self.assertEqual(refused.returncode, 3, refused.stdout + refused.stderr)
            self.assertIn("schema guard", refused.stderr)
            self.assertEqual(fingerprint(db), before)

    def test_new_database_records_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "new.db"
            env = os.environ.copy()
            env["LEQUTIS_DB"] = str(db)
            made = subprocess.run([sys.executable, str(KERNEL), "init"], env=env, text=True, capture_output=True)
            self.assertEqual(made.returncode, 0, made.stderr + made.stdout)
            self.assertIn("lequtis-os-kernel-3", made.stdout)
            self.assertIn("LOCAL PROOF, NOT LIVE VPS VERIFIED", made.stdout)

    def test_uncheckpointed_wal_revision_is_accepted_and_original_bytes_stay(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "wal.db"
            env = os.environ.copy()
            env["LEQUTIS_DB"] = str(db)
            base = sqlite3.connect(db)
            base.execute("PRAGMA journal_mode=WAL")
            base.execute(
                "CREATE TABLE identity (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            base.commit()
            base.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            holder = sqlite3.connect(db)
            holder.execute("BEGIN")
            holder.execute("SELECT key FROM identity").fetchall()
            writer = sqlite3.connect(db)
            writer.execute("PRAGMA wal_autocheckpoint=0")
            schema = (ROOT / "database" / "schema.sql").read_text(encoding="utf-8")
            writer.executescript(schema)
            writer.execute(
                "INSERT INTO identity(key,value) VALUES (?,?)",
                ("schema_revision", "lequtis-os-kernel-3"),
            )
            writer.commit()
            writer.close()
            try:
                stale = sqlite3.connect(
                    "file:" + str(db.resolve()) + "?mode=ro&immutable=1", uri=True
                )
                try:
                    stale_tables = {
                        row[0]
                        for row in stale.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                finally:
                    stale.close()
                self.assertNotIn("executions", stale_tables)
                accepted = subprocess.run(
                    [sys.executable, str(KERNEL), "status"],
                    env=env, text=True, capture_output=True,
                )
            finally:
                holder.close()
            self.assertEqual(accepted.returncode, 0, accepted.stderr + accepted.stdout)
            self.assertIn("lequtis-os-kernel-3", accepted.stdout)


if __name__ == "__main__":
    unittest.main()
