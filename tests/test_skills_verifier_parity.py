#!/usr/bin/env python3
"""Disposable tests: skills lifecycle, independent verifier, access parity, search, schema."""

from __future__ import annotations

import os
import re
import shutil
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
    print("TEST SKILLS: propose → sandbox → enable → retire")
    L = load_L(state)
    sid = L.skill_propose("ping-helper", version="0.1.0", evidence={"via": "test"})
    assert L.skill_list("PROPOSED")
    L.skill_advance(sid, "SANDBOXED")
    L.skill_advance(sid, "ENABLED")
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
    print("  PASS")


def test_access_parity(state: Path) -> None:
    print("TEST PARITY: ACCESS/SOURCES/gates IDs consistent")
    L = load_L(state)
    report = L.access_parity()
    assert report["ok"] is True, report
    assert report["counts"]["gates"] == 12
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
        test_independent_verifier(tmp / "verifier")
        test_access_parity(tmp / "parity")
        test_knowledge_search(tmp / "search")
        test_schema_drift(tmp / "schema")
        print("ALL PASS: skills + verifier + parity + search + schema")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
