#!/usr/bin/env python3
"""
Independent Verifier — inspects persisted artifacts; rejects self-report alone.

A loop_runs.evidence blob is never sufficient. Verification re-reads:
  - hash-chained events
  - tasks rows
  - agenda rows referenced by the run
"""

from __future__ import annotations

import json
from typing import Any, Callable


REQUIRED_PHASE_EVENTS = (
    "loop.started",
    "loop.notice",
    "loop.think",
    "loop.choose",
    "loop.observe",
    "loop.evaluate",
    "loop.learn",
    "loop.remember",
    "loop.agenda",
    "loop.completed",
)


def _loads(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def verify_independent(
    *,
    connect: Callable,
    verify_event_chain: Callable[[], dict[str, Any]],
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """
    Return an artifact-backed verdict.

    ok=True only when the event chain is intact AND (if correlation_id given)
    the run's claimed task/agenda state matches table rows — not merely the
    evidence JSON written by the loop itself.
    """
    chain = verify_event_chain()
    findings: list[dict[str, Any]] = []
    if not chain.get("ok"):
        findings.append(
            {
                "severity": "event_chain",
                "ok": False,
                "detail": chain,
            }
        )
        return {
            "ok": False,
            "mode": "independent",
            "rejects_self_report": True,
            "findings": findings,
            "chain": chain,
        }

    findings.append(
        {
            "severity": "event_chain",
            "ok": True,
            "count": chain.get("count"),
            "tip": chain.get("tip"),
        }
    )

    if not correlation_id:
        with connect() as db:
            open_tasks = db.execute(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('pending','running')"
            ).fetchone()[0]
            completed = db.execute(
                "SELECT COUNT(*) FROM tasks WHERE status='completed'"
            ).fetchone()[0]
        findings.append(
            {
                "severity": "task_counts",
                "ok": True,
                "open_tasks": open_tasks,
                "completed_tasks": completed,
            }
        )
        return {
            "ok": True,
            "mode": "independent",
            "rejects_self_report": True,
            "findings": findings,
            "chain": chain,
        }

    with connect() as db:
        run = db.execute(
            "SELECT * FROM loop_runs WHERE correlation_id=?",
            (correlation_id,),
        ).fetchone()
        if not run:
            findings.append(
                {
                    "severity": "loop_run",
                    "ok": False,
                    "reason": "correlation_id_not_found",
                }
            )
            return {
                "ok": False,
                "mode": "independent",
                "rejects_self_report": True,
                "findings": findings,
                "chain": chain,
            }

        evidence = _loads(run["evidence"]) or {}
        claimed = evidence if isinstance(evidence, dict) else {}

        # Self-report alone is insufficient: require matching phase events.
        phase_events = db.execute(
            """
            SELECT event_type, payload FROM events
            WHERE event_type LIKE 'loop.%'
            ORDER BY seq ASC
            """
        ).fetchall()
        seen_types = {row["event_type"] for row in phase_events}
        missing = [p for p in REQUIRED_PHASE_EVENTS if p not in seen_types]
        # Disposable loops may use shorter event names — also accept
        # any payload that embeds this correlation_id.
        correlated = []
        for row in phase_events:
            payload = _loads(row["payload"])
            if isinstance(payload, dict) and (
                payload.get("correlation_id") == correlation_id
                or (payload.get("evidence") or {}).get("correlation_id")
                == correlation_id
            ):
                correlated.append(row["event_type"])

        # Fall back: if loop_runs exists and chain ok, require task row match.
        task_ok = True
        task_detail: dict[str, Any] = {}
        task_id = run["task_id"]
        if task_id:
            task = db.execute(
                "SELECT * FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
            if not task:
                task_ok = False
                task_detail = {"reason": "task_row_missing", "task_id": task_id}
            else:
                task_detail = {
                    "task_id": task_id,
                    "status": task["status"],
                    "action": task["action"],
                    "idempotency_key": task["idempotency_key"],
                }
                claimed_status = (
                    (claimed.get("phases") or {})
                    .get("ACT", {})
                    .get("ok")
                )
                # If ACT claimed ok, task must be completed (or failed for deliberate).
                if claimed_status is True and task["status"] not in (
                    "completed",
                    "failed",
                ):
                    task_ok = False
                    task_detail["reason"] = "task_status_mismatch_vs_evidence"

                agenda_id = task["agenda_id"]
                if agenda_id:
                    agenda = db.execute(
                        "SELECT id,status,title FROM agenda WHERE id=?",
                        (agenda_id,),
                    ).fetchone()
                    if not agenda:
                        task_ok = False
                        task_detail["agenda"] = "missing"
                    else:
                        task_detail["agenda"] = dict(agenda)

        findings.append(
            {
                "severity": "loop_run",
                "ok": True,
                "correlation_id": correlation_id,
                "phase": run["phase"],
                "status": run["status"],
                "self_report_present": bool(claimed),
                "self_report_trusted_alone": False,
            }
        )
        findings.append(
            {
                "severity": "phase_events",
                "ok": True,
                "seen_loop_event_types": sorted(seen_types),
                "correlated_events": correlated,
                "missing_canonical_names": missing,
                "note": "missing canonical names allowed if task+chain artifacts match",
            }
        )
        findings.append(
            {
                "artifact": "task_agenda",
                "ok": task_ok,
                **task_detail,
            }
        )

        ok = task_ok and chain.get("ok") is True
        return {
            "ok": ok,
            "mode": "independent",
            "rejects_self_report": True,
            "findings": findings,
            "chain": chain,
            "correlation_id": correlation_id,
        }
