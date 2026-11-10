"""Fail closed when an existing database does not match this kernel revision."""
import hashlib
import json
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
            self.assertIn("lequtis-os-kernel-4", made.stdout)
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
                ("schema_revision", "lequtis-os-kernel-4"),
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
            self.assertIn("lequtis-os-kernel-4", accepted.stdout)

    def make_kernel3(self, db: Path, *, prior_event: bool = False) -> None:
        con = sqlite3.connect(db)
        con.executescript((ROOT / "tests" / "fixtures" / "schema-lequtis-os-kernel-3.sql").read_text(encoding="utf-8"))
        con.execute(
            "INSERT INTO identity(key,value) VALUES ('schema_revision', 'lequtis-os-kernel-3')"
        )
        if prior_event:
            payload = json.dumps({"marker": "kernel3"}, sort_keys=True)
            ts = "2026-11-10T00:00:00+00:00"
            raw = "GENESIS|" + ts + "|fixture.marker|" + payload
            digest = hashlib.sha256(raw.encode()).hexdigest()
            con.execute(
                """
                INSERT INTO events
                (event_id,ts,event_type,payload,previous_hash,event_hash)
                VALUES (?,?,?,?,?,?)
                """,
                ("fixture-event", ts, "fixture.marker", payload, "GENESIS", digest),
            )
        con.commit()
        con.close()

    def test_kernel3_status_does_not_migrate_or_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel3.db"
            env = os.environ.copy()
            env["LEQUTIS_DB"] = str(db)
            self.make_kernel3(db, prior_event=True)
            before = fingerprint(db)
            refused = subprocess.run(
                [sys.executable, str(KERNEL), "status"],
                env=env, text=True, capture_output=True,
            )
            self.assertEqual(refused.returncode, 3, refused.stdout + refused.stderr)
            self.assertIn("schema guard", refused.stderr)
            self.assertEqual(fingerprint(db), before)
            with sqlite3.connect(db) as con:
                tables = {
                    row[0]
                    for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                revision = con.execute(
                    "SELECT value FROM identity WHERE key='schema_revision'"
                ).fetchone()[0]
            self.assertNotIn("cancellations", tables)
            self.assertEqual(revision, "lequtis-os-kernel-3")

    def test_migrate_kernel3_is_explicit_idempotent_and_chained(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel3.db"
            env = os.environ.copy()
            env["LEQUTIS_DB"] = str(db)
            self.make_kernel3(db, prior_event=True)
            migrated = subprocess.run(
                [sys.executable, str(KERNEL), "migrate"],
                env=env, text=True, capture_output=True,
            )
            self.assertEqual(migrated.returncode, 0, migrated.stderr + migrated.stdout)
            body = json.loads(migrated.stdout)
            self.assertEqual(body["status"], "migrated")
            self.assertEqual(body["schema_revision"], "lequtis-os-kernel-4")
            self.assertEqual(body["from"], "lequtis-os-kernel-3")
            with sqlite3.connect(db) as con:
                revision = con.execute(
                    "SELECT value FROM identity WHERE key='schema_revision'"
                ).fetchone()[0]
                agenda_cols = {row[1] for row in con.execute("PRAGMA table_info(agenda)")}
                execution_cols = {row[1] for row in con.execute("PRAGMA table_info(executions)")}
                events = con.execute(
                    "SELECT event_type FROM events ORDER BY seq"
                ).fetchall()
            self.assertEqual(revision, "lequtis-os-kernel-4")
            self.assertIn("cancelled_at", agenda_cols)
            self.assertIn("cancelled_at", execution_cols)
            self.assertEqual([row[0] for row in events], ["fixture.marker", "schema.migrated"])
            verified = subprocess.run(
                [sys.executable, str(KERNEL), "verify"],
                env=env, text=True, capture_output=True,
            )
            self.assertEqual(verified.returncode, 0, verified.stderr + verified.stdout)
            self.assertTrue(json.loads(verified.stdout)["ok"])
            before = fingerprint(db)
            again = subprocess.run(
                [sys.executable, str(KERNEL), "migrate"],
                env=env, text=True, capture_output=True,
            )
            self.assertEqual(again.returncode, 0, again.stderr + again.stdout)
            self.assertEqual(json.loads(again.stdout)["status"], "current")
            self.assertEqual(fingerprint(db), before)
            with sqlite3.connect(db) as con:
                count = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            self.assertEqual(count, 2)

    def test_partial_kernel3_migration_is_refused_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "partial.db"
            env = os.environ.copy()
            env["LEQUTIS_DB"] = str(db)
            self.make_kernel3(db)
            with sqlite3.connect(db) as con:
                con.execute("ALTER TABLE agenda ADD COLUMN cancelled_at TEXT")
            before = fingerprint(db)
            refused = subprocess.run(
                [sys.executable, str(KERNEL), "migrate"],
                env=env, text=True, capture_output=True,
            )
            self.assertEqual(refused.returncode, 3, refused.stdout + refused.stderr)
            self.assertIn("schema guard", refused.stderr)
            self.assertEqual(fingerprint(db), before)
            with sqlite3.connect(db) as con:
                revision = con.execute(
                    "SELECT value FROM identity WHERE key='schema_revision'"
                ).fetchone()[0]
                tables = {
                    row[0]
                    for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
            self.assertEqual(revision, "lequtis-os-kernel-3")
            self.assertNotIn("cancellations", tables)

    def test_pre_kernel3_database_migrate_is_refused_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "old.db"
            env = os.environ.copy()
            env["LEQUTIS_DB"] = str(db)
            made = subprocess.run(
                [sys.executable, str(UPSTREAM), "init"],
                env=env, text=True, capture_output=True,
            )
            self.assertEqual(made.returncode, 0, made.stderr)
            before = fingerprint(db)
            refused = subprocess.run(
                [sys.executable, str(KERNEL), "migrate"],
                env=env, text=True, capture_output=True,
            )
            self.assertEqual(refused.returncode, 3, refused.stdout + refused.stderr)
            self.assertIn("schema guard", refused.stderr)
            self.assertEqual(fingerprint(db), before)


if __name__ == "__main__":
    unittest.main()
