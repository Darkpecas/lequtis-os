#!/usr/bin/env python3
"""
Disposable integration tests for the LeQutis autonomous loop.

TEST A — happy path: goal -> task -> execution -> observation -> evaluation
          -> learning -> memory -> agenda update -> audit events
TEST B — failure: captured, state updated, audit event, recoverable agenda
TEST C — restart: state survives, unfinished detectable, no duplicate completion
TEST D — cryptographic event chain remains valid

Never touches production state: uses a temp LEQUTIS_STATE directory.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEQUTIS = ROOT / "core" / "lequtis.py"


def run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(LEQUTIS), *args]
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def must_ok(proc: subprocess.CompletedProcess[str], label: str) -> str:
    if proc.returncode != 0:
        raise AssertionError(
            f"{label} failed rc={proc.returncode}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc.stdout


def load_module(state_dir: Path):
    """Import lequtis against a disposable state directory."""
    os.environ["LEQUTIS_ROOT"] = str(ROOT)
    os.environ["LEQUTIS_STATE"] = str(state_dir)
    # Fresh import each time
    sys.modules.pop("lequtis", None)
    sys.path.insert(0, str(ROOT / "core"))
    import lequtis as L  # noqa: WPS433

    # Re-bind paths in case module was cached oddly
    L.ROOT = ROOT
    L.STATE = state_dir
    L.DB = state_dir / "lequtis.db"
    state_dir.mkdir(parents=True, exist_ok=True)
    L.init()
    return L


def test_a_happy_path(state: Path) -> None:
    print("TEST A: happy path autonomous loop")
    L = load_module(state)
    gid = L.add_goal("Inspect kernel status via autonomous loop", priority=50)
    result = L.run_loop(correlation_id="test-a-corr")
    assert result["status"] == "completed", result
    assert result["evidence"]["phases"]["NOTICE"]["goals"] >= 1
    assert result["evidence"]["phases"]["ACT"]["ok"] is True
    assert result["evidence"]["phases"]["EVALUATE"]["accepted"] is True
    assert result["evidence"]["phases"]["REMEMBER"]["memory_id"]
    assert result["evidence"]["phases"]["UPDATE_AGENDA"]["status"] == "done"
    assert result["event_chain"]["ok"] is True

    with L.connect() as db:
        status = db.execute(
            "SELECT status FROM agenda WHERE id=?", (gid,)
        ).fetchone()[0]
        events = db.execute(
            "SELECT event_type FROM events ORDER BY seq"
        ).fetchall()
    assert status == "done"
    types = [r[0] for r in events]
    for required in (
        "loop.started",
        "loop.notice",
        "loop.think",
        "loop.choose",
        "task.completed",
        "loop.observe",
        "loop.evaluate",
        "loop.learn",
        "loop.remember",
        "loop.agenda",
        "loop.completed",
    ):
        assert required in types, f"missing event {required} in {types}"
    print("  PASS")


def test_b_failure_recovery(state: Path) -> None:
    print("TEST B: failure capture and recoverable agenda")
    L = load_module(state)
    gid = L.add_goal("Force deliberate failure for recovery drill", priority=80)
    result = L.run_loop(correlation_id="test-b-corr")
    assert result["status"] == "failed", result
    assert result["evidence"]["phases"]["ACT"]["ok"] is False
    assert result["evidence"]["phases"]["EVALUATE"]["accepted"] is False
    assert result["evidence"]["phases"]["UPDATE_AGENDA"].get("recovery_goal")

    unfinished = L.unfinished_work()
    assert any(t["status"] == "failed" for t in unfinished), unfinished

    with L.connect() as db:
        goal_status = db.execute(
            "SELECT status FROM agenda WHERE id=?", (gid,)
        ).fetchone()[0]
        recovery = db.execute(
            """
            SELECT COUNT(*) FROM agenda
            WHERE status='open' AND title LIKE 'Recover failed task%'
            """
        ).fetchone()[0]
        failed_events = db.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='task.failed'"
        ).fetchone()[0]
    assert goal_status == "open"
    assert recovery >= 1
    assert failed_events >= 1
    assert L.verify_event_chain()["ok"] is True
    print("  PASS")


def test_c_restart_idempotency(state: Path) -> None:
    print("TEST C: restart persistence and idempotent replay")
    L = load_module(state)
    L.add_goal("Store memory note from loop", priority=40)
    first = L.run_loop(correlation_id="test-c-first")
    assert first["status"] == "completed"
    task_id = first["evidence"]["phases"]["ACT"]["task_id"]
    tip_after_first = L.verify_event_chain()["tip"]

    # Simulate process restart: re-import module against same DB.
    L2 = load_module(state)
    assert L2.verify_event_chain()["ok"] is True
    assert L2.verify_event_chain()["tip"] == tip_after_first

    # Replay same goal action via explicit choice with same idempotency key.
    with L2.connect() as db:
        row = db.execute(
            "SELECT idempotency_key, action, agenda_id, title FROM tasks WHERE id=?",
            (task_id,),
        ).fetchone()
    choice = {
        "kind": "goal",
        "task_id": task_id,
        "action": row["action"],
        "agenda_id": row["agenda_id"],
        "reason": "replay",
        "idempotency_key": row["idempotency_key"],
        "payload": {},
        "title": row["title"],
    }
    replay = L2.act(choice)
    assert replay["duplicate"] is True
    assert replay["ok"] is True

    with L2.connect() as db:
        completed = db.execute(
            "SELECT COUNT(*) FROM tasks WHERE idempotency_key=? AND status='completed'",
            (row["idempotency_key"],),
        ).fetchone()[0]
    assert completed == 1, "duplicate completion must not create a second row"
    assert L2.verify_event_chain()["ok"] is True

    # Unfinished work after a failed task must be detectable after restart.
    L2.add_goal("Force deliberate failure for recovery drill", priority=90)
    L2.run_loop(correlation_id="test-c-fail")
    L3 = load_module(state)
    unfinished = L3.unfinished_work()
    assert any(t["status"] == "failed" for t in unfinished), unfinished
    print("  PASS")


def test_d_event_chain(state: Path) -> None:
    print("TEST D: cryptographic event chain integrity")
    L = load_module(state)
    L.heartbeat()
    L.remember("chain integrity probe")
    L.add_goal("chain goal")
    L.run_loop(correlation_id="test-d-corr")
    verify = L.verify_event_chain()
    assert verify["ok"] is True
    assert verify["count"] > 5

    # Tamper then detect.
    with L.connect() as db:
        db.execute(
            "UPDATE events SET payload='{\"tampered\":true}' WHERE seq=1"
        )
    broken = L.verify_event_chain()
    assert broken["ok"] is False
    assert broken.get("reason") in (
        "event_hash_mismatch",
        "previous_hash_mismatch",
    )
    print("  PASS")


def test_cli_disposable(state: Path) -> None:
    print("TEST CLI: disposable subprocess loop")
    env = os.environ.copy()
    env["LEQUTIS_ROOT"] = str(ROOT)
    env["LEQUTIS_STATE"] = str(state)
    must_ok(run(env, "init"), "init")
    must_ok(run(env, "goal", "Inspect kernel status via autonomous loop"), "goal")
    out = must_ok(run(env, "loop"), "loop")
    data = json.loads(out)
    assert data["status"] == "completed"
    verify = json.loads(must_ok(run(env, "verify"), "verify"))
    assert verify["ok"] is True
    print("  PASS")


def test_e_knowledge_sources(state: Path) -> None:
    print("TEST E: knowledge source registry + local assimilate")
    L = load_module(state)
    fixture_root = state / "repo_fixture"
    (fixture_root / "knowledge").mkdir(parents=True, exist_ok=True)
    (fixture_root / "docs" / "evidence").mkdir(parents=True, exist_ok=True)
    (fixture_root / "knowledge" / "SOURCES.json").write_text(
        json.dumps(
            {
                "version": 1,
                "canonical_github": "https://github.com/Darkpecas/lequtis-os",
                "sources": [
                    {
                        "id": "github_lequtis_os",
                        "kind": "code_repository",
                        "role": "canonical_runtime_home",
                        "location": "https://github.com/Darkpecas/lequtis-os",
                        "status": "declared",
                    }
                ],
                "local_evidence_feed": [],
            }
        ),
        encoding="utf-8",
    )
    (fixture_root / "docs" / "evidence" / "test-evidence.md").write_text(
        "Disposable evidence fixture for autonomous loop tests.\n",
        encoding="utf-8",
    )
    L.ROOT = fixture_root
    reg = L.register_sources_from_manifest()
    assert reg["canonical_github"] == "https://github.com/Darkpecas/lequtis-os"
    ids = {s["id"] for s in reg["sources"]}
    assert "github_lequtis_os" in ids
    result = L.assimilate_local_evidence()
    assert result["ok"] is True
    assert result["indexed"] >= 1
    assert L.verify_event_chain()["ok"] is True
    print("  PASS")


def test_f_inbox_gates(state: Path) -> None:
    print("TEST F: inbox ingest + LIVE LOOP gate seeding")
    L = load_module(state)
    fixture_root = state / "repo_fixture"
    knowledge = fixture_root / "knowledge"
    knowledge.mkdir(parents=True, exist_ok=True)
    for name in ("ACCESS_MANIFEST.yaml", "ACCESS_MATRIX.yaml", "LIVE_LOOP_GATES.json"):
        shutil.copy2(ROOT / "knowledge" / name, knowledge / name)
    L.ROOT = fixture_root
    inbox = knowledge / "inbox" / "obsidian"
    inbox.mkdir(parents=True, exist_ok=True)
    sample = inbox / "sop-test.md"
    sample.write_text("# SOP test\nHeartbeat before loop.\n", encoding="utf-8")
    try:
        ing = L.ingest_inbox()
        assert ing["ok"] is True
        assert ing["by_source"].get("obsidian", 0) >= 1
        report = L.gates_report()
        assert report["ledger_status"] == "OPEN"
        g01 = next(g for g in report["gates"] if g["id"] == "G01_recover_stdio_connector")
        assert g01["status"] == "VERIFIED_DISPOSABLE"
        # Still-open Hermes gates must remain seedable.
        assert any(
            g["status"] in ("OPEN", "PARTIAL") and g["id"].startswith("G0")
            for g in report["gates"]
        )
        seeded = L.seed_open_gates_to_agenda()
        assert len(seeded["created"]) >= 1
        assert not any(t.get("gate") == "G01_recover_stdio_connector" for t in seeded["created"])
        again = L.seed_open_gates_to_agenda()
        assert again["created"] == []
        assert L.verify_event_chain()["ok"] is True
    finally:
        sample.unlink(missing_ok=True)
    print("  PASS")


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="lequtis-test-"))
    try:
        test_a_happy_path(base / "a")
        test_b_failure_recovery(base / "b")
        test_c_restart_idempotency(base / "c")
        test_d_event_chain(base / "d")
        test_cli_disposable(base / "cli")
        test_e_knowledge_sources(base / "e")
        test_f_inbox_gates(base / "f")
        print()
        print("=== LEQUTIS AUTONOMOUS LOOP TESTS: ALL PASS ===")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
