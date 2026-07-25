"""LLM provider interface.

Generation is the one piece of this system that needs an account, so it is the
one piece kept behind an interface. Swapping Gemini for a local Ollama model, or
for Claude if a key ever exists, is a new implementation of `complete_json` —
not a change to prompting, retrieval, verification, or evaluation.

That boundary is also what lets the citation guarantee be provider-agnostic:
verification happens on our side, on the returned quotes, regardless of which
model produced them.
"""

from __future__ import annotations

from typing import Any, Protocol


class LLMProvider(Protocol):
    name: str

    async def complete_json(
        self, system: str, user: str, schema: dict[str, Any]
    ) -> tuple[dict, dict]:
        """Return (parsed_json, usage). Must raise on unparseable output."""
        ...


class ProviderError(RuntimeError):
    """Raised when the provider is unusable — missing key, quota, bad output."""


def get_provider() -> LLMProvider:
    """Construct the configured provider.

    Deliberately fails with an actionable message rather than falling back to a
    stub: a silent fallback would make an unconfigured system look like a
    working one, and the eval numbers would be meaningless.
    """
    from app.answer.gemini import GeminiProvider

    return GeminiProvider()
