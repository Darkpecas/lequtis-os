"""Identical hard budget ledger. Reservations are one SQLite update."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

# Preregistered in eval/swarm/PREREGISTRATION.md. Every arm uses this cap per task.
CAP = {"tokens": 180, "tool_calls": 12, "wall_ms": 120}
POOL = 3

COST = {
    "plan": {"tokens": 8, "tool_calls": 0, "wall_ms": 5},
    "worker": {"tokens": 24, "tool_calls": 1, "wall_ms": 20},
    "synthesize": {"tokens": 16, "tool_calls": 0, "wall_ms": 10},
    "verify": {"tokens": 12, "tool_calls": 1, "wall_ms": 8},
    "lease": {"tokens": 4, "tool_calls": 1, "wall_ms": 6},
}

# Local-model run only. Tool calls and simulated wall stay on the mock schedule.
# The token cap is larger so one real completion fits, and it is the same for every arm.
LOCAL_CALL_TOKEN_BUDGET = 800
LOCAL_CAP = {"tokens": 3072, "tool_calls": 12, "wall_ms": 120}
LOCAL_COST = {
    "plan": dict(COST["plan"]),
    "worker": {"tokens": LOCAL_CALL_TOKEN_BUDGET, "tool_calls": 1, "wall_ms": COST["worker"]["wall_ms"]},
    "synthesize": dict(COST["synthesize"]),
    "verify": dict(COST["verify"]),
    "lease": dict(COST["lease"]),
}


def add_costs(*parts: dict[str, int]) -> dict[str, int]:
    total = {"tokens": 0, "tool_calls": 0, "wall_ms": 0}
    for part in parts:
        for key in total:
            total[key] += int(part[key])
    return total


class ScheduleClock:
    """Deterministic schedule length. This is not process wall time."""

    def __init__(self) -> None:
        self.ms = 0

    def serial(self, duration_ms: int) -> None:
        if duration_ms < 0:
            raise ValueError("negative duration")
        self.ms += duration_ms

    def parallel(self, durations_ms: list[int]) -> None:
        if not durations_ms:
            return
        if any(item < 0 for item in durations_ms):
            raise ValueError("negative duration")
        self.ms += max(durations_ms)


class Budget:
    def __init__(self, path: Path, cap: dict[str, int] | None = None) -> None:
        self.path = Path(path)
        self.cap = dict(CAP if cap is None else cap)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = self._connect()
        try:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS task_budget (
                    task_id TEXT PRIMARY KEY,
                    tokens INTEGER NOT NULL DEFAULT 0,
                    tool_calls INTEGER NOT NULL DEFAULT 0,
                    wall_ms INTEGER NOT NULL DEFAULT 0,
                    tokens_cap INTEGER NOT NULL,
                    tool_calls_cap INTEGER NOT NULL,
                    wall_ms_cap INTEGER NOT NULL
                )
                """
            )
            db.commit()
        finally:
            db.close()
        self.refusals: list[dict[str, Any]] = []

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def reserve(self, task_id: str, cost: dict[str, int]) -> bool:
        tokens = int(cost["tokens"])
        tool_calls = int(cost["tool_calls"])
        wall_ms = int(cost["wall_ms"])
        if tokens < 0 or tool_calls < 0 or wall_ms < 0:
            raise ValueError("negative reservation")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """
                INSERT OR IGNORE INTO task_budget
                (task_id,tokens,tool_calls,wall_ms,tokens_cap,tool_calls_cap,wall_ms_cap)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    task_id, 0, 0, 0,
                    self.cap["tokens"], self.cap["tool_calls"], self.cap["wall_ms"],
                ),
            )
            updated = db.execute(
                """
                UPDATE task_budget
                SET tokens=tokens+?, tool_calls=tool_calls+?, wall_ms=wall_ms+?
                WHERE task_id=?
                  AND tokens+?<=tokens_cap
                  AND tool_calls+?<=tool_calls_cap
                  AND wall_ms+?<=wall_ms_cap
                """,
                (
                    tokens, tool_calls, wall_ms, task_id,
                    tokens, tool_calls, wall_ms,
                ),
            ).rowcount
            if updated != 1:
                db.execute("ROLLBACK")
                self.refusals.append({"task_id": task_id, "cost": {
                    "tokens": tokens, "tool_calls": tool_calls, "wall_ms": wall_ms,
                }})
                return False
            db.execute("COMMIT")
            return True
        finally:
            db.close()

    def spent(self, task_id: str | None = None) -> dict[str, int]:
        db = self._connect()
        try:
            if task_id is None:
                row = db.execute(
                    "SELECT COALESCE(SUM(tokens),0), COALESCE(SUM(tool_calls),0), COALESCE(SUM(wall_ms),0) FROM task_budget"
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT tokens, tool_calls, wall_ms FROM task_budget WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                if row is None:
                    return {"tokens": 0, "tool_calls": 0, "wall_ms": 0}
            return {"tokens": row[0], "tool_calls": row[1], "wall_ms": row[2]}
        finally:
            db.close()
