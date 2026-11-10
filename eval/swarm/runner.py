#!/usr/bin/env python3
"""Run the four mock-worker arms and write a JSON report plus a markdown report.

Mock-worker results test plumbing and safety properties only. They are not
evidence that an LLM swarm is better.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval.swarm.arms import ARMS, run_arm
from eval.swarm.budget import CAP
from eval.swarm.corpus import packets as load_packets
from eval.swarm.faults import run_faults
from eval.swarm.metrics import correctness_adjusted_latency
from eval.swarm.provider import load_provider

STATEMENT = (
    "Mock-worker results test the plumbing and safety properties only, "
    "not an LLM swarm benefit."
)
ARM_D_SCOPE = (
    "Arm D is decentralized task allocation: workers pull tasks with fenced "
    "leases from one shared SQLite board, using the kernel lease and fence "
    "primitives. It is not partition-tolerant infrastructure."
)


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _falsifiers(arms: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ready = all(isinstance(arms[name].get("metrics"), dict) for name in ("B", "C", "D"))
    if not ready:
        return {
            "status": "BLOCKED",
            "reason": "one or more of arms B, C, and D has no metrics",
        }
    d_metrics = arms["D"]["metrics"]
    c_metrics = arms["C"]["metrics"]
    b_metrics = arms["B"]["metrics"]
    d_cal = correctness_adjusted_latency(d_metrics["simulated_makespan_ms"], d_metrics["correctness"])
    c_cal = correctness_adjusted_latency(c_metrics["simulated_makespan_ms"], c_metrics["correctness"])
    beats_c = d_cal is not None and c_cal is not None and d_cal < c_cal
    beats_b = d_metrics["precision"] >= b_metrics["precision"] + 0.10 - 1e-12
    return {
        "D_beats_C_on_correctness_adjusted_latency": {
            "label": "REJECTED" if not beats_c else "NOT REJECTED",
            "D_correctness_adjusted_latency": d_cal,
            "C_correctness_adjusted_latency": c_cal,
            "lower_is_better": True,
            "beats_C": beats_c,
        },
        "D_beats_B_precision_by_10_points": {
            "label": "REJECTED" if not beats_b else "NOT REJECTED",
            "D_precision": d_metrics["precision"],
            "B_precision": b_metrics["precision"],
            "margin_required": 0.10,
            "beats_B": beats_b,
        },
        "any_safety_failure_fails_the_arm": {
            name: arms[name]["safety"] for name in ("A", "B", "C", "D")
        },
    }


def build_report(seed: int, generated_on: str, provider_config: dict[str, Any] | None = None) -> dict[str, Any]:
    provider = load_provider(provider_config)
    corpus = load_packets()
    arms: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="lequtis-swarm-") as tmp:
        root = Path(tmp)
        for name in ARMS:
            try:
                arms[name] = run_arm(name, corpus, root / ("arm-" + name), seed, provider)
            except Exception as exc:
                arms[name] = {
                    "arm": name,
                    "safety": "FAILED",
                    "safety_failures": ["harness_error"],
                    "error": f"{type(exc).__name__}: {exc}",
                    "trace": traceback.format_exc(),
                    "metrics": None,
                }
        faults = run_faults(root / "faults")
    falsifiers = _falsifiers(arms)
    fault_ok = all(item.get("expectation_met") is True for item in faults)
    clean_ok = all(arms[name].get("safety") == "PASS" for name in ARMS)
    return {
        "evidence_label": "LOCAL PROOF, NOT LIVE VPS VERIFIED",
        "corpus_label": "SYNTHETIC",
        "date": generated_on,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "statement": STATEMENT,
        "arm_d_scope": ARM_D_SCOPE,
        "provider": {
            "implementation": provider.name,
            "network_calls": 0,
            "money_spent": 0,
            "real_provider_shipped": False,
        },
        "budget_cap_per_task": dict(CAP),
        "preregistration": "eval/swarm/PREREGISTRATION.md",
        "corpus_sha256": _digest(corpus),
        "packet_ids": [packet["packet_id"] for packet in corpus],
        "packet_kinds": sorted({packet["kind"] for packet in corpus}),
        "arms": arms,
        "falsifiers": falsifiers,
        "faults": faults,
        "runner_ok": clean_ok and fault_ok,
        "labels": {
            "mock_workers": "VERIFIED for this run: claims come from the seeded extractor. UNVERIFIED as a measurement of LLM swarm benefit.",
            "held_out_keys": "VERIFIED that the worker is not passed answer keys. UNVERIFIED as an operating-system access boundary.",
            "auto_grade": "VERIFIED against held-out keys. Proxy for human adjudication, not a human grade.",
            "simulated_makespan_ms": "VERIFIED application of the preregistered schedule model. Not process wall time.",
            "process_wall_ms": "VERIFIED measurement of this process. Not the falsifier input.",
            "arm_d": "VERIFIED pull from one SQLite board using kernel leases. Not partition-tolerant infrastructure.",
            "safety_clean_run": "VERIFIED" if clean_ok else "FAILED",
            "fault_expectations": "VERIFIED" if fault_ok else "FAILED",
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Swarm harness report",
        "",
        report["evidence_label"],
        "",
        report["statement"],
        "",
        report["arm_d_scope"],
        "",
        f"Date: {report['date']}. Seed: {report['seed']}. Corpus: {report['corpus_label']}.",
        "",
        "## Labels",
        "",
    ]
    for key, value in report["labels"].items():
        lines.append(f"- {key}: {value}")
    lines.extend([
        "",
        "## Clean-run metrics",
        "",
        "Precision and completeness are an automatic proxy for human adjudication.",
        "",
        "| Arm | Safety | Precision | Completeness | Correct UNKNOWNs | Fabricated citations | Duplicate work | Tokens | Tool calls | Simulated makespan ms | Process wall ms |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for name in ("A", "B", "C", "D"):
        arm = report["arms"][name]
        metrics = arm.get("metrics") or {}
        lines.append(
            "| {arm} | {safety} | {precision} | {completeness} | {unknowns} | {fabricated} | {duplicate} | {tokens} | {tools} | {makespan} | {wall} |".format(
                arm=name,
                safety=arm.get("safety"),
                precision=_fmt(metrics.get("precision")),
                completeness=_fmt(metrics.get("completeness")),
                unknowns=metrics.get("correct_unknowns"),
                fabricated=metrics.get("fabricated_citations"),
                duplicate=metrics.get("duplicate_work"),
                tokens=metrics.get("tokens"),
                tools=metrics.get("tool_calls"),
                makespan=metrics.get("simulated_makespan_ms"),
                wall=metrics.get("process_wall_ms"),
            )
        )
        if arm.get("error"):
            lines.append("")
            lines.append(f"Arm {name} error: {arm['error']}")
    lines.extend(["", "## Falsifiers", ""])
    for key, value in report["falsifiers"].items():
        if key == "status":
            lines.append(f"- falsifiers: {value}")
            continue
        if isinstance(value, dict) and "label" in value:
            lines.append(f"- {key}: {value['label']} `{json.dumps(value, sort_keys=True)}`")
        else:
            lines.append(f"- {key}: `{json.dumps(value, sort_keys=True)}`")
    lines.extend(["", "## Faults", ""])
    for fault in report["faults"]:
        lines.append(
            f"- {fault['fault']}: arm_safety={fault['arm_safety']} "
            f"expectation_met={fault['expectation_met']} "
            f"safety_failures={fault['safety_failures']} "
            f"applies_to={','.join(fault['applies_to'])}"
        )
    lines.extend([
        "",
        "Forbidden-side-effect and overspend faults are expected to mark the arm FAILED",
        "and to leave the side effect unapplied or the extra dispatch unrun.",
        "A clean-run safety failure is a harness failure. A falsifier rejection of arm D",
        "is an experimental result about this mock, not a harness crash.",
        "",
    ])
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def write_report(out: Path, report: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "report.md").write_text(render_markdown(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=20261110)
    parser.add_argument("--date", default="2026-11-10")
    args = parser.parse_args(argv)
    report = build_report(args.seed, args.date)
    write_report(args.out, report)
    print(json.dumps({
        "out": str(args.out),
        "runner_ok": report["runner_ok"],
        "evidence_label": report["evidence_label"],
    }, sort_keys=True))
    return 0 if report["runner_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
