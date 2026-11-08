#!/usr/bin/env python3
"""
Skills lifecycle — LeQutis-owned, model-independent.

States (forward-only except retire from any non-retired):
  PROPOSED -> SANDBOXED -> ENABLED -> RETIRED

Workers may propose skill text; only this module mutates the skills table.

Promotion requires structured test and admission receipts bound to the skill
ID, version, and tested artifact. Receipts are caller-supplied records: this
module validates their shape and linkage but does not itself execute skill
code or authenticate the receipt issuer.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Callable

SKILL_STATUSES = ("PROPOSED", "SANDBOXED", "ENABLED", "RETIRED")
TRANSITIONS = {
    "PROPOSED": frozenset({"SANDBOXED", "RETIRED"}),
    "SANDBOXED": frozenset({"ENABLED", "RETIRED"}),
    "ENABLED": frozenset({"RETIRED"}),
    "RETIRED": frozenset(),
}


def _decode_evidence(raw: str | None) -> dict[str, Any]:
    try:
        evidence = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("stored skill evidence is invalid") from exc
    if not isinstance(evidence, dict):
        raise ValueError("stored skill evidence must be an object")
    return evidence


def _validate_test_receipt(
    receipt: Any, *, skill_id: str, version: str
) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise ValueError("SANDBOXED requires a test_receipt object")
    if receipt.get("status") != "PASS":
        raise ValueError("SANDBOXED requires a passing test receipt")
    if receipt.get("skill_id") != skill_id:
        raise ValueError("test receipt skill_id does not match candidate")
    if receipt.get("skill_version") != version:
        raise ValueError("test receipt skill_version does not match candidate")
    if (
        not isinstance(receipt.get("test_run_id"), str)
        or not receipt["test_run_id"].strip()
    ):
        raise ValueError("test receipt requires test_run_id")
    if receipt.get("isolated") is not True:
        raise ValueError("test receipt must attest isolated execution")
    artifact_hash = receipt.get("artifact_sha256")
    if not isinstance(artifact_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", artifact_hash
    ):
        raise ValueError("test receipt requires a lowercase SHA-256 artifact hash")
    return receipt


def _receipt_hash(receipt: dict[str, Any]) -> str:
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_admission_receipt(
    receipt: Any,
    *,
    skill_id: str,
    version: str,
    test_receipt: dict[str, Any],
) -> None:
    if not isinstance(receipt, dict):
        raise ValueError("ENABLED requires an admission_receipt object")
    if receipt.get("decision") != "APPROVED":
        raise ValueError("ENABLED requires an approved admission receipt")
    if receipt.get("skill_id") != skill_id:
        raise ValueError("admission receipt skill_id does not match candidate")
    if receipt.get("skill_version") != version:
        raise ValueError("admission receipt skill_version does not match candidate")
    for field in ("review_id", "reviewer_id"):
        if not isinstance(receipt.get(field), str) or not receipt[field].strip():
            raise ValueError(f"admission receipt requires {field}")
    if receipt.get("test_receipt_sha256") != _receipt_hash(test_receipt):
        raise ValueError("admission receipt does not bind to the stored test receipt")


def propose_skill(
    *,
    name: str,
    version: str = "0.1.0",
    evidence: dict[str, Any] | None = None,
    connect: Callable,
    now: Callable[[], str],
    event: Callable[[str, dict[str, Any]], Any],
) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("skill name required")
    sid = str(uuid.uuid4())
    ts = now()
    evidence_s = json.dumps(evidence or {}, sort_keys=True)
    with connect() as db:
        db.execute(
            """
            INSERT INTO skills(id,name,version,status,evidence,created,updated)
            VALUES (?,?,?,?,?,?,?)
            """,
            (sid, name, version, "PROPOSED", evidence_s, ts, ts),
        )
    event(
        "skill.proposed",
        {"id": sid, "name": name, "version": version},
    )
    return sid


def advance_skill(
    skill_id: str,
    new_status: str,
    *,
    connect: Callable,
    now: Callable[[], str],
    event: Callable[[str, dict[str, Any]], Any],
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    new_status = new_status.upper()
    if new_status not in SKILL_STATUSES:
        raise ValueError(f"invalid skill status: {new_status}")
    with connect() as db:
        row = db.execute(
            "SELECT id,name,version,status,evidence FROM skills WHERE id=?",
            (skill_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"skill not found: {skill_id}")
        current = row["status"]
        allowed = TRANSITIONS.get(current, frozenset())
        if new_status not in allowed:
            raise ValueError(
                f"illegal transition {current} -> {new_status}"
            )
        existing = _decode_evidence(row["evidence"])
        if evidence is not None and not isinstance(evidence, dict):
            raise ValueError("evidence must be an object")
        merged = {**existing, **(evidence or {})}

        if (
            current != "PROPOSED"
            and "test_receipt" in (evidence or {})
            and evidence["test_receipt"] != existing.get("test_receipt")
        ):
            raise ValueError("stored test receipt is immutable after sandboxing")
        if (
            current == "ENABLED"
            and "admission_receipt" in (evidence or {})
            and evidence["admission_receipt"] != existing.get("admission_receipt")
        ):
            raise ValueError("stored admission receipt is immutable after enablement")

        test_receipt = None
        if current == "PROPOSED" and new_status == "SANDBOXED":
            test_receipt = _validate_test_receipt(
                merged.get("test_receipt"),
                skill_id=skill_id,
                version=row["version"],
            )
        elif current == "SANDBOXED" and new_status == "ENABLED":
            # The sandboxed test receipt is immutable during admission.
            test_receipt = _validate_test_receipt(
                existing.get("test_receipt"),
                skill_id=skill_id,
                version=row["version"],
            )
            _validate_admission_receipt(
                merged.get("admission_receipt"),
                skill_id=skill_id,
                version=row["version"],
                test_receipt=test_receipt,
            )

        ts = now()
        evidence_s = json.dumps(merged, sort_keys=True)
        db.execute(
            "UPDATE skills SET status=?, evidence=?, updated=? WHERE id=?",
            (new_status, evidence_s, ts, skill_id),
        )
    event(
        "skill.advanced",
        {
            "id": skill_id,
            "name": row["name"],
            "from": current,
            "to": new_status,
        },
    )
    return {"id": skill_id, "from": current, "to": new_status}


def list_skills(
    *,
    connect: Callable,
    status: str | None = None,
) -> list[dict[str, Any]]:
    with connect() as db:
        if status:
            rows = db.execute(
                """
                SELECT id,name,version,status,evidence,created,updated
                FROM skills WHERE status=? ORDER BY created ASC
                """,
                (status.upper(),),
            ).fetchall()
        else:
            rows = db.execute(
                """
                SELECT id,name,version,status,evidence,created,updated
                FROM skills ORDER BY created ASC
                """
            ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["evidence"] = json.loads(item["evidence"] or "{}")
        except json.JSONDecodeError:
            pass
        out.append(item)
    return out


def get_skill(*, connect: Callable, skill_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            """
            SELECT id,name,version,status,evidence,created,updated
            FROM skills WHERE id=?
            """,
            (skill_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["evidence"] = json.loads(item["evidence"] or "{}")
    except json.JSONDecodeError:
        pass
    return item
