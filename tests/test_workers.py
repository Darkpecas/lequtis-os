#!/usr/bin/env python3
"""Disposable tests: replaceable THINK/CHOOSE workers; ACT stays registered-safe."""

from __future__ import annotations

import json
import os
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
    os.environ.pop("LEQUTIS_WORKER_SCRIPT", None)
    sys.path.insert(0, str(CORE))
    sys.modules.pop("lequtis", None)
    sys.modules.pop("workers", None)
    import lequtis as L  # noqa: WPS433

    L.ROOT = ROOT
    L.STATE = state
    L.DB = state / "lequtis.db"
    state.mkdir(parents=True, exist_ok=True)
    L.init()
    return L


def test_deterministic_default(state: Path) -> None:
    print("TEST WORKERS: deterministic default loop still completes")
    L = load_L(state)
    L.add_goal("Inspect kernel status via autonomous loop", priority=50)
    result = L.run_loop(correlation_id="worker-det")
    assert result["status"] == "completed", result
    assert result["evidence"]["phases"]["ACT"]["ok"] is True
    print("  PASS")


def test_script_worker_think_choose(state: Path) -> None:
    print("TEST WORKERS: script worker influences THINK/CHOOSE")
    L = load_L(state)
    script = state / "worker_script.py"
    script.write_text(
        """#!/usr/bin/env python3
import json, sys
req = json.load(sys.stdin)
if req["phase"] == "think":
    goals = req["noticed"].get("open_goals") or []
    g = goals[0] if goals else {"id": None, "title": "x"}
    print(json.dumps({
      "candidates": [{
        "kind": "goal",
        "action": "store_note",
        "agenda_id": g["id"],
        "title": g.get("title"),
        "reason": "script_prefers_note",
        "idempotency_key": f"goal:{g['id']}:store_note",
        "payload": {"note": "from-script-worker"}
      }]
    }))
elif req["phase"] == "choose":
    print(json.dumps({"choice": req["candidates"][0]}))
""",
        encoding="utf-8",
    )
    os.environ["LEQUTIS_WORKER"] = "script"
    os.environ["LEQUTIS_WORKER_SCRIPT"] = str(script)
    sys.modules.pop("workers", None)
    L.add_goal("Remember this note about workers", priority=50)
    result = L.run_loop(correlation_id="worker-script")
    assert result["status"] == "completed", result
    assert result["evidence"]["phases"]["CHOOSE"]["action"] == "store_note"
    # Ensure ACT stayed in registry (store_note).
    assert result["evidence"]["phases"]["ACT"]["ok"] is True
    print("  PASS")


def test_unsafe_worker_proposal_rejected(state: Path) -> None:
    print("TEST WORKERS: unsafe actions rejected → deterministic fallback")
    L = load_L(state)
    script = state / "bad_worker.py"
    script.write_text(
        """#!/usr/bin/env python3
import json, sys
req = json.load(sys.stdin)
if req["phase"] == "think":
    print(json.dumps({"candidates":[{
      "kind":"goal","action":"rm_rf_root","agenda_id":None,
      "idempotency_key":"evil","payload":{}
    }]}))
else:
    print(json.dumps({"choice": req["candidates"][0]}))
""",
        encoding="utf-8",
    )
    os.environ["LEQUTIS_WORKER"] = "script"
    os.environ["LEQUTIS_WORKER_SCRIPT"] = str(script)
    sys.modules.pop("workers", None)
    L.add_goal("Inspect kernel status via autonomous loop", priority=50)
    result = L.run_loop(correlation_id="worker-safe")
    assert result["status"] == "completed", result
    # Must not have executed unknown action.
    assert result["evidence"]["phases"]["CHOOSE"]["action"] in (
        "inspect_status",
        "store_note",
        "ping",
        "deliberate_fail",
    )
    print("  PASS")


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="lequtis-workers-"))
    try:
        test_deterministic_default(base / "a")
        test_script_worker_think_choose(base / "b")
        test_unsafe_worker_proposal_rejected(base / "c")
        print()
        print("=== LEQUTIS WORKER TESTS: ALL PASS ===")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
