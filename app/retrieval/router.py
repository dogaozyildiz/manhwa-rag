"""Decide which corpus (or both) a question needs.

Routing is rule-based rather than an LLM call, for the same reasons as filter
extraction: deterministic, free, instant, and unit-testable. The signals are
strong enough that a model adds cost without adding accuracy.

The three routes:

* **catalogue** — about specific series. "under 100 chapters", a title, a genre.
* **industry** — about the business. Publishers, platforms, formats, history.
* **both** — comparative or contextual questions that need series facts *and*
  industry framing ("do manhwa run longer than manga, and why?").

When the signal is genuinely ambiguous, route to `both` and let retrieval
decide. Retrieving from the wrong corpus produces a confident answer from
irrelevant sources; retrieving from both costs a few extra rows.
"""

from __future__ import annotations

import re
from typing import Literal

from app.retrieval.filters import CatalogueFilters

Route = Literal["catalogue", "industry", "both"]

# Business/meta vocabulary: about the industry, not about a story.
INDUSTRY_TERMS = [
    "industry", "publisher", "publishers", "publishing", "platform", "platforms",
    "revenue", "monetise", "monetize", "monetisation", "business model",
    "market", "sales", "profit", "subscription", "royalties", "licensing",
    "licensed", "serialisation", "serialization", "magazine", "imprint",
    "scanlation", "piracy", "copyright", "adaptation", "adapted",
    "demographic", "shonen", "shōnen", "shojo", "shōjo", "seinen", "josei",
    "history", "originated", "origin of", "difference between",
    # "webtoon" is a format and platform name. It is an industry signal here
    # even though it is deliberately NOT an origin filter in filters.py — a
    # question *about* webtoons is about the medium, whereas a catalogue query
    # for Korean series says "manhwa". When both signals appear, the presence of
    # hard structured filters still wins below.
    "vertical scroll", "webtoon", "webtoon format",
    "naver", "kakao", "lezhin", "tapas",
    "shueisha", "kodansha", "shogakukan", "jump",
    "compared to", "versus", " vs ",
]

# Generic question openers are NOT industry signals. "What is X about?" is an
# alias lookup when X is a title, and treating the opener as an industry marker
# sent "What is Na Honjaman Level Up about?" to the articles corpus, where Solo
# Leveling does not exist. They only count alongside a real industry term.
WEAK_INDUSTRY_TERMS = ["what is", "what are", "how does", "why do", "why does"]

# Catalogue signals: asking for series, not context.
CATALOGUE_TERMS = [
    "recommend", "recommendation", "similar to", "like ", "suggest",
    "list", "show me", "find me", "which series", "what series",
    "chapters", "completed", "ongoing", "finished", "rated", "score",
]


def _hits(text: str, terms: list[str]) -> int:
    lowered = text.lower()
    return sum(
        1
        for term in terms
        if (term in lowered if not term.strip().isalpha()
            else re.search(rf"\b{re.escape(term)}\b", lowered) is not None)
    )


def route_query(query: str, filters: CatalogueFilters) -> Route:
    industry = _hits(query, INDUSTRY_TERMS)
    catalogue = _hits(query, CATALOGUE_TERMS)

    # A weak opener reinforces an existing industry signal but never creates one
    # on its own.
    if industry:
        industry += _hits(query, WEAK_INDUSTRY_TERMS)

    # Structured filters are the strongest catalogue signal there is: nobody
    # asks "under 100 chapters" about the publishing industry.
    if not filters.is_empty():
        has_hard_filter = any(
            [
                filters.max_chapters, filters.min_chapters, filters.status,
                filters.genres, filters.exclude_genres, filters.min_score,
                filters.min_year, filters.max_year,
            ]
        )
        if has_hard_filter:
            return "both" if industry >= 2 else "catalogue"
        # A bare country filter ("korean") is weak — it appears in industry
        # questions ("the Korean industry") as readily as catalogue ones.

    if industry and not catalogue:
        return "industry"
    if catalogue and not industry:
        return "catalogue"
    if industry and catalogue:
        return "both"
    # No signal either way: comparative and open questions are more often about
    # context than about a specific series.
    return "both"
