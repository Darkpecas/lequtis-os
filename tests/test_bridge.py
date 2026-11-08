#!/usr/bin/env python3
"""
Disposable unit tests for the Hermes stdio MCP adapter (G01).

Covers: status, valid/tampered chain, disabled query, initialize/tools list,
absence of synthetic live-host proof. Never touches production state.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONNECTOR = ROOT / "runtime" / "hermes-stdio-connector"
CORE = ROOT / "core"


def _prep(state: Path):
    os.environ["LEQUTIS_ROOT"] = str(ROOT)
    os.environ["LEQUTIS_STATE"] = str(state)
    os.environ.pop("LEQUTIS_HERMES_QUERY", None)
    sys.path.insert(0, str(CORE))
    sys.path.insert(0, str(CONNECTOR))
    sys.modules.pop("lequtis", None)
    sys.modules.pop("lequtis_mcp_stdio", None)
    import lequtis as L  # noqa: WPS433

    L.ROOT = ROOT
    L.STATE = state
    L.DB = state / "lequtis.db"
    state.mkdir(parents=True, exist_ok=True)
    L.init()
    L.event("test.seed", {"n": 1})
    import lequtis_mcp_stdio as adapter  # noqa: WPS433

    return L, adapter


def test_initialize_and_tools_list(state: Path) -> None:
    print("TEST BRIDGE: initialize + tools/list")
    _, adapter = _prep(state)
    hs = adapter.handshake_once()
    assert hs["ok"] is True
    assert "lequtis_status" in hs["tools"]
    assert "lequtis_verify_events" in hs["tools"]
    assert "hermes_probe" in hs["tools"]
    assert "hermes_query" not in hs["tools"]
    assert hs["hermes_query_enabled"] is False
    print("  PASS")


def test_status_and_chain(state: Path) -> None:
    print("TEST BRIDGE: status + valid chain")
    L, adapter = _prep(state)
    status = adapter.tool_lequtis_status()
    assert status["ok"] is True
    assert status["live_host"] is False
    assert status["status"]["events"] >= 1
    verify = adapter.tool_lequtis_verify_events()
    assert verify["ok"] is True
    assert verify["event_chain"]["ok"] is True
    assert "previous|timestamp|event_type|payload" in verify["formula"]
    # Tamper detection via kernel, then adapter reports failure.
    with L.connect() as db:
        db.execute("UPDATE events SET payload='{\"tampered\":true}' WHERE seq=1")
    broken = adapter.tool_lequtis_verify_events()
    assert broken["ok"] is False
    assert broken["event_chain"]["ok"] is False
    print("  PASS")


def test_query_disabled_and_no_synthetic_live(state: Path) -> None:
    print("TEST BRIDGE: query disabled + no synthetic live proof")
    _, adapter = _prep(state)
    q = adapter.tool_hermes_query("ping")
    assert q["ok"] is False
    assert q["reason"] == "hermes_query_disabled"
    probe = adapter.tool_hermes_probe()
    assert probe["live_host"] is False
    # Must not invent a Hostinger receipt when binary missing or present.
    assert "receipt" not in probe or probe.get("receipt") in (None, "")
    if not probe["ok"]:
        assert probe["reason"] == "hermes_binary_not_found"
    print("  PASS")


def test_tools_call_mcp_shape(state: Path) -> None:
    print("TEST BRIDGE: tools/call MCP response shape")
    _, adapter = _prep(state)
    reply = adapter.handle(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": "lequtis_status", "arguments": {}},
        }
    )
    assert reply["id"] == 9
    body = json.loads(reply["result"]["content"][0]["text"])
    assert body["ok"] is True
    assert body["live_host"] is False
    print("  PASS")


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="lequtis-bridge-"))
    try:
        test_initialize_and_tools_list(base / "a")
        test_status_and_chain(base / "b")
        test_query_disabled_and_no_synthetic_live(base / "c")
        test_tools_call_mcp_shape(base / "d")
        print()
        print("=== LEQUTIS STDIO BRIDGE TESTS: ALL PASS ===")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
