#!/usr/bin/env python3
"""Disposable tests: skills lifecycle, independent verifier, access parity, search, schema."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"


def load_L(state: Path):
    os.environ["LEQUTIS_ROOT"] = str(ROOT)
    os.environ["LEQUTIS_STATE"] = str(state)
    os.environ.pop("LEQUTIS_WORKER", None)
    sys.path.insert(0, str(CORE))
    for mod in ("lequtis", "workers", "skills", "verifier", "access_parity"):
        sys.modules.pop(mod, None)
    import lequtis as L  # noqa: WPS433

    L.ROOT = ROOT
    L.STATE = state
    L.DB = state / "lequtis.db"
    state.mkdir(parents=True, exist_ok=True)
    L.init()
    return L


def test_skills_lifecycle(state: Path) -> None:
    print("TEST SKILLS: evidence-gated sandbox → admission → retire")
    L = load_L(state)
    sid = L.skill_propose(
        "ping-helper", version="0.1.0", evidence={"via": "test"}
    )
    assert L.skill_list("PROPOSED")

    def must_reject(call, label: str) -> None:
        try:
            call()
            raise AssertionError(f"{label} must be rejected")
        except ValueError:
            pass

    def status() -> str:
        return L.skill_list()[0]["status"]

    must_reject(lambda: L.skill_advance(sid, "SANDBOXED"), "missing test receipt")
    assert status() == "PROPOSED"

    test_receipt = {
        "status": "PASS",
        "skill_id": sid,
        "skill_version": "0.1.0",
        "test_run_id": "disposable-test-001",
        "isolated": True,
        "artifact_sha256": "a" * 64,
    }
    failed_receipt = {**test_receipt, "status": "FAIL"}
    must_reject(
        lambda: L.skill_advance(sid, "SANDBOXED", {"test_receipt": failed_receipt}),
        "failed test",
    )
    wrong_candidate = {**test_receipt, "skill_version": "9.9.9"}
    must_reject(
        lambda: L.skill_advance(sid, "SANDBOXED", {"test_receipt": wrong_candidate}),
        "wrong candidate version",
    )
    assert status() == "PROPOSED"

    L.skill_advance(sid, "SANDBOXED", {"test_receipt": test_receipt})
    assert status() == "SANDBOXED"
    must_reject(lambda: L.skill_advance(sid, "ENABLED"), "missing admission receipt")

    receipt_hash = hashlib.sha256(
        json.dumps(test_receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    admission_receipt = {
        "decision": "APPROVED",
        "skill_id": sid,
        "skill_version": "0.1.0",
        "review_id": "review-001",
        "reviewer_id": "lequtis-verifier-01",
        "test_receipt_sha256": receipt_hash,
    }
    bad_admission = {**admission_receipt, "test_receipt_sha256": "0" * 64}
    must_reject(
        lambda: L.skill_advance(sid, "ENABLED", {"admission_receipt": bad_admission}),
        "unbound admission receipt",
    )
    replaced_test = {**test_receipt, "test_run_id": "different-run"}
    must_reject(
        lambda: L.skill_advance(
            sid,
            "ENABLED",
            {"test_receipt": replaced_test, "admission_receipt": admission_receipt},
        ),
        "replacement test receipt",
    )
    assert status() == "SANDBOXED"

    L.skill_advance(sid, "ENABLED", {"admission_receipt": admission_receipt})
    assert status() == "ENABLED"
    must_reject(
        lambda: L.skill_advance(
            sid,
            "RETIRED",
            {"test_receipt": {**test_receipt, "test_run_id": "tampered"}},
        ),
        "receipt tampering during retirement",
    )
    assert status() == "ENABLED"
    L.skill_advance(sid, "RETIRED")
    try:
        L.skill_advance(sid, "ENABLED")
        raise AssertionError("retired skills must not re-enable")
    except ValueError:
        pass
    assert L.status()["skills"] == 1
    print("  PASS")


def test_independent_verifier(state: Path) -> None:
    print("TEST VERIFIER: rejects self-report; requires artifacts")
    L = load_L(state)
    L.add_goal("Inspect kernel status via autonomous loop", priority=50)
    result = L.run_loop(correlation_id="verify-ind-1")
    assert result["status"] == "completed", result
    report = L.verify_independent("verify-ind-1")
    assert report["ok"] is True, report
    assert report["rejects_self_report"] is True
    # Tamper evidence JSON alone must not flip ok if artifacts still match —
    # but deleting the task row must fail.
    with L.connect() as db:
        row = db.execute(
            "SELECT task_id FROM loop_runs WHERE correlation_id=?",
            ("verify-ind-1",),
        ).fetchone()
        tid = row["task_id"]
        db.execute("DELETE FROM tasks WHERE id=?", (tid,))
    bad = L.verify_independent("verify-ind-1")
    assert bad["ok"] is False, bad

    with L.connect() as db:
        db.execute(
            "INSERT INTO loop_runs (id,correlation_id,phase,status,task_id,evidence,created,updated) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("run-empty", "verify-empty-run", "NOTICE", "running", None, "{}",
             "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
    empty = L.verify_independent("verify-empty-run")
    assert empty["ok"] is False, empty

    # A completed task plus only start/end events is still not a full loop.
    L.add_goal("Create a task for forged receipt check", priority=50)
    good = L.run_loop(correlation_id="verify-good-run")
    assert good["status"] == "completed", good
    task_id = good["evidence"]["phases"]["ACT"]["task_id"]
    with L.connect() as db:
        db.execute(
            "INSERT INTO loop_runs (id,correlation_id,phase,status,task_id,evidence,created,updated) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("run-forged", "verify-forged-run", "UPDATE_AGENDA", "completed",
             task_id, '{"phases":{"ACT":{"ok":true}}}',
             "2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z"),
        )
    L.event("loop.started", {
        "run_id": "run-forged", "correlation_id": "verify-forged-run"
    })
    L.event("loop.completed", {
        "run_id": "run-forged", "correlation_id": "verify-forged-run",
        "status": "completed",
    })
    forged = L.verify_independent("verify-forged-run")
    assert forged["ok"] is False, forged
    print("  PASS")


def test_skill_cli_receipt(state: Path) -> None:
    print("TEST SKILLS CLI: accepts structured promotion evidence")
    L = load_L(state)
    sid = L.skill_propose("cli-helper", version="0.1.0")
    receipt = {
        "status": "PASS",
        "skill_id": sid,
        "skill_version": "0.1.0",
        "test_run_id": "cli-test-001",
        "isolated": True,
        "artifact_sha256": "b" * 64,
    }
    env = os.environ.copy()
    env["LEQUTIS_ROOT"] = str(ROOT)
    env["LEQUTIS_STATE"] = str(state)
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "core" / "lequtis.py"),
            "skills",
            "advance",
            sid,
            "SANDBOXED",
            json.dumps({"test_receipt": receipt}),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert L.skill_list()[0]["status"] == "SANDBOXED"
    print("  PASS")


def test_access_parity(state: Path) -> None:
    print("TEST PARITY: ACCESS/SOURCES/gates IDs consistent")
    L = load_L(state)
    report = L.access_parity()
    assert report["ok"] is True, report
    # G01–G12 plus G13_github_pr_engineering_gate
    assert report["counts"]["gates"] == 13, report
    assert "G13_github_pr_engineering_gate" in report["gate_ids"]
    print("  PASS")


def test_knowledge_search(state: Path) -> None:
    print("TEST SEARCH: knowledge + memory substring")
    L = load_L(state)
    L.assimilate_local_evidence()
    L.remember("unique-search-token-lequtis-xyz", kind="semantic")
    hit = L.search_knowledge("unique-search-token-lequtis-xyz")
    assert hit["memory"], hit
    # Broader assimilate may or may not find 'LeQutis' depending on evidence pack.
    broader = L.search_knowledge("LeQutis")
    assert isinstance(broader["knowledge_items"], list)
    print("  PASS")


def _tables_from_schema_sql(text: str) -> dict[str, set[str]]:
    tables: dict[str, set[str]] = {}
    for match in re.finditer(
        r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\);",
        text,
        flags=re.S | re.I,
    ):
        name = match.group(1)
        body = match.group(2)
        cols: set[str] = set()
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            if not line or line.startswith("--"):
                continue
            upper = line.upper()
            if upper.startswith("FOREIGN KEY") or upper.startswith("UNIQUE") or upper.startswith("PRIMARY"):
                continue
            col = line.split()[0].strip("`\"")
            cols.add(col)
        tables[name] = cols
    return tables


def test_schema_drift(state: Path) -> None:
    print("TEST SCHEMA: schema.sql matches init() tables/columns")
    L = load_L(state)
    schema_text = (ROOT / "database" / "schema.sql").read_text(encoding="utf-8")
    expected = _tables_from_schema_sql(schema_text)
    assert expected, "schema.sql produced no tables"
    with L.connect() as db:
        live_tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        assert set(expected) <= live_tables, (set(expected) - live_tables)
        for table, cols in expected.items():
            live_cols = {
                row[1]
                for row in db.execute(f"PRAGMA table_info({table})").fetchall()
            }
            missing = cols - live_cols
            assert not missing, f"{table} missing columns: {missing}"
    print("  PASS")


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="lequtis-svp-"))
    try:
        test_skills_lifecycle(tmp / "skills")
        test_skill_cli_receipt(tmp / "skill-cli")
        test_independent_verifier(tmp / "verifier")
        test_access_parity(tmp / "parity")
        test_knowledge_search(tmp / "search")
        test_schema_drift(tmp / "schema")
        print("ALL PASS: skill receipts + verifier + parity + search + schema")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
