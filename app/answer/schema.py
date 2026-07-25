from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Claim:
    """One statement in the answer, with the quote that supports it.

    `verified` is set by `app.answer.verify`, never by the model. A model can
    assert anything about its own sources; the only trustworthy signal is
    whether the quote it produced actually occurs in the text it named.
    """

    text: str
    quote: str
    ref: str
    verified: bool = False
    # Present only when verification failed — kept for the eval report and the
    # debug UI, so a caught hallucination is visible rather than merely absent.
    reason: str | None = None

    @property
    def source_title(self) -> str:
        return self.ref.split(":", 1)[-1]


@dataclass(frozen=True)
class Answer:
    text: str
    claims: list[Claim]
    sources: list[dict]
    refused: bool
    latency_ms: int
    model: str
    # Filters the retrieval layer actually applied, surfaced so a user can see
    # why a result set is what it is.
    applied_filters: list[str] = field(default_factory=list)
    route: str = "catalogue"
    usage: dict = field(default_factory=dict)

    @property
    def verified_claims(self) -> list[Claim]:
        return [c for c in self.claims if c.verified]

    @property
    def rejected_claims(self) -> list[Claim]:
        return [c for c in self.claims if not c.verified]

    @property
    def groundedness(self) -> float | None:
        """Share of claims whose quote was found in its cited source."""
        if not self.claims:
            return None
        return len(self.verified_claims) / len(self.claims)
