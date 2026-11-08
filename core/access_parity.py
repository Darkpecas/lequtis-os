#!/usr/bin/env python3
"""
ACCESS / SOURCES / LIVE_LOOP gate ID parity checker (G11).

Evidence-only: reports mismatches; does not invent live routes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_yaml_simple(path: Path) -> dict[str, Any]:
    """Minimal YAML subset loader for our manifests (no nested complexity)."""
    try:
        import yaml  # type: ignore

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except ImportError:
        return _parse_simple_manifest(path.read_text(encoding="utf-8"))


def _parse_simple_manifest(text: str) -> dict[str, Any]:
    """
    Fallback parser for ACCESS_*.yaml shaped lists of `- id:` / `- principal:`.
    Sufficient for parity IDs when PyYAML is unavailable.
    """
    result: dict[str, Any] = {"principals": [], "stores": [], "routes": [], "matrix": []}
    section = None
    current: dict[str, Any] | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" ") and line.endswith(":"):
            key = line[:-1].strip()
            if key in result:
                section = key
                current = None
            continue
        if section is None:
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            current = {}
            result[section].append(current)
            rest = stripped[2:]
            if ":" in rest:
                k, v = rest.split(":", 1)
                current[k.strip()] = v.strip().strip('"').strip("'")
        elif current is not None and ":" in stripped:
            k, v = stripped.split(":", 1)
            current[k.strip()] = v.strip().strip('"').strip("'")
    return result


def check_access_parity(root: Path) -> dict[str, Any]:
    knowledge = root / "knowledge"
    manifest = _load_yaml_simple(knowledge / "ACCESS_MANIFEST.yaml")
    matrix = _load_yaml_simple(knowledge / "ACCESS_MATRIX.yaml")
    sources = json.loads((knowledge / "SOURCES.json").read_text(encoding="utf-8"))
    gates = json.loads(
        (knowledge / "LIVE_LOOP_GATES.json").read_text(encoding="utf-8")
    )

    store_ids = {s.get("id") for s in manifest.get("stores") or [] if s.get("id")}
    route_ids = {r.get("id") for r in manifest.get("routes") or [] if r.get("id")}
    principal_ids = {
        p.get("id") for p in manifest.get("principals") or [] if p.get("id")
    }
    source_ids = {s.get("id") for s in sources.get("sources") or [] if s.get("id")}
    gate_ids = [g.get("id") for g in gates.get("gates") or [] if g.get("id")]

    matrix_principals = {
        m.get("principal") for m in matrix.get("matrix") or [] if m.get("principal")
    }
    matrix_resources = {
        m.get("resource") for m in matrix.get("matrix") or [] if m.get("resource")
    }

    issues: list[dict[str, str]] = []

    # Sources that describe durable stores should appear in ACCESS_MANIFEST.stores
    expected_store_overlap = {
        "github_lequtis_os",
        "google_docs",
        "google_drive",
        "icloud",
        "chatgpt",
        "gemini",
        "notebook_lm",
        "obsidian",
        "personal_graph_sops",
    }
    missing_in_manifest = sorted(
        (source_ids & expected_store_overlap) - store_ids
    )
    missing_in_sources = sorted(
        (store_ids & expected_store_overlap) - source_ids
    )
    for sid in missing_in_manifest:
        issues.append(
            {
                "kind": "store_missing_in_manifest",
                "id": sid,
            }
        )
    for sid in missing_in_sources:
        issues.append(
            {
                "kind": "store_missing_in_sources",
                "id": sid,
            }
        )

    for pid in sorted(matrix_principals - principal_ids):
        issues.append({"kind": "matrix_principal_unknown", "id": pid})

    required_routes = {
        "local_kernel_loop",
        "hermes_stdio_connector",
        "hermes_hostinger",
        "chatgpt_to_hermes_bridge",
        "cognitive_workers",
        "independent_verifier",
        "skills_lifecycle",
    }
    for rid in sorted(required_routes - route_ids):
        issues.append({"kind": "route_missing", "id": rid})

    required_gates = {
        "G01_recover_stdio_connector",
        "G02_chatgpt_hermes_route",
        "G03_hermes_probe_receipt",
        "G04_canonical_state_read",
        "G05_persist_intent_ids",
        "G06_hermes_harmless_task",
        "G07_independent_verifier",
        "G08_canonical_observe_eval",
        "G09_idempotent_replay",
        "G10_fresh_session_continuity",
        "G11_access_manifest_parity",
        "G12_tbq_doc_signoff",
    }
    missing_gates = sorted(required_gates - set(gate_ids))
    for gid in missing_gates:
        issues.append({"kind": "gate_missing", "id": gid})

    required_matrix_resources = {
        "github_lequtis_os_read",
        "github_lequtis_os_write",
        "google_drive_mcp",
        "local_lequtis_kernel",
        "hermes_stdio_connector_local",
        "hermes_hostinger",
    }
    for rid in sorted(required_matrix_resources - matrix_resources):
        issues.append({"kind": "matrix_resource_missing", "id": rid})

    ok = len(issues) == 0
    return {
        "ok": ok,
        "issues": issues,
        "counts": {
            "stores": len(store_ids),
            "routes": len(route_ids),
            "principals": len(principal_ids),
            "sources": len(source_ids),
            "gates": len(gate_ids),
            "matrix_rows": len(matrix.get("matrix") or []),
        },
        "gate_ids": gate_ids,
        "route_ids": sorted(route_ids),
        "store_ids": sorted(store_ids),
    }
