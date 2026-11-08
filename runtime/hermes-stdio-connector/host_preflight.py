#!/usr/bin/env python3
"""
Host preflight for the LeQutis Hermes stdio connector (G01).

Exit codes (System Access Manager v1.2.22 contract):
  0 — stdio handshake OK and host prerequisites present
  2 — stdio failure
  3 — stdio OK but host prerequisites absent (core / DB / Hermes)

Never claims live Hostinger verification. SQLite inspection is read-only
and non-authoritative for production Hostinger/A71 state.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _root() -> Path:
    return Path(os.environ.get("LEQUTIS_ROOT", HERE.parents[1]))


def _stdio_handshake() -> dict:
    sys.path.insert(0, str(HERE))
    import lequtis_mcp_stdio as adapter  # noqa: WPS433

    return adapter.handshake_once()


def _check_core() -> dict:
    core = _root() / "core" / "lequtis.py"
    return {"ok": core.is_file(), "path": str(core)}


def _check_db() -> dict:
    state = Path(os.environ.get("LEQUTIS_STATE", _root() / "state"))
    db = state / "lequtis.db"
    if not db.is_file():
        return {"ok": False, "path": str(db), "reason": "db_missing"}
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            n = con.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error as exc:
        return {"ok": False, "path": str(db), "reason": f"db_error:{exc}"}
    return {
        "ok": True,
        "path": str(db),
        "sqlite_master_rows": n,
        "note": "read-only inspection; not authoritative Hostinger/A71 proof",
    }


def _check_hermes() -> dict:
    binary = os.environ.get("LEQUTIS_HERMES_BIN", "hermes")
    path = shutil.which(binary)
    return {
        "ok": path is not None,
        "binary": binary,
        "path": path,
        "note": "presence only — not a live Hostinger probe receipt",
    }


def run_preflight(*, require_hermes: bool = True) -> dict:
    stdio = _stdio_handshake()
    core = _check_core()
    db = _check_db()
    hermes = _check_hermes()

    host_ok = core["ok"] and db["ok"] and (hermes["ok"] if require_hermes else True)
    if not stdio.get("ok"):
        exit_code = 2
    elif not host_ok:
        exit_code = 3
    else:
        exit_code = 0

    return {
        "ok": exit_code == 0,
        "exit_code": exit_code,
        "live_host": False,
        "stdio": stdio,
        "core": core,
        "db": db,
        "hermes": hermes,
        "require_hermes": require_hermes,
        "root": str(_root()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LeQutis Hermes stdio host preflight")
    parser.add_argument(
        "--allow-missing-hermes",
        action="store_true",
        help="Treat Hermes binary as optional (still exit 3 if core/DB missing)",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    args = parser.parse_args(argv)

    report = run_preflight(require_hermes=not args.allow_missing_hermes)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"preflight exit={report['exit_code']} "
            f"stdio_ok={report['stdio'].get('ok')} "
            f"core_ok={report['core']['ok']} "
            f"db_ok={report['db']['ok']} "
            f"hermes_ok={report['hermes']['ok']} "
            f"live_host=False"
        )
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
