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


def _write_principal() -> str | None:
    # The trusted host binds this stdio process to a principal. Never accept a
    # caller-supplied principal, path, SQL statement, or capability escalation.
    if os.environ.get("LEQUTIS_CANONICAL_WRITE") != "1":
        return None
    principal = os.environ.get("LEQUTIS_WRITE_PRINCIPAL", "")
    import re
    return principal if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", principal) else None


def tool_canonical_intake(arguments: Any, *, read_only: bool = False) -> dict[str, Any]:
    principal = _write_principal()
    if principal is None:
        return {"ok": False, "live_host": False, "reason": "canonical_write_disabled"}
    # The host must attest that this stdio process is reachable only over a
    # trusted local transport before any canonical intake or read is served.
    if os.environ.get("LEQUTIS_TRUSTED_LOCAL_TRANSPORT") != "1":
        return {"ok": False, "live_host": False, "reason": "trusted_transport_not_attested"}
    try:
        import canonical_write as C
        if read_only:
            if not isinstance(arguments, dict) or set(arguments) != {"idempotency_key"}:
                raise ValueError("request_fields_invalid")
            return C.read_intake(principal, arguments["idempotency_key"])
        return C.write_intake(principal, arguments)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        # Error messages contain field names only; never echo secrets or input.
        return {"ok": False, "live_host": False, "reason": str(exc) if isinstance(exc, ValueError) else "canonical_intake_unavailable"}
    except Exception:
        return {"ok": False, "live_host": False, "reason": "canonical_intake_unavailable"}


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

if _write_principal():
    TOOLS.extend([
        {
            "name": "lequtis_canonical_write",
            "description": "Atomically record task intent held awaiting approval, an unverified receipt claim and submitted memory in the existing WAL DB. Neither loop engine executes held work; no approval operation is exposed.",
            "inputSchema": {
                "type": "object", "additionalProperties": False,
                "required": ["idempotency_key", "title", "action", "payload", "receipt", "memory"],
                "properties": {
                    "idempotency_key": {"type": "string", "maxLength": 128},
                    "title": {"type": "string", "maxLength": 2000},
                    "action": {"type": "string", "enum": ["inspect_status", "store_note", "ping", "deliberate_fail"]},
                    "payload": {"type": "object"}, "receipt": {"type": "object"},
                    "memory": {"type": "object", "additionalProperties": False,
                               "required": ["kind", "content"],
                               "properties": {"kind": {"type": "string", "enum": ["semantic", "episodic", "working"]},
                                              "content": {"type": "string", "maxLength": 16000}}},
                },
            },
        },
        {
            "name": "lequtis_canonical_read",
            "description": "Independently read back the host principal's canonical intake and check its stored bindings and event chain.",
            "inputSchema": {"type": "object", "additionalProperties": False,
                            "required": ["idempotency_key"],
                            "properties": {"idempotency_key": {"type": "string", "maxLength": 128}}},
        },
    ])


def call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    args = arguments or {}
    if name == "lequtis_canonical_write":
        return tool_canonical_intake(arguments)
    if name == "lequtis_canonical_read":
        return tool_canonical_intake(arguments, read_only=True)
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
    """Read one newline-delimited JSON-RPC message from MCP stdio."""
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if not line.strip():
            continue
        message = json.loads(line.decode("utf-8"))
        if not isinstance(message, dict):
            raise ValueError("MCP stdio message must be a JSON object")
        return message


def _write_message(msg: dict[str, Any]) -> None:
    raw = json.dumps(msg, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(raw + b"\n")
    sys.stdout.buffer.flush()


def handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    # This adapter implements legacy MCP 2024-11-05 only. Never echo a
    # modern (2026-07-28) version: it requires server/discover and per-request
    # metadata, neither of which this adapter implements.
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": "2024-11-05",
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
