#!/usr/bin/env python3
"""
Skills lifecycle — LeQutis-owned, model-independent.

States (forward-only except retire from any non-retired):
  PROPOSED -> SANDBOXED -> ENABLED -> RETIRED

Workers may propose skill text; only this module mutates the skills table.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable

SKILL_STATUSES = ("PROPOSED", "SANDBOXED", "ENABLED", "RETIRED")
TRANSITIONS = {
    "PROPOSED": frozenset({"SANDBOXED", "RETIRED"}),
    "SANDBOXED": frozenset({"ENABLED", "RETIRED"}),
    "ENABLED": frozenset({"RETIRED"}),
    "RETIRED": frozenset(),
}


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
            "SELECT id,name,status,evidence FROM skills WHERE id=?",
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
        ts = now()
        if evidence is not None:
            merged = json.loads(row["evidence"] or "{}")
            if not isinstance(merged, dict):
                merged = {"prior": merged}
            merged.update(evidence)
            evidence_s = json.dumps(merged, sort_keys=True)
            db.execute(
                "UPDATE skills SET status=?, evidence=?, updated=? WHERE id=?",
                (new_status, evidence_s, ts, skill_id),
            )
        else:
            db.execute(
                "UPDATE skills SET status=?, updated=? WHERE id=?",
                (new_status, ts, skill_id),
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
