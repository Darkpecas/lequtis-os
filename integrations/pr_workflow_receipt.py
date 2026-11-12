#!/usr/bin/env python3
"""Engineering workflow receipt — ties PR identity into the LeQutis ledger shape.

LeQutis remains the authority. This receipt is a subordinate artifact that a
later Hermes/TBQ/Verifier step can assimilate. It does not call Hermes,
Telegram, or Hostinger and does not mutate production state.

Schema aligns with integrations/hermes_receipt_gate.FIELDS where possible:
task_id, correlation_id, action, status, result_sha256, timestamp.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

EVIDENCE_LABEL = "LOCAL PROOF, NOT LIVE VPS VERIFIED"
SCHEMA = "lequtis.engineering_workflow_receipt.v1"
ACTION = "pr_gate_decide"


def _canonical(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def result_sha256(result: object) -> str:
    return hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


def build_receipt(
    *,
    pr_number: int | str,
    head_sha: str,
    base_ref: str,
    gate_verdict: dict[str, Any],
    auditor: dict[str, Any] | None = None,
    required_checks: dict[str, Any] | None = None,
    merge_sha: str | None = None,
    run_url: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a traceable engineering receipt for one PR gate decision."""
    ts = (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    correlation_id = f"pr-{pr_number}-{head_sha[:12]}"
    task_id = f"eng-pr-{pr_number}"
    status = "completed" if gate_verdict.get("merge_allowed") else "failed"
    result = {
        "pr_number": int(pr_number),
        "head_sha": head_sha,
        "base_ref": base_ref,
        "merge_allowed": bool(gate_verdict.get("merge_allowed")),
        "blocking": list(gate_verdict.get("blocking") or []),
        "merge_sha": merge_sha,
        "run_url": run_url,
        "review_source": gate_verdict.get("review_source"),
        "harmless": bool(gate_verdict.get("harmless")),
    }
    payload = {
        "task_id": task_id,
        "correlation_id": correlation_id,
        "action": ACTION,
        "status": status,
        "result_sha256": result_sha256(result),
        "timestamp": ts,
    }
    return {
        "schema": SCHEMA,
        "evidence_label": EVIDENCE_LABEL,
        "authority": "lequtis",
        "subordinate": "github_actions_pr_gate",
        "chain": [
            "LeQutis",
            "Oracle/TBQ(human-gated)",
            "Hermes(subordinate)",
            "Builder Swarm(subordinate)",
            "Verifier/Auditor",
        ],
        "payload": payload,
        "result": result,
        "gate": gate_verdict,
        "auditor": auditor,
        "required_checks": required_checks or {},
        "live_hermes": False,
        "live_hostinger": False,
        "live_telegram": False,
        "canonical_bytes_sha256": hashlib.sha256(_canonical(payload)).hexdigest(),
    }
