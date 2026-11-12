#!/usr/bin/env python3
"""Short gate summary for the existing Hermes route.

This does not provision Telegram, Hostinger, or a tunnel. The route in this
repository can probe; it has no Telegram sender. Missing route secrets degrade
to a receipt field and never print secret values.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ROUTE_PATH = ROOT / "runtime" / "chatgpt_hermes_route" / "route.py"

PRESENCE_NAMES = (
    "LEQUTIS_TUNNEL_ID",
    "LEQUTIS_TUNNEL_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)


def presence(names: tuple[str, ...] = PRESENCE_NAMES) -> dict[str, str]:
    return {name: "present" if os.environ.get(name) else "absent" for name in names}


def _scrub(text: str) -> str:
    cleaned = text
    for name in PRESENCE_NAMES:
        value = os.environ.get(name) or ""
        if len(value) >= 8:
            cleaned = cleaned.replace(value, "<redacted>")
    return cleaned


def _load_route() -> Any:
    spec = importlib.util.spec_from_file_location("lequtis_hermes_route", ROUTE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError("hermes route module is not loadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


def deliver(summary: str) -> dict[str, Any]:
    """Record a subordinate Hermes probe. Never claims a Telegram send."""
    preview = _scrub(summary or "")[:180]
    report: dict[str, Any] = {
        "channel": "hermes",
        "telegram_delivered": False,
        "live_host": False,
        "degraded": True,
        "reason": "lequtis_hermes_route_has_no_telegram_sender",
        "summary_sha256": hashlib.sha256((summary or "").encode("utf-8")).hexdigest(),
        "summary_preview": preview,
        "presence": presence(),
        "route": None,
    }
    try:
        module = _load_route()
        probe = module.establish_route_and_probe("disposable")
    except Exception as exc:  # noqa: BLE001 - degrade, do not fail the gate
        report["reason"] = "hermes_route_unavailable"
        report["error"] = type(exc).__name__
        return report
    report["route"] = probe.get("route")
    report["probe_ok"] = bool(probe.get("ok"))
    report["live_host"] = False
    if probe.get("live_host"):
        report["probe_live_host_ignored"] = True
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", default="LeQutis engineering gate")
    parser.add_argument("--summary-file")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    text = args.summary
    if args.summary_file:
        text = Path(args.summary_file).read_text(encoding="utf-8")
    report = deliver(text)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
