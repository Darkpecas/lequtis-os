"""Pluggable completion interface. The only shipped implementation is the mock."""
from __future__ import annotations

import hashlib
from typing import Any


class ProviderRefused(Exception):
    """A real provider was requested and no call was made."""


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
        }


def load_provider(config: dict[str, Any] | None = None) -> MockProvider:
    """Return the mock, or refuse before any network call.

    A real provider name is refused even when the caller supplies a money cap.
    No real provider implementation is shipped.
    """
    if config is None:
        return MockProvider()
    name = config.get("provider", "mock")
    if name in (None, "", "mock"):
        return MockProvider()
    cap = config.get("money_cap", None)
    if type(cap) not in (int, float) or cap < 0:
        raise ProviderRefused(
            "real provider refused: an explicit provider name and money cap are required; no call was made"
        )
    raise ProviderRefused(
        f"real provider {name!r} is not shipped; no network call was made"
    )
