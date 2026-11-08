#!/usr/bin/env python3
"""
Disposable tests for host_preflight exit-code contract (G01 / v1.2.22).

  2 — stdio failure
  3 — stdio OK but host prerequisites absent
  0 — stdio OK and prerequisites present
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONNECTOR = ROOT / "runtime" / "hermes-stdio-connector"
CORE = ROOT / "core"


def _import_preflight():
    sys.path.insert(0, str(CONNECTOR))
    sys.modules.pop("host_preflight", None)
    sys.modules.pop("lequtis_mcp_stdio", None)
    import host_preflight as hp  # noqa: WPS433

    return hp


def test_exit_3_when_db_missing() -> None:
    print("TEST PREFLIGHT: exit 3 when DB missing (stdio OK)")
    hp = _import_preflight()
    state = Path(tempfile.mkdtemp(prefix="lequtis-pf-nodb-"))
    try:
        os.environ["LEQUTIS_ROOT"] = str(ROOT)
        os.environ["LEQUTIS_STATE"] = str(state)
        # No init → no DB. Core exists in ROOT. Hermes optional.
        report = hp.run_preflight(require_hermes=False)
        assert report["stdio"]["ok"] is True, report
        assert report["core"]["ok"] is True
        assert report["db"]["ok"] is False
        assert report["exit_code"] == 3
        assert report["live_host"] is False
    finally:
        shutil.rmtree(state, ignore_errors=True)
    print("  PASS")


def test_exit_0_with_db_without_requiring_hermes() -> None:
    print("TEST PREFLIGHT: exit 0 when core+DB OK (Hermes optional)")
    hp = _import_preflight()
    state = Path(tempfile.mkdtemp(prefix="lequtis-pf-ok-"))
    try:
        os.environ["LEQUTIS_ROOT"] = str(ROOT)
        os.environ["LEQUTIS_STATE"] = str(state)
        sys.path.insert(0, str(CORE))
        sys.modules.pop("lequtis", None)
        import lequtis as L  # noqa: WPS433

        L.ROOT = ROOT
        L.STATE = state
        L.DB = state / "lequtis.db"
        state.mkdir(parents=True, exist_ok=True)
        L.init()

        report = hp.run_preflight(require_hermes=False)
        assert report["stdio"]["ok"] is True, report
        assert report["db"]["ok"] is True, report
        assert report["exit_code"] == 0, report
        assert report["live_host"] is False
    finally:
        shutil.rmtree(state, ignore_errors=True)
    print("  PASS")


def test_exit_3_when_hermes_required_missing() -> None:
    print("TEST PREFLIGHT: exit 3 when Hermes required but missing")
    hp = _import_preflight()
    state = Path(tempfile.mkdtemp(prefix="lequtis-pf-hermes-"))
    try:
        os.environ["LEQUTIS_ROOT"] = str(ROOT)
        os.environ["LEQUTIS_STATE"] = str(state)
        os.environ["LEQUTIS_HERMES_BIN"] = "hermes-definitely-not-installed-xyz"
        sys.path.insert(0, str(CORE))
        sys.modules.pop("lequtis", None)
        import lequtis as L  # noqa: WPS433

        L.ROOT = ROOT
        L.STATE = state
        L.DB = state / "lequtis.db"
        state.mkdir(parents=True, exist_ok=True)
        L.init()

        report = hp.run_preflight(require_hermes=True)
        assert report["stdio"]["ok"] is True
        assert report["hermes"]["ok"] is False
        assert report["exit_code"] == 3
    finally:
        os.environ.pop("LEQUTIS_HERMES_BIN", None)
        shutil.rmtree(state, ignore_errors=True)
    print("  PASS")


def test_nonexistent_core_cannot_claim_live() -> None:
    print("TEST PREFLIGHT: nonexistent core cannot claim live")
    hp = _import_preflight()
    fake_root = Path(tempfile.mkdtemp(prefix="lequtis-pf-nocore-"))
    state = Path(tempfile.mkdtemp(prefix="lequtis-pf-nocore-state-"))
    try:
        os.environ["LEQUTIS_ROOT"] = str(fake_root)
        os.environ["LEQUTIS_STATE"] = str(state)
        # Stdio adapter still imports from CONNECTOR path; core check uses ROOT.
        report = hp.run_preflight(require_hermes=False)
        assert report["live_host"] is False
        assert report["core"]["ok"] is False
        # Stdio may still handshake (adapter is local); exit must not be 0.
        assert report["exit_code"] in (2, 3)
        assert report["exit_code"] != 0
    finally:
        shutil.rmtree(fake_root, ignore_errors=True)
        shutil.rmtree(state, ignore_errors=True)
    print("  PASS")


def main() -> int:
    test_exit_3_when_db_missing()
    test_exit_0_with_db_without_requiring_hermes()
    test_exit_3_when_hermes_required_missing()
    test_nonexistent_core_cannot_claim_live()
    print()
    print("=== LEQUTIS HOST PREFLIGHT TESTS: ALL PASS ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
