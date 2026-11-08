#!/usr/bin/env python3
"""
LeQutis MCP stdio adapter — System Access Manager contract (G01).

Integration candidate. Not deployed to Hostinger. Not a live Hermes proof.

Read-only tools (always):
  - lequtis_status
  - lequtis_verify_events
  - hermes_probe

Opt-in (LEQUTIS_HERMES_QUERY=1):
  - hermes_query  — subprocess only; never writes LeQutis canonical state

Contract recovered from LIVE LOOP ledger evidence when the private
System Access Manager plugin package was unavailable to this session.
Event-chain formula matches core/lequtis.py:
  SHA256(previous|timestamp|event_type|payload)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("LEQUTIS_ROOT", Path(__file__).resolve().parents[2]))
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

# Hermes query is disabled unless the host explicitly opts in.
HERMES_QUERY_ENABLED = os.environ.get("LEQUTIS_HERMES_QUERY", "").strip() in (
    "1",
    "true",
    "TRUE",
    "yes",
    "YES",
)
HERMES_TIMEOUT_SEC = int(os.environ.get("LEQUTIS_HERMES_TIMEOUT_SEC", "30"))
HERMES_BIN = os.environ.get("LEQUTIS_HERMES_BIN", "hermes")


def _load_lequtis():
    import lequtis as L  # noqa: WPS433

    return L


def tool_lequtis_status() -> dict[str, Any]:
    L = _load_lequtis()
    return {"ok": True, "live_host": False, "status": L.status()}


def tool_lequtis_verify_events() -> dict[str, Any]:
    L = _load_lequtis()
    chain = L.verify_event_chain()
    return {
        "ok": bool(chain.get("ok")),
        "live_host": False,
        "event_chain": chain,
        "formula": "sha256(previous|timestamp|event_type|payload)",
    }


def tool_hermes_probe() -> dict[str, Any]:
    """Read-only probe. Never fabricates a live Hostinger receipt."""
    path = shutil.which(HERMES_BIN)
    if not path:
        return {
            "ok": False,
            "live_host": False,
            "reason": "hermes_binary_not_found",
            "binary": HERMES_BIN,
            "hint": "Install Hermes on host or set LEQUTIS_HERMES_BIN",
        }
    try:
        proc = subprocess.run(
            [path, "--version"],
            text=True,
            capture_output=True,
            timeout=HERMES_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "live_host": False,
            "reason": "hermes_probe_timeout",
            "binary": path,
        }
    return {
        "ok": proc.returncode == 0,
        "live_host": False,
        "binary": path,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[:4000],
        "stderr": (proc.stderr or "")[:4000],
        "note": "Local binary probe only — not a Hostinger/Hermes live receipt",
    }


def tool_hermes_query(query: str) -> dict[str, Any]:
    if not HERMES_QUERY_ENABLED:
        return {
            "ok": False,
            "live_host": False,
            "reason": "hermes_query_disabled",
            "hint": "Set LEQUTIS_HERMES_QUERY=1 only after host principal/scope verified",
        }
    if not query or not str(query).strip():
        return {"ok": False, "reason": "empty_query"}
    path = shutil.which(HERMES_BIN)
    if not path:
        return {"ok": False, "reason": "hermes_binary_not_found", "binary": HERMES_BIN}
    # Compatibility UNKNOWN vs host Hermes CLI; keep legacy [--query] contract
    # documented in the LIVE LOOP ledger. Prefer host --help before live use.
    try:
        proc = subprocess.run(
            [path, "--query", str(query)],
            text=True,
            capture_output=True,
            timeout=HERMES_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "hermes_query_timeout"}
    return {
        "ok": proc.returncode == 0,
        "live_host": False,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[:8000],
        "stderr": (proc.stderr or "")[:8000],
        "note": (
            "Subprocess only — does NOT persist LeQutis intent, events, "
            "evaluation, memory, or agenda"
        ),
    }


TOOLS: list[dict[str, Any]] = [
    {
        "name": "lequtis_status",
        "description": "Read-only LeQutis kernel status (disposable or local DB).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "lequtis_verify_events",
        "description": "Verify hash-chained event fabric (previous|ts|type|payload).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "hermes_probe",
        "description": "Read-only local Hermes binary probe. Not a live Hostinger receipt.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]

if HERMES_QUERY_ENABLED:
    TOOLS.append(
        {
            "name": "hermes_query",
            "description": (
                "Opt-in Hermes --query subprocess. Disabled by default. "
                "Does not write LeQutis canonical state."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        }
    )


def call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    args = arguments or {}
    if name == "lequtis_status":
        return tool_lequtis_status()
    if name == "lequtis_verify_events":
        return tool_lequtis_verify_events()
    if name == "hermes_probe":
        return tool_hermes_probe()
    if name == "hermes_query":
        return tool_hermes_query(str(args.get("query", "")))
    return {"ok": False, "reason": "unknown_tool", "name": name}


def _read_message() -> dict[str, Any] | None:
    """MCP stdio framing: Content-Length header + JSON body."""
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        if b":" in line:
            key, value = line.decode("utf-8").split(":", 1)
            headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _write_message(msg: dict[str, Any]) -> None:
    raw = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(
        f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii") + raw
    )
    sys.stdout.buffer.flush()


def handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "lequtis-hermes-stdio",
                    "version": "1.2.22-reconstructed",
                },
                "instructions": (
                    "Integration candidate. Read-only by default. "
                    "Not a Hostinger live proof. hermes_query requires LEQUTIS_HERMES_QUERY=1."
                ),
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        result = call_tool(name, arguments)
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "content": [
                    {"type": "text", "text": json.dumps(result, indent=2, sort_keys=True)}
                ],
                "isError": not bool(result.get("ok", False)),
                "structuredContent": result,
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}

    return {
        "jsonrpc": "2.0",
        "id": mid,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def serve() -> int:
    while True:
        msg = _read_message()
        if msg is None:
            return 0
        reply = handle(msg)
        if reply is not None:
            _write_message(reply)


def handshake_once() -> dict[str, Any]:
    """Non-server helper for host_preflight / unit tests."""
    init = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
        }
    )
    tools = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    names = [t["name"] for t in (tools or {}).get("result", {}).get("tools", [])]
    return {
        "ok": init is not None and "lequtis_status" in names,
        "tools": names,
        "hermes_query_enabled": HERMES_QUERY_ENABLED,
        "server": (init or {}).get("result", {}).get("serverInfo"),
    }


if __name__ == "__main__":
    raise SystemExit(serve())
