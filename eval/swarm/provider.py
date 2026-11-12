"""Pluggable completion interface.

Shipped implementations are the deterministic mock and a local open-weights
runner. Hosted or paid providers are refused. No API key is read.
"""
from __future__ import annotations

import hashlib
from typing import Any


class ProviderRefused(Exception):
    """A provider was requested and no call was made."""


class MockProvider:
    name = "mock"

    def complete(self, prompt: str, *, seed: int, max_tokens: int) -> dict[str, Any]:
        digest = hashlib.sha256(f"{seed}\n{max_tokens}\n{prompt}".encode("utf-8")).hexdigest()
        return {
            "provider": self.name,
            "seed": seed,
            "max_tokens": max_tokens,
            "digest": digest,
            "text": "",
            "network_call": False,
            "money_spent": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }


def _money_cap_is_number(cap: Any) -> bool:
    return type(cap) in (int, float)


def load_provider(config: dict[str, Any] | None = None):
    """Return mock or local, or refuse before any call.

    ``local`` is allowed only when ``money_cap`` is numeric 0. Any other
    provider name is treated as hosted or paid and is refused even if a money
    cap is present. No hosted implementation is shipped.
    """
    if config is None:
        return MockProvider()
    name = config.get("provider", "mock")
    if name in (None, "", "mock"):
        return MockProvider()
    cap = config.get("money_cap", None)
    if name == "local":
        if not _money_cap_is_number(cap) or cap != 0:
            raise ProviderRefused(
                "local provider refused: money_cap must be 0; no call was made"
            )
        from eval.swarm.local_provider import LocalProvider

        return LocalProvider()
    if not _money_cap_is_number(cap) or cap < 0:
        raise ProviderRefused(
            "hosted/paid provider refused: an explicit provider name and money cap are required; no call was made"
        )
    raise ProviderRefused(
        f"hosted/paid provider {name!r} is refused; not shipped; no call was made"
    )
