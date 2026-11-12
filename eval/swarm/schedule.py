"""Ready-wave schedule. Packet order inside a wave is packet_id, not a random id."""
from __future__ import annotations

from typing import Any


def waves(packets: list[dict[str, Any]], pool: int) -> list[list[dict[str, Any]]]:
    if pool < 1:
        raise ValueError("pool must be at least 1")
    remaining = list(packets)
    done: set[str] = set()
    planned: list[list[dict[str, Any]]] = []
    while remaining:
        ready = [
            packet for packet in remaining
            if all(dep in done for dep in packet["depends_on"])
        ]
        ready.sort(key=lambda packet: packet["packet_id"])
        if not ready:
            raise ValueError("packet graph is not a DAG")
        wave = ready[:pool]
        planned.append(wave)
        for packet in wave:
            done.add(packet["packet_id"])
            remaining.remove(packet)
    return planned
