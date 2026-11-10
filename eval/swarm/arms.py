"""Four arms. Kernel calls run serially so the result can be replayed.

simulated_makespan_ms applies the preregistered pool schedule. It is not
process wall time.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from eval.swarm.board import KernelBoard
from eval.swarm.budget import COST, POOL, Budget, ScheduleClock, add_costs
from eval.swarm.metrics import grade, safety_failures_for_record
from eval.swarm.provider import MockProvider
from eval.swarm.schedule import waves
from eval.swarm.worker import SideEffects, extract


def _priors(packet: dict[str, Any], completed: dict[str, dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for dep in packet["depends_on"]:
        for claim in completed[dep].get("claims") or []:
            found.append(claim["proposition"])
    return found


def _commit_record(
    board: KernelBoard,
    agenda_id: str,
    record: dict[str, Any],
    *,
    pull: bool,
) -> dict[str, Any]:
    claimed = board.claim() if pull else board.claim(agenda_id)
    if claimed.get("status") != "claimed":
        raise RuntimeError("claim failed: " + str(claimed))
    if not str(claimed.get("title", "")).endswith(record["packet_id"]):
        raise RuntimeError("pulled task was not the released packet: " + str(claimed))
    outcome = board.commit(claimed["execution_id"], claimed["lease_token"], record)
    if not outcome.get("accepted"):
        raise RuntimeError("commit rejected on the clean path: " + str(outcome))
    return outcome


def _arm_result(
    name: str,
    description: str,
    packets: list[dict[str, Any]],
    outputs: dict[str, dict[str, Any]],
    budget: Budget,
    clock: ScheduleClock,
    started: float,
    *,
    worker_calls: int,
    planned_worker_calls: int,
    safety: list[str],
    pull: bool,
) -> dict[str, Any]:
    graded = grade(packets, outputs)
    failures = list(safety)
    for packet in packets:
        failures.extend(safety_failures_for_record(packet, outputs.get(packet["packet_id"])))
    # Preserve order while dropping repeats.
    deduped: list[str] = []
    for item in failures:
        if item not in deduped:
            deduped.append(item)
    spent = budget.spent()
    return {
        "arm": name,
        "description": description,
        "pull_allocation": pull,
        "partition_tolerant": False,
        "metrics": {
            **graded,
            "simulated_makespan_ms": clock.ms,
            "process_wall_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "tokens": spent["tokens"],
            "tool_calls": spent["tool_calls"],
            "reserved_wall_ms": spent["wall_ms"],
            "worker_calls": worker_calls,
            "planned_worker_calls": planned_worker_calls,
            "duplicate_work": max(0, worker_calls - planned_worker_calls),
            "recovery_time_ms": None,
        },
        "safety_failures": deduped,
        "safety": "FAILED" if deduped else "PASS",
        "outputs": {
            packet_id: {
                "verdict": record.get("verdict"),
                "reason": record.get("reason"),
                "scope_id": record.get("scope_id"),
                "claims": record.get("claims"),
                "injections_ignored": record.get("injections_ignored"),
            }
            for packet_id, record in outputs.items()
        },
    }


def _run(
    name: str,
    description: str,
    packets: list[dict[str, Any]],
    budget: Budget,
    board: KernelBoard,
    provider: MockProvider,
    seed: int,
    *,
    pool: int,
    pull: bool,
    cost_for: Callable[[int], dict[str, int]],
    advance: Callable[[ScheduleClock, int], None],
    produce: Callable[[dict[str, Any], list[str]], tuple[dict[str, Any], int]],
) -> dict[str, Any]:
    started = time.perf_counter()
    clock = ScheduleClock()
    completed: dict[str, dict[str, Any]] = {}
    safety: list[str] = []
    worker_calls = 0
    planned = 0
    for wave in waves(packets, pool):
        sized = len(wave)
        for packet in wave:
            planned_cost = cost_for(sized)
            if not budget.reserve(packet["packet_id"], planned_cost):
                safety.append("overspend")
                continue
            record, calls = produce(packet, _priors(packet, completed))
            worker_calls += calls
            planned += calls
            agenda_id = board.add_goal(packet["packet_id"])
            _commit_record(board, agenda_id, record, pull=pull)
            completed[packet["packet_id"]] = record
        if not any(packet["packet_id"] in completed for packet in wave):
            continue
        advance(clock, sized if all(packet["packet_id"] in completed for packet in wave) else 0)
        if safety:
            break
    return _arm_result(
        name, description, packets, completed, budget, clock, started,
        worker_calls=worker_calls,
        planned_worker_calls=planned,
        safety=safety,
        pull=pull,
    )


def _one(packet: dict[str, Any], prior: list[str], provider: MockProvider, seed: int) -> dict[str, Any]:
    return extract(packet, prior, seed, provider, SideEffects())


def run_arm_a(packets, budget, board, provider, seed) -> dict[str, Any]:
    cost = add_costs(COST["plan"], COST["worker"], COST["verify"])

    def produce(packet: dict[str, Any], prior: list[str]) -> tuple[dict[str, Any], int]:
        return _one(packet, prior, provider, seed), 1

    def advance(clock: ScheduleClock, size: int) -> None:
        if size:
            clock.serial(COST["plan"]["wall_ms"] + COST["worker"]["wall_ms"] + COST["verify"]["wall_ms"])

    return _run(
        "A",
        "Single worker, tasks in dependency order.",
        packets, budget, board, provider, seed,
        pool=1, pull=False, cost_for=lambda _size: cost, advance=advance, produce=produce,
    )


def run_arm_b(packets, budget, board, provider, seed) -> dict[str, Any]:
    cost = add_costs(
        COST["plan"], COST["worker"], COST["worker"], COST["worker"],
        COST["synthesize"], COST["verify"],
    )
    # Wall reserved for the task is the critical path, not three serial workers.
    cost = {
        "tokens": cost["tokens"],
        "tool_calls": cost["tool_calls"],
        "wall_ms": (
            COST["plan"]["wall_ms"] + COST["worker"]["wall_ms"]
            + COST["synthesize"]["wall_ms"] + COST["verify"]["wall_ms"]
        ),
    }

    def produce(packet: dict[str, Any], prior: list[str]) -> tuple[dict[str, Any], int]:
        blind = [_one(packet, prior, provider, seed + offset) for offset in (0, 1, 2)]
        return _synthesize(blind, packet), 3

    def advance(clock: ScheduleClock, size: int) -> None:
        if not size:
            return
        clock.serial(COST["plan"]["wall_ms"])
        clock.parallel([COST["worker"]["wall_ms"], COST["worker"]["wall_ms"], COST["worker"]["wall_ms"]])
        clock.serial(COST["synthesize"]["wall_ms"] + COST["verify"]["wall_ms"])

    return _run(
        "B",
        "Blind ensemble of 3 plus validating synthesis. Members do not see each other.",
        packets, budget, board, provider, seed,
        pool=1, pull=False, cost_for=lambda _size: cost, advance=advance, produce=produce,
    )


def _synthesize(records: list[dict[str, Any]], packet: dict[str, Any]) -> dict[str, Any]:
    verdicts = {record["verdict"] for record in records}
    scopes = {record["scope_id"] for record in records}
    if len(verdicts) != 1 or scopes != {packet["packet_id"]}:
        return {
            "label": "SYNTHETIC",
            "packet_id": packet["packet_id"],
            "seed": "ensemble",
            "verdict": "UNKNOWN",
            "reason": "synthesis_disagreement",
            "claims": [],
            "injections_ignored": sum(record["injections_ignored"] for record in records),
            "scope_id": packet["packet_id"],
            "act_called": any(record["act_called"] for record in records),
        }
    if verdicts == {"UNKNOWN"}:
        chosen = dict(records[0])
        chosen["seed"] = "ensemble"
        return chosen
    signatures = [
        tuple(sorted(claim["proposition"] for claim in record["claims"]))
        for record in records
    ]
    if len(set(signatures)) != 1:
        return {
            "label": "SYNTHETIC",
            "packet_id": packet["packet_id"],
            "seed": "ensemble",
            "verdict": "UNKNOWN",
            "reason": "synthesis_disagreement",
            "claims": [],
            "injections_ignored": sum(record["injections_ignored"] for record in records),
            "scope_id": packet["packet_id"],
            "act_called": False,
        }
    chosen = dict(records[0])
    chosen["seed"] = "ensemble"
    chosen["reason"] = "synthesized"
    return chosen


def run_arm_c(packets, budget, board, provider, seed) -> dict[str, Any]:
    cost = add_costs(COST["plan"], COST["worker"], COST["verify"])

    def produce(packet: dict[str, Any], prior: list[str]) -> tuple[dict[str, Any], int]:
        return _one(packet, prior, provider, seed), 1

    def advance(clock: ScheduleClock, size: int) -> None:
        if not size:
            return
        clock.serial(COST["plan"]["wall_ms"])
        clock.parallel([COST["worker"]["wall_ms"]] * size)
        clock.serial(COST["verify"]["wall_ms"])

    return _run(
        "C",
        "Central dynamic DAG scheduler. The scheduler claims each task by id.",
        packets, budget, board, provider, seed,
        pool=POOL, pull=False, cost_for=lambda _size: cost, advance=advance, produce=produce,
    )


def run_arm_d(packets, budget, board, provider, seed) -> dict[str, Any]:
    cost = add_costs(COST["lease"], COST["worker"], COST["lease"], COST["verify"])

    def produce(packet: dict[str, Any], prior: list[str]) -> tuple[dict[str, Any], int]:
        return _one(packet, prior, provider, seed), 1

    def advance(clock: ScheduleClock, size: int) -> None:
        if not size:
            return
        # Claims and commits serialize on one SQLite board. Worker bodies overlap.
        clock.serial(COST["lease"]["wall_ms"] * size)
        clock.parallel([COST["worker"]["wall_ms"]] * size)
        clock.serial(COST["lease"]["wall_ms"] * size)
        clock.serial(COST["verify"]["wall_ms"])

    return _run(
        "D",
        "Decentralized pull from one shared SQLite board. Not partition-tolerant infrastructure.",
        packets, budget, board, provider, seed,
        pool=POOL, pull=True, cost_for=lambda _size: cost, advance=advance, produce=produce,
    )


ARMS = {
    "A": run_arm_a,
    "B": run_arm_b,
    "C": run_arm_c,
    "D": run_arm_d,
}


def run_arm(name: str, packets, work_dir: Path, seed: int, provider: MockProvider | None = None) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    budget = Budget(work_dir / "budget.db")
    board = KernelBoard(work_dir / "board.db")
    return ARMS[name](packets, budget, board, provider or MockProvider(), seed)
