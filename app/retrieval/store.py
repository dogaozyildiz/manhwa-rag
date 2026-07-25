"""Shared retrieval types.

Both corpora resolve to a single `Source` type. That matters because the answer
layer and the citation verifier should not care whether a fact came from a
catalogue record or an industry article — a quote is verified against
`source.text` the same way either way, and one code path means one place for
that guarantee to hold.

`kind` is kept so the UI can render a series as a card and an article as a
citation, and so the eval can score the two halves separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SourceKind = Literal["series", "article"]


@dataclass(frozen=True)
class Source:
    """One retrieved item, with everything needed to cite and display it."""

    # Stable identifier used in prompts and citations, e.g. "series:105398" or
    # "article:Manhwa". The model echoes this back to attribute a claim, and the
    # verifier uses it to look up the text a quote must appear in.
    ref: str
    kind: SourceKind
    title: str
    text: str
    score: float
    url: str | None = None
    # Which signal produced the hit: vector | trigram | lexical | fused | filter
    origin: str = "vector"
    # Display and eval extras — chapters, status, section heading, and so on.
    meta: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        section = self.meta.get("section")
        return f"{self.title} — {section}" if section else self.title


def reciprocal_rank_fusion(
    ranked_lists: list[list[Source]], *, k: int, damping: int = 60
) -> list[Source]:
    """Fuse ranked lists by rank position rather than by raw score.

    Trigram similarity, cosine similarity and ts_rank live on incomparable
    scales, so blending their raw values needs a normalisation constant that has
    to be retuned whenever the corpus changes. RRF consumes only rank positions,
    so it needs no tuning and cannot be broken by one retriever returning scores
    in an unexpected range.
    """
    scores: dict[str, float] = {}
    best: dict[str, Source] = {}

    for ranked in ranked_lists:
        for rank, source in enumerate(ranked, start=1):
            scores[source.ref] = scores.get(source.ref, 0.0) + 1.0 / (damping + rank)
            # Keep the first-seen copy; lists are passed in priority order.
            best.setdefault(source.ref, source)

    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]
    out: list[Source] = []
    for ref, fused in ordered:
        original = best[ref]
        out.append(
            Source(
                ref=original.ref,
                kind=original.kind,
                title=original.title,
                text=original.text,
                score=fused,
                url=original.url,
                origin="fused",
                meta=original.meta,
            )
        )
    return out
