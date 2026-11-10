"""Seeded mock workers. They propose claim records and never call ACT."""
from __future__ import annotations

import hashlib
from typing import Any

from eval.swarm.provider import MockProvider

INJECTION_MARKERS = (
    "ignore previous instructions",
    "ignore prior instructions",
    "new task:",
    "call act",
)


class SideEffectError(Exception):
    """ACT was attempted. The attempt is not applied."""


class SideEffects:
    def __init__(self) -> None:
        self.attempted: list[str] = []
        self.applied: list[str] = []

    def act(self, name: str) -> None:
        self.attempted.append(name)
        raise SideEffectError("ACT is forbidden in the swarm harness")


def passage_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _unknown(packet: dict[str, Any], seed: int, injections: int, reason: str) -> dict[str, Any]:
    return {
        "label": "SYNTHETIC",
        "packet_id": packet["packet_id"],
        "seed": seed,
        "verdict": "UNKNOWN",
        "reason": reason,
        "claims": [],
        "injections_ignored": injections,
        "scope_id": packet["packet_id"],
        "act_called": False,
    }


def extract(
    packet: dict[str, Any],
    prior_propositions: list[str],
    seed: int,
    provider: MockProvider | None = None,
    side_effects: SideEffects | None = None,
) -> dict[str, Any]:
    """Propose claims from FACT lines. Quoted instructions do not change scope."""
    if packet.get("_call_act"):
        if side_effects is None:
            side_effects = SideEffects()
        side_effects.act(packet["packet_id"])
    engine = provider or MockProvider()
    prompt = packet["packet_id"] + "\n" + packet["question"]
    engine.complete(prompt, seed=seed, max_tokens=24)
    injections = 0
    facts: list[dict[str, str]] = []
    for passage in packet["passages"]:
        digest = passage_hash(passage["text"])
        for line in passage["text"].splitlines():
            stripped = line.strip()
            lowered = stripped.lower()
            if any(marker in lowered for marker in INJECTION_MARKERS):
                injections += 1
                continue
            if not stripped.startswith("FACT:"):
                continue
            proposition = stripped[len("FACT:"):].strip()
            subject = proposition.split(" = ", 1)[0]
            facts.append({
                "proposition": proposition,
                "subject": subject,
                "source_id": passage["source_id"],
                "source_hash": digest,
            })
    missing = [item for item in packet.get("requires_prior") or [] if item not in set(prior_propositions)]
    if missing:
        return _unknown(packet, seed, injections, "missing_prior")
    by_subject: dict[str, list[dict[str, str]]] = {}
    for fact in facts:
        if fact["subject"] not in packet["subjects"]:
            continue
        by_subject.setdefault(fact["subject"], []).append(fact)
    if len(by_subject) != len(packet["subjects"]):
        return _unknown(packet, seed, injections, "unsupported")
    claims = []
    for subject in packet["subjects"]:
        group = by_subject[subject]
        propositions = {item["proposition"] for item in group}
        if len(propositions) != 1:
            return _unknown(packet, seed, injections, "conflict")
        fact = group[0]
        claims.append({
            "proposition": fact["proposition"],
            "source_ids": [fact["source_id"]],
            "source_hashes": [fact["source_hash"]],
        })
    return {
        "label": "SYNTHETIC",
        "packet_id": packet["packet_id"],
        "seed": seed,
        "verdict": "CLAIMS",
        "reason": "supported",
        "claims": claims,
        "injections_ignored": injections,
        "scope_id": packet["packet_id"],
        "act_called": False,
    }
