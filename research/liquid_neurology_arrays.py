#!/usr/bin/env python3
"""LeQutis research array packet generator. No network, autonomous execution or production writes."""
import argparse
import hashlib
import json
from pathlib import Path

ARRAYS = {
    "protocol": ("MCP versions, SDK capability gaps, interoperability", "primary specification and reproducible capability test"),
    "memory": ("Continual learning and retention versus mere retrieval", "held-out task comparison with baseline"),
    "diversity": ("Independent research hypotheses and convergence failures", "counterexample and source-independence audit"),
    "engineering": ("Autonomous coding and feature-level evaluation", "fresh checkout reproducible test"),
    "security": ("MCP authorization, prompt injection and receipt provenance", "negative authorization test"),
    "continuity": ("Hermes task resumption after iPhone disconnect", "same idempotency key and audit continuity"),
    "invention": ("Curiosity allocation and Liquid Neurology mechanisms", "equal-budget preregistered baseline"),
}
PHASES = ("GOAL", "STATE", "EVIDENCE", "GAP", "ACTION", "TEST", "VERIFY", "UPDATE")

def packets(goal):
    """Return independent bounded research briefs, not fabricated research results."""
    for name, (question, gate) in ARRAYS.items():
        packet = {
            "schema": "lequtis.research.packet.v1",
            "sovereign": "LeQutis",
            "array": name,
            "goal": goal,
            "question": question,
            "verification_gate": gate,
            "phase": "NOTICE",
            "status": "NOT_EXECUTED",
            "allowed_decisions": ["HARVEST", "ISOLATED_EXPERIMENT", "BOUNDED_USE", "WATCH", "REJECT", "ORIGINAL_INVENTION"],
            "required_return": ["claim", "primary_sources", "contradictions", "uncertainty", "harvestable_primitive", "falsification_test", "test_observation", "decision"],
        }
        packet["idempotency_key"] = hashlib.sha256((goal + "\0" + name).encode()).hexdigest()[:24]
        yield packet

def verify_receipt(receipt):
    """Reject agent self-reports lacking a separate, observable verification receipt."""
    if not isinstance(receipt, dict):
        return False
    if receipt.get("status") != "VERIFIED":
        return False
    if not all(receipt.get(k) for k in ("idempotency_key", "primary_sources", "test_observation", "verifier", "evidence_hash")):
        return False
    if receipt.get("verifier") == receipt.get("executor"):
        return False
    return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", default="Investigate frontier advances useful to LeQutis")
    parser.add_argument("--verify-receipt", type=Path, help="Read-only receipt validation; does not authenticate identity")
    args = parser.parse_args()
    if args.verify_receipt:
        data = json.loads(args.verify_receipt.read_text(encoding="utf-8"))
        valid = verify_receipt(data)
        print(json.dumps({"receipt_structure_valid": valid, "live_verified": False}))
        return 0 if valid else 2
    for packet in packets(args.goal):
        print(json.dumps(packet, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
