#!/usr/bin/env python3
"""Traceable engineering workflow receipts for LeQutis.

LeQutis remains the authority. GitHub Actions, Codex, Hermes, and Telegram are
subordinate resources. This module never opens Hostinger, Hermes, or Telegram
connections. It records a single receipt that links:

  task identity → PR → independent review → tests → merge decision → verify

LOCAL PROOF, NOT LIVE VPS VERIFIED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EVIDENCE_LABEL = "LOCAL PROOF, NOT LIVE VPS VERIFIED"
SCHEMA = "lequtis-engineering-workflow-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def build_receipt(
    *,
    task_id: str | None = None,
    pr_number: int | None = None,
    pr_url: str | None = None,
    head_sha: str | None = None,
    base_ref: str | None = None,
    gate_verdict: dict[str, Any] | None = None,
    static_audit: dict[str, Any] | None = None,
    ai_review: str | None = None,
    tests_passed: bool | None = None,
    test_attempts: int | None = None,
    merge_attempted: bool = False,
    merge_result: str | None = None,
    actions_run_url: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Assemble one workflow receipt. Does not claim live Hermes/Telegram."""
    correlation_id = correlation_id or ("eng-" + uuid.uuid4().hex)
    task = task_id or ("pr-" + str(pr_number) if pr_number is not None else correlation_id)
    stages = {
        "build": {"status": "recorded", "head_sha": head_sha, "base_ref": base_ref},
        "pull_request": {"status": "recorded", "number": pr_number, "url": pr_url},
        "independent_review": {
            "status": ai_review or (static_audit or {}).get("status") or "missing",
            "ai_review": ai_review,
            "static_audit": (static_audit or {}).get("status"),
            "static_findings": len((static_audit or {}).get("findings") or []),
        },
        "tests": {
            "status": "pass" if tests_passed else ("fail" if tests_passed is False else "unknown"),
            "attempts": test_attempts,
        },
        "verify": {
            "status": "recorded" if gate_verdict is not None else "missing",
            "merge_allowed": (gate_verdict or {}).get("merge_allowed"),
            "blocking": (gate_verdict or {}).get("blocking") or [],
        },
        "auto_merge": {
            "attempted": merge_attempted,
            "result": merge_result or ("not_attempted" if not merge_attempted else "unknown"),
        },
        "read_back": {
            "status": "local_receipt_only",
            "note": "Canonical Hostinger/Hermes read-back remains a separate live gate.",
        },
    }
    receipt = {
        "schema": SCHEMA,
        "evidence_label": EVIDENCE_LABEL,
        "authority": "LeQutis",
        "subordinate_resources": ["github_actions", "codex_review", "static_auditor"],
        "not_authorities": ["github", "codex", "cursor_agent", "hermes", "telegram"],
        "live_hermes": False,
        "live_hostinger": False,
        "live_telegram": False,
        "correlation_id": correlation_id,
        "task_id": task,
        "created": _utc_now(),
        "actions_run_url": actions_run_url,
        "stages": stages,
        "gate_verdict": gate_verdict,
        "static_audit": static_audit,
    }
    receipt["receipt_sha256"] = _sha256(
        {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    )
    return receipt


def write_receipt(path: Path, receipt: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def update_merge_outcome(
    receipt: dict[str, Any],
    *,
    merge_attempted: bool,
    merge_result: str,
) -> dict[str, Any]:
    """Preserve correlation_id while recording the final merge outcome."""
    updated = dict(receipt)
    stages = dict(updated.get("stages") or {})
    auto_merge = dict(stages.get("auto_merge") or {})
    auto_merge["attempted"] = merge_attempted
    auto_merge["result"] = merge_result
    stages["auto_merge"] = auto_merge
    updated["stages"] = stages
    updated["updated"] = _utc_now()
    updated["receipt_sha256"] = _sha256(
        {k: v for k, v in updated.items() if k != "receipt_sha256"}
    )
    return updated


def event_payload(receipt: dict[str, Any]) -> dict[str, Any]:
    """Shape suitable for LeQutis hash-chained events without importing the kernel."""
    return {
        "schema": SCHEMA,
        "correlation_id": receipt.get("correlation_id"),
        "task_id": receipt.get("task_id"),
        "receipt_sha256": receipt.get("receipt_sha256"),
        "merge_allowed": ((receipt.get("gate_verdict") or {}).get("merge_allowed")),
        "blocking": ((receipt.get("gate_verdict") or {}).get("blocking") or []),
        "actions_run_url": receipt.get("actions_run_url"),
        "live_hermes": False,
        "live_hostinger": False,
        "evidence_label": EVIDENCE_LABEL,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id")
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--pr-url")
    parser.add_argument("--head-sha")
    parser.add_argument("--base-ref")
    parser.add_argument("--gate-file")
    parser.add_argument("--static-audit-file")
    parser.add_argument("--ai-review")
    parser.add_argument("--tests-passed", choices=("true", "false"))
    parser.add_argument("--test-attempts", type=int)
    parser.add_argument("--merge-attempted", choices=("true", "false"), default="false")
    parser.add_argument("--merge-result")
    parser.add_argument("--actions-run-url")
    parser.add_argument("--correlation-id")
    parser.add_argument(
        "--update-receipt-file",
        help="Existing receipt to update in place, preserving correlation_id",
    )
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.update_receipt_file:
        existing = json.loads(Path(args.update_receipt_file).read_text(encoding="utf-8"))
        receipt = update_merge_outcome(
            existing,
            merge_attempted=args.merge_attempted == "true",
            merge_result=args.merge_result or "unknown",
        )
        write_receipt(Path(args.out), receipt)
        sys.stdout.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        return 0
    gate = json.loads(Path(args.gate_file).read_text(encoding="utf-8")) if args.gate_file else None
    static = (
        json.loads(Path(args.static_audit_file).read_text(encoding="utf-8"))
        if args.static_audit_file
        else None
    )
    tests_passed = None
    if args.tests_passed is not None:
        tests_passed = args.tests_passed == "true"
    receipt = build_receipt(
        task_id=args.task_id,
        pr_number=args.pr_number,
        pr_url=args.pr_url,
        head_sha=args.head_sha,
        base_ref=args.base_ref,
        gate_verdict=gate,
        static_audit=static,
        ai_review=args.ai_review,
        tests_passed=tests_passed,
        test_attempts=args.test_attempts,
        merge_attempted=args.merge_attempted == "true",
        merge_result=args.merge_result,
        actions_run_url=args.actions_run_url,
        correlation_id=args.correlation_id,
    )
    write_receipt(Path(args.out), receipt)
    sys.stdout.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
