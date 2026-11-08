"""Disposable canonical write tests. Never use the host state."""
import importlib.util
import os
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "runtime/hermes-stdio-connector/canonical_write.py"

def main():
    spec = importlib.util.spec_from_file_location("canonical_write", FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with tempfile.TemporaryDirectory(prefix="lequtis-write-") as td:
        db = sqlite3.connect(Path(td) / "lequtis.db")
        db.executescript("""
        CREATE TABLE tasks(id TEXT PRIMARY KEY,agenda_id TEXT,idempotency_key TEXT UNIQUE NOT NULL,
          title TEXT NOT NULL,action TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL,
          result TEXT,error TEXT,created TEXT NOT NULL,updated TEXT NOT NULL);
        CREATE TABLE memory(id TEXT PRIMARY KEY,kind TEXT NOT NULL,content TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL);
        CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT NULL,ts TEXT NOT NULL,
          event_type TEXT NOT NULL,payload TEXT NOT NULL,previous_hash TEXT NOT NULL,event_hash TEXT NOT NULL);
        """)
        db.close()
        os.environ["LEQUTIS_STATE"] = td
        os.environ.pop("LEQUTIS_CANONICAL_WRITE", None)
        os.environ.pop("LEQUTIS_TRUSTED_LOCAL_TRANSPORT", None)
        kwargs = dict(key="test:write:001", title="harmless receipt", receipt={"outcome": "observed"}, memory="test lesson")
        assert mod.commit_record(**kwargs)["reason"] == "write_disabled"
        os.environ["LEQUTIS_CANONICAL_WRITE"] = "1"
        assert mod.commit_record(**kwargs)["reason"] == "trusted_transport_not_attested"
        os.environ["LEQUTIS_TRUSTED_LOCAL_TRANSPORT"] = "1"
        first = mod.commit_record(**kwargs)
        assert first["ok"] and first["replay"] is False and first["verified"] is False, first
        again = mod.commit_record(**kwargs)
        assert again["ok"] and again["replay"] is True and again["task_id"] == first["task_id"]
        conflict = mod.commit_record(**{**kwargs, "memory": "changed"})
        assert conflict["reason"] == "idempotency_conflict"
        import hashlib
        with sqlite3.connect(Path(td) / "lequtis.db") as db:
            assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM memory").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
            prev, ts, typ, payload, digest = db.execute(
                "SELECT previous_hash,ts,event_type,payload,event_hash FROM events").fetchone()
            assert hashlib.sha256((prev+"|"+ts+"|"+typ+"|"+payload).encode()).hexdigest() == digest
    print("CANONICAL_WRITE_DISPOSABLE_PASS")

if __name__ == "__main__":
    main()
