#!/usr/bin/env python3
"""Load and validate knowledge/ROUTING_CONTRACT.json.

A tier may name a model only when that model's availability is VERIFIED.
This module does not call a model and does not open a network connection.

LOCAL PROOF, NOT LIVE VPS VERIFIED.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA = "lequtis-routing-contract-v1"
TIER_IDS = ("tier0", "tier1", "tier2", "tier3")
EVIDENCE_LABEL = "LOCAL PROOF, NOT LIVE VPS VERIFIED"


class RoutingContractError(Exception):
    """The contract is missing a tier or names a model that is not VERIFIED."""


def contract_path(root: Path | None = None) -> Path:
    base = root if root is not None else Path(__file__).resolve().parents[1]
    return base / "knowledge" / "ROUTING_CONTRACT.json"


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RoutingContractError(label + " must be a non-empty string")
    return value


def _https_sources(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise RoutingContractError("model sources must be a non-empty list")
    sources: list[str] = []
    for item in value:
        text = _nonempty_string(item, "model source")
        if not text.startswith("https://"):
            raise RoutingContractError("model source must be an https URL")
        sources.append(text)
    return sources


def validate(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise RoutingContractError("contract must be an object")
    if document.get("schema") != SCHEMA:
        raise RoutingContractError("unexpected contract schema")
    if document.get("evidence_label") != EVIDENCE_LABEL:
        raise RoutingContractError("evidence label must stay local-proof")
    tiers = document.get("tiers")
    if not isinstance(tiers, list) or [tier.get("id") if isinstance(tier, dict) else None for tier in tiers] != list(TIER_IDS):
        raise RoutingContractError("contract must contain tier0, tier1, tier2, tier3 in that order")
    for tier in tiers:
        _nonempty_string(tier.get("role"), tier["id"] + " role")
        _nonempty_string(tier.get("fallback"), tier["id"] + " fallback")
        _nonempty_string(tier.get("verifier_requirement"), tier["id"] + " verifier_requirement")
        for field in ("input_contract", "output_contract"):
            body = tier.get(field)
            if not isinstance(body, dict) or not body:
                raise RoutingContractError(tier["id"] + " " + field + " must be an object")
            _nonempty_string(body.get("summary"), tier["id"] + " " + field + " summary")
        models = tier.get("models")
        if not isinstance(models, list) or not models:
            raise RoutingContractError(tier["id"] + " needs at least one VERIFIED model")
        for model in models:
            if not isinstance(model, dict):
                raise RoutingContractError(tier["id"] + " model must be an object")
            _nonempty_string(model.get("name"), tier["id"] + " model name")
            if model.get("availability") != "VERIFIED":
                raise RoutingContractError(
                    "refusing model that is not VERIFIED: " + str(model.get("name"))
                )
            _https_sources(model.get("sources"))
    return document


def load(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise RoutingContractError("refusing to read a symlinked contract")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RoutingContractError("contract is unreadable") from exc
    return validate(document)
