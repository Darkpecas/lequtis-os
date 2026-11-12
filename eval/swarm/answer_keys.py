"""Held-out grader keys. Workers are not given this module.

This is a code-level holdout: the worker function does not receive these
records. It is not an operating-system access boundary.
"""
from __future__ import annotations

from typing import Any


def keys() -> dict[str, dict[str, Any]]:
    return {
        "syn-01": {
            "unknown": False,
            "acceptable_propositions": ["beacon color = amber", "dock count = 4"],
        },
        "syn-02": {
            "unknown": False,
            "acceptable_propositions": ["beacon = north"],
        },
        "syn-03": {
            "unknown": False,
            "acceptable_propositions": ["route = follow the north beacon"],
        },
        "syn-04": {
            "unknown": False,
            "acceptable_propositions": ["eta = two days"],
        },
        "syn-05": {"unknown": True, "acceptable_propositions": []},
        "syn-06": {"unknown": True, "acceptable_propositions": []},
        "syn-07": {
            "unknown": False,
            "acceptable_propositions": ["motto = hold fast"],
        },
        "syn-08": {
            "unknown": False,
            "acceptable_propositions": ["signal = steady"],
        },
    }
