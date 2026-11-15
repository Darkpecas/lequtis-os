import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class KnowledgeArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lequtis-archive-")
        self.addCleanup(self.temp.cleanup)
        self.original_env = {
            key: os.environ.get(key)
            for key in ("LEQUTIS_ROOT", "LEQUTIS_STATE", "LEQUTIS_DB")
        }
        self.addCleanup(self.restore_env)
        self.base = Path(self.temp.name)
        self.root = self.base / "repo"
        self.core_dir = self.root / "core"
        self.core_dir.mkdir(parents=True)
        source_core = Path(__file__).resolve().parents[1] / "core" / "lequtis.py"
        shutil.copy2(source_core, self.core_dir / "lequtis.py")
        self.state = self.base / "state"
        self.inbox = self.root / "knowledge" / "inbox" / "chat_export"
        self.inbox.mkdir(parents=True)
        os.environ.pop("LEQUTIS_DB", None)
        self.module = self.load_module()

    def restore_env(self):
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def load_module(self):
        os.environ["LEQUTIS_ROOT"] = str(self.root)
        os.environ["LEQUTIS_STATE"] = str(self.state)
        spec = importlib.util.spec_from_file_location(
            "lequtis_under_test_" + str(id(self)), self.core_dir / "lequtis.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_versions_are_retained_idempotently_and_readable_in_fresh_process(self):
        path = self.inbox / "history.md"
        first = b"first export bytes\n"
        path.write_bytes(first)
        self.module.init()

        initial = self.module.ingest_inbox()
        first_hash = hashlib.sha256(first).hexdigest()
        self.assertEqual(initial["indexed"], 1)
        first_blob = self.state / "source_blobs" / first_hash[:2] / (first_hash + ".blob")
        self.assertEqual(first_blob.read_bytes(), first)

        with sqlite3.connect(self.state / "lequtis.db") as db:
            before_repeat = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        repeated = self.module.ingest_inbox()
        with sqlite3.connect(self.state / "lequtis.db") as db:
            after_repeat = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self.assertEqual(repeated["indexed"], 0)
        self.assertEqual(after_repeat, before_repeat)

        second = b"revised export with different content\n"
        path.write_bytes(second)
        updated = self.module.ingest_inbox()
        second_hash = hashlib.sha256(second).hexdigest()
        self.assertEqual(updated["indexed"], 1)
        second_blob = self.state / "source_blobs" / second_hash[:2] / (second_hash + ".blob")
        self.assertEqual(first_blob.read_bytes(), first)
        self.assertEqual(second_blob.read_bytes(), second)

        with sqlite3.connect(self.state / "lequtis.db") as db:
            db.row_factory = sqlite3.Row
            versions = [
                json.loads(row["payload"])
                for row in db.execute(
                    "SELECT payload FROM events WHERE event_type='knowledge.item_indexed' ORDER BY seq"
                )
            ]
        self.assertEqual([item["hash"] for item in versions], [first_hash, second_hash])
        self.assertIsNone(versions[0]["previous_hash"])
        self.assertEqual(versions[1]["previous_hash"], first_hash)
        self.assertTrue(self.module.verify_event_chain()["ok"])
        self.assertTrue(self.module.verify_knowledge_blobs()["ok"])

        child_code = (
            "import importlib.util,json,sys;"
            "spec=importlib.util.spec_from_file_location('fresh',sys.argv[1]);"
            "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
            "print(json.dumps(m.verify_knowledge_blobs(),sort_keys=True))"
        )
        fresh = subprocess.run(
            [sys.executable, "-c", child_code, str(self.core_dir / "lequtis.py")],
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            check=True,
        )
        fresh_report = json.loads(fresh.stdout.strip())
        self.assertTrue(fresh_report["ok"])
        self.assertEqual(fresh_report["checked"], 2)

    def test_blob_tampering_is_reported(self):
        raw = b"tamper check\n"
        (self.inbox / "history.txt").write_bytes(raw)
        self.module.init()
        self.module.ingest_inbox()
        digest = hashlib.sha256(raw).hexdigest()
        blob = self.state / "source_blobs" / digest[:2] / (digest + ".blob")
        blob.write_bytes(b"altered")
        report = self.module.verify_knowledge_blobs()
        self.assertFalse(report["ok"])
        self.assertEqual(report["corrupt"][0]["reason"], "blob_hash_mismatch")

    def test_symlinked_source_file_is_skipped(self):
        outside = self.base / "outside.md"
        outside.write_text("must not be imported", encoding="utf-8")
        link = self.inbox / "linked.md"
        outside_dir = self.base / "outside_dir"
        outside_dir.mkdir()
        (outside_dir / "nested.md").write_text("must also stay outside", encoding="utf-8")
        linked_dir = self.inbox / "linked_dir"
        try:
            link.symlink_to(outside)
            linked_dir.symlink_to(outside_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable on this platform")
        self.module.init()
        result = self.module.ingest_inbox()
        self.assertEqual(result["indexed"], 0)
        self.assertGreaterEqual(result["skipped_unsafe"], 1)
        with sqlite3.connect(self.state / "lequtis.db") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM knowledge_items").fetchone()[0], 0)

    def test_legacy_event_gets_one_backfill_receipt(self):
        raw = b"backfill me\n"
        (self.inbox / "history.txt").write_bytes(raw)
        self.module.init()
        digest = hashlib.sha256(raw).hexdigest()
        ts = self.module.now()
        with self.module.connect() as db:
            db.execute(
                """
                INSERT INTO knowledge_sources
                (id,kind,role,location,status,meta,created,updated)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                ("chat_export", "inbox_drop", "operator_export", str(self.inbox),
                 "indexed", "{}", ts, ts),
            )
            db.execute(
                """
                INSERT INTO knowledge_items
                (id,source_id,path,title,content_hash,excerpt,status,created,updated)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                ("legacy-item", "chat_export", "history.txt", "history", digest,
                 "legacy excerpt", "indexed", ts, ts),
            )
            self.module._append_event(
                db,
                "knowledge.item_indexed",
                {
                    "id": "legacy-item",
                    "source_id": "chat_export",
                    "path": "history.txt",
                    "hash": digest,
                },
            )

        result = self.module.ingest_inbox()
        blob = self.state / "source_blobs" / digest[:2] / (digest + ".blob")
        self.assertEqual(result["indexed"], 1)
        self.assertEqual(blob.read_bytes(), raw)
        self.assertEqual(self._event_count("knowledge.item_blob_backfilled"), 1)
        self.assertEqual(self.module.ingest_inbox()["indexed"], 0)
        self.assertEqual(self._event_count("knowledge.item_blob_backfilled"), 1)
        report = self.module.verify_knowledge_blobs()
        self.assertTrue(report["ok"])
        self.assertEqual(report["legacy_unarchived"], 1)
        self.assertEqual(report["checked"], 1)

    def _event_count(self, event_type):
        with sqlite3.connect(self.state / "lequtis.db") as db:
            return db.execute(
                "SELECT COUNT(*) FROM events WHERE event_type=?", (event_type,)
            ).fetchone()[0]


if __name__ == "__main__":
    unittest.main()
