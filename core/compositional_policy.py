"""Standalone fail-closed cross-tool policy gate; not wired into ACT."""
from dataclasses import dataclass
from typing import FrozenSet

@dataclass(frozen=True)
class ToolPolicy:
    name: str
    reads: FrozenSet[str]
    writes: FrozenSet[str]
    clearance: int
    egress: bool = False

@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    sensitivity: int

class Session:
    def __init__(self, task_id: str, allowed_tools: FrozenSet[str], max_clearance: int):
        if not task_id or max_clearance < 0:
            raise ValueError("Invalid task scope")
        self.task_id = task_id
        self.allowed_tools = frozenset(allowed_tools)
        self.max_clearance = max_clearance
        self.sensitivity = 0
        self.seen = []

    def authorize(self, policy: ToolPolicy, *, resource_level: int = 0) -> Decision:
        if policy.name not in self.allowed_tools:
            return Decision(False, "tool_not_delegated", self.sensitivity)
        if resource_level < 0 or policy.clearance < 0:
            return Decision(False, "invalid_classification", self.sensitivity)
        if resource_level > policy.clearance or resource_level > self.max_clearance:
            return Decision(False, "clearance_exceeded", self.sensitivity)
        candidate = max(self.sensitivity, resource_level)
        if policy.egress and candidate > 0:
            return Decision(False, "sensitive_egress_denied", self.sensitivity)
        if policy.egress and not policy.writes:
            return Decision(False, "egress_destination_missing", self.sensitivity)
        if not policy.reads and not policy.writes:
            return Decision(False, "undefined_effects", self.sensitivity)
        self.sensitivity = candidate
        self.seen.append(policy.name)
        return Decision(True, "allowed", self.sensitivity)
