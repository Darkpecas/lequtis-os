#!/usr/bin/env python3
"""
G02/G03 — ChatGPT → bridge → Hermes/Hostinger route contract.

Disposable by default. Live Hostinger/tunnel requires explicit operator env
and never fabricates production receipts.

Env for LIVE attempts (all required; unset ⇒ disposable/denied):
  LEQUTIS_HERMES_ROUTE=live
  LEQUTIS_TUNNEL_ID=...          (presence check only; value not logged)
  LEQUTIS_TUNNEL_API_KEY=...     (presence check only; value not logged)
  LEQUTIS_HERMES_BIN=hermes
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class RoutePrincipal:
    id: str
    scope: str
    authorized: bool


@dataclass
class ProbeReceipt:
    receipt_id: str
    route: str
    live_host: bool
    ok: bool
    principal: str
    tool: str
    ts: float
    payload_hash: str
    detail: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "route": self.route,
            "live_host": self.live_host,
            "ok": self.ok,
            "principal": self.principal,
            "tool": self.tool,
            "ts": self.ts,
            "payload_hash": self.payload_hash,
            "detail": self.detail,
        }


def _hash_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _is_secret_field(name: str) -> bool:
    n = name.lower()
    if n.endswith("_present") or n.endswith("_set") or n == "need":
        return False
    return (
        n.endswith("_key")
        or n.endswith("_token")
        or n.endswith("_secret")
        or n in {"api_key", "token", "secret", "password", "authorization"}
        or "api_key" in n
        or "access_token" in n
    )


def make_receipt(
    *,
    route: str,
    live_host: bool,
    ok: bool,
    principal: str,
    tool: str,
    detail: dict[str, Any],
) -> ProbeReceipt:
    # Never embed secret values in receipts. Boolean presence flags are OK.
    scrubbed = {
        k: ("<redacted>" if _is_secret_field(k) and not isinstance(v, bool) else v)
        for k, v in detail.items()
    }
    return ProbeReceipt(
        receipt_id=str(uuid.uuid4()),
        route=route,
        live_host=live_host,
        ok=ok,
        principal=principal,
        tool=tool,
        ts=time.time(),
        payload_hash=_hash_payload(scrubbed),
        detail=scrubbed,
    )


class HermesTransport(Protocol):
    name: str

    def authorize(self) -> RoutePrincipal: ...

    def probe(self) -> ProbeReceipt: ...


class DisposableFakeRoute:
    """Authorized disposable route for contract tests — never claims Hostinger."""

    name = "disposable_fake"

    def __init__(self, principal_id: str = "test_principal") -> None:
        self.principal_id = principal_id

    def authorize(self) -> RoutePrincipal:
        return RoutePrincipal(
            id=self.principal_id, scope="read_only_probe", authorized=True
        )

    def probe(self) -> ProbeReceipt:
        principal = self.authorize()
        detail = {
            "hermes_version": "fake-0.0.0",
            "stdout": "HERMES FAKE PROBE OK",
            "note": "disposable fake — not Hostinger",
        }
        return make_receipt(
            route=self.name,
            live_host=False,
            ok=True,
            principal=principal.id,
            tool="hermes_probe",
            detail=detail,
        )


class LiveHostingerRoute:
    """
    Local Hermes binary probe guarded by the intended live-route configuration.
    This module has no tunnel transport, so it must never claim a live Hostinger
    route from local configuration or a local ``hermes --version`` response.
    """

    name = "chatgpt_tunnel_hostinger"

    def authorize(self) -> RoutePrincipal:
        live = (os.environ.get("LEQUTIS_HERMES_ROUTE") or "").strip().lower() == "live"
        has_tunnel = bool(os.environ.get("LEQUTIS_TUNNEL_ID"))
        has_key = bool(os.environ.get("LEQUTIS_TUNNEL_API_KEY"))
        ok = live and has_tunnel and has_key
        return RoutePrincipal(
            id="alan_operator" if ok else "unauthorized",
            scope="read_only_probe",
            authorized=ok,
        )

    def probe(self) -> ProbeReceipt:
        principal = self.authorize()
        if not principal.authorized:
            return make_receipt(
                route=self.name,
                live_host=False,
                ok=False,
                principal=principal.id,
                tool="hermes_probe",
                detail={
                    "reason": "route_not_authorized",
                    "need": [
                        "LEQUTIS_HERMES_ROUTE=live",
                        "LEQUTIS_TUNNEL_ID",
                        "LEQUTIS_TUNNEL_API_KEY",
                    ],
                    # Presence flags only — never values.
                    "tunnel_id_present": bool(os.environ.get("LEQUTIS_TUNNEL_ID")),
                    "tunnel_api_key_present": bool(
                        os.environ.get("LEQUTIS_TUNNEL_API_KEY")
                    ),
                },
            )

        binary = os.environ.get("LEQUTIS_HERMES_BIN", "hermes")
        path = shutil.which(binary)
        if not path:
            return make_receipt(
                route=self.name,
                live_host=False,
                ok=False,
                principal=principal.id,
                tool="hermes_probe",
                detail={
                    "reason": "hermes_binary_not_found",
                    "binary": binary,
                    "probe_scope": "local_binary_only",
                    "remote_tunnel_probe_required": True,
                },
            )
        try:
            proc = subprocess.run(
                [path, "--version"],
                text=True,
                capture_output=True,
                timeout=int(os.environ.get("LEQUTIS_HERMES_TIMEOUT_SEC", "30")),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return make_receipt(
                route=self.name,
                live_host=False,
                ok=False,
                principal=principal.id,
                tool="hermes_probe",
                detail={
                    "reason": "hermes_probe_timeout",
                    "probe_scope": "local_binary_only",
                    "remote_tunnel_probe_required": True,
                },
            )
        return make_receipt(
            route=self.name,
            live_host=False,
            ok=proc.returncode == 0,
            principal=principal.id,
            tool="hermes_probe",
            detail={
                "binary": path,
                "returncode": proc.returncode,
                "stdout": (proc.stdout or "")[:2000],
                "stderr": (proc.stderr or "")[:2000],
                "probe_scope": "local_binary_only",
                "remote_tunnel_probe_required": True,
            },
        )


def get_route(mode: str | None = None) -> HermesTransport:
    chosen = (mode or os.environ.get("LEQUTIS_HERMES_ROUTE") or "disposable").strip().lower()
    if chosen == "live":
        return LiveHostingerRoute()
    return DisposableFakeRoute()


def establish_route_and_probe(mode: str | None = None) -> dict[str, Any]:
    """G02 authorize + G03 probe in one auditable report."""
    route = get_route(mode)
    principal = route.authorize()
    receipt = route.probe()
    return {
        "ok": principal.authorized and receipt.ok,
        "live_host": receipt.live_host,
        "route": route.name,
        "principal": {
            "id": principal.id,
            "scope": principal.scope,
            "authorized": principal.authorized,
        },
        "receipt": receipt.as_dict(),
        "gates": {
            "G02": "PARTIAL" if principal.authorized and not receipt.live_host else (
                "VERIFIED_LIVE" if principal.authorized and receipt.live_host and receipt.ok else "OPEN"
            ),
            "G03": "PARTIAL" if receipt.ok and not receipt.live_host else (
                "VERIFIED_LIVE" if receipt.ok and receipt.live_host else "OPEN"
            ),
        },
    }


if __name__ == "__main__":
    print(json.dumps(establish_route_and_probe(), indent=2, sort_keys=True))
