#!/usr/bin/env python3
"""Disposable G02/G03 route contract tests — never claim Hostinger live."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTE = ROOT / "runtime" / "chatgpt_hermes_route"
sys.path.insert(0, str(ROUTE))

import route as R  # noqa: E402


def test_disposable_route_receipt() -> None:
    print("TEST ROUTE: disposable authorized probe receipt")
    os.environ.pop("LEQUTIS_HERMES_ROUTE", None)
    report = R.establish_route_and_probe("disposable")
    assert report["ok"] is True
    assert report["live_host"] is False
    receipt = report["receipt"]
    assert receipt["ok"] is True
    assert receipt["live_host"] is False
    assert receipt["receipt_id"]
    assert receipt["payload_hash"]
    assert report["gates"]["G02"] == "PARTIAL"
    assert report["gates"]["G03"] == "PARTIAL"
    print("  PASS")


def test_live_refuses_without_credentials() -> None:
    print("TEST ROUTE: live refuses without tunnel credentials")
    for k in ("LEQUTIS_TUNNEL_ID", "LEQUTIS_TUNNEL_API_KEY", "LEQUTIS_HERMES_ROUTE"):
        os.environ.pop(k, None)
    report = R.establish_route_and_probe("live")
    assert report["ok"] is False
    assert report["live_host"] is False
    assert report["principal"]["authorized"] is False
    assert report["receipt"]["detail"]["reason"] == "route_not_authorized"
    assert report["receipt"]["detail"]["tunnel_api_key_present"] is False
    print("  PASS")


def test_receipt_redacts_secrets() -> None:
    print("TEST ROUTE: receipts redact secret-like fields")
    os.environ["LEQUTIS_TUNNEL_API_KEY"] = "SUPERSECRET-VALUE-XYZ"
    try:
        receipt = R.make_receipt(
            route="t",
            live_host=False,
            ok=True,
            principal="p",
            tool="hermes_probe",
            detail={"api_key": "SUPERSECRET-VALUE-XYZ", "stdout": "ok"},
        )
        assert receipt.detail["api_key"] == "<redacted>"
        assert receipt.detail["stdout"] == "ok"
        assert "SUPERSECRET-VALUE-XYZ" not in json_blob(receipt.as_dict())
        # Live probe must not echo the key value either.
        report = R.establish_route_and_probe("live")
        assert "SUPERSECRET-VALUE-XYZ" not in json_blob(report)
    finally:
        os.environ.pop("LEQUTIS_TUNNEL_API_KEY", None)
    print("  PASS")


def json_blob(obj) -> str:
    import json

    return json.dumps(obj)


def main() -> int:
    test_disposable_route_receipt()
    test_live_refuses_without_credentials()
    test_receipt_redacts_secrets()
    print()
    print("=== LEQUTIS HERMES ROUTE TESTS: ALL PASS ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
