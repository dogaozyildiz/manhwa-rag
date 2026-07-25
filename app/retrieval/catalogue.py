"""Catalogue retrieval: structured filters × vector similarity × trigram titles.

Three signals, each covering the others' blind spot:

* **Filters** (SQL) — the only thing that can honour "under 100 chapters".
  Applied as a `WHERE` clause, so they *constrain* rather than merely influence.
* **Vector** — handles "similar to Solo Leveling", paraphrase, and theme.
* **Trigram** — handles aliases. "Kimetsu no Yaiba" and "Demon Slayer" share no
  tokens and embed some distance apart, but trigram-match the same record.

The ordering is the whole point: **filter first, then rank within the filtered
set**. Ranking first and filtering after would silently drop results whenever
the top-k happened to contain nothing matching the constraints, which is the
common failure of naive catalogue RAG — the user asks for completed series
under 100 chapters and gets an ongoing 900-chapter one, confidently.
"""

from __future__ import annotations

from sqlalchemy import Float, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.ingest.embedder import Embedder, get_embedder
from app.models import Series
from app.retrieval.filters import CatalogueFilters
from app.retrieval.store import Source, reciprocal_rank_fusion

# Below this word-similarity, a "match" is coincidental word overlap rather than
# an alias. Measured against the corpus rather than guessed:
#
#   exact aliases ("Kimetsu no Yaiba", "Sinui Tap")      1.000
#   typo ("kimetsu no yaba")                             0.875
#   missing space ("SoloLeveling")                       0.688
#   ---------------------------------------------------- 0.600  <- threshold
#   worst false positive ("pirate adventure manga",      0.478
#     which matched *JoJo's Bizarre Adventure* on the
#     single generic word "adventure")
#   other prose queries                                  0.22-0.25
#
# At the previous 0.45 the "adventure" collision passed, and five JoJo volumes
# outranked One Piece for "pirate adventure manga". 0.60 keeps genuine typos and
# spacing variants while excluding single-generic-word collisions.
TRIGRAM_THRESHOLD = 0.60


def _to_source(row: Series, score: float, origin: str) -> Source:
    return Source(
        ref=f"series:{row.anilist_id}",
        kind="series",
        title=row.display_title,
        text=row.card,
        score=score,
        url=row.site_url,
        origin=origin,
        meta={
            "anilist_id": row.anilist_id,
            "country": row.country,
            "status": row.status,
            "chapters": row.chapters,
            "start_year": row.start_year,
            "genres": row.genres,
            "average_score": row.average_score,
            "titles": row.titles,
        },
    )


def build_predicates(filters: CatalogueFilters) -> list[ColumnElement[bool]]:
    """Translate extracted filters into SQL predicates.

    Nullable columns need care: `chapters < 100` is NULL — and therefore false —
    for a series with unknown chapter count. That is the behaviour we want for
    an explicit numeric constraint (an unknown length cannot be asserted to be
    under 100), so no COALESCE here. It is a deliberate choice, not an oversight.
    """
    where: list[ColumnElement[bool]] = []

    if filters.country:
        where.append(Series.country == filters.country)
    if filters.status:
        where.append(Series.status == filters.status)
    if filters.min_chapters is not None:
        where.append(Series.chapters >= filters.min_chapters)
    if filters.max_chapters is not None:
        where.append(Series.chapters < filters.max_chapters)
    if filters.min_year is not None:
        where.append(Series.start_year >= filters.min_year)
    if filters.max_year is not None:
        where.append(Series.start_year < filters.max_year)
    if filters.min_score is not None:
        where.append(Series.average_score >= filters.min_score)
    if filters.genres:
        # @> : the row's genres must contain ALL requested genres.
        where.append(Series.genres.contains(filters.genres))
    if filters.exclude_genres:
        # && : overlap. Negated, so the row shares NONE of them.
        where.append(~Series.genres.overlap(filters.exclude_genres))

    return where


class CatalogueRetriever:
    def __init__(self, session: AsyncSession, embedder: Embedder | None = None) -> None:
        self._session = session
        self._explicit_embedder = embedder

    @property
    def _embedder(self) -> Embedder:
        # Lazy: loading the model costs seconds and memory, and filter-only or
        # trigram-only queries never need it.
        if self._explicit_embedder is None:
            self._explicit_embedder = get_embedder()
        return self._explicit_embedder

    async def count(self) -> int:
        return (
            await self._session.execute(select(func.count()).select_from(Series))
        ).scalar_one()

    async def by_filters_only(
        self, filters: CatalogueFilters, *, k: int
    ) -> list[Source]:
        """Pure filter query — no semantic component. Ranked by popularity,
        which is the sensible default for "list completed romance manhwa"."""
        stmt = (
            select(Series)
            .where(and_(*build_predicates(filters)) if not filters.is_empty() else True)
            .order_by(Series.popularity.desc().nullslast())
            .limit(k)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_source(r, float(r.popularity or 0), "filter") for r in rows]

    async def by_vector(
        self, semantic_query: str, filters: CatalogueFilters, *, k: int
    ) -> list[Source]:
        vector = await self._embedder.embed_query(semantic_query)
        distance = Series.embedding.cosine_distance(vector).label("distance")
        stmt = (
            select(Series, distance)
            .where(and_(*build_predicates(filters)) if not filters.is_empty() else True)
            .order_by(distance)
            .limit(k)
        )
        rows = (await self._session.execute(stmt)).all()
        return [_to_source(r, 1.0 - float(d), "vector") for r, d in rows]

    async def by_title(
        self, query: str, filters: CatalogueFilters, *, k: int
    ) -> list[Source]:
        """Fuzzy alias match.

        `word_similarity(query, titles_blob)` scores the query against the most
        similar *span* inside the blob, rather than against the whole blob.
        Plain `similarity()` would be diluted to near-zero here, because a
        record's blob holds up to nine aliases and the query matches one.
        """
        score = func.word_similarity(query, Series.titles_blob).label("sim")
        predicates = build_predicates(filters)
        stmt = (
            select(Series, score)
            .where(
                and_(
                    cast(score, Float) > TRIGRAM_THRESHOLD,
                    *(predicates if predicates else []),
                )
            )
            .order_by(score.desc())
            .limit(k)
        )
        rows = (await self._session.execute(stmt)).all()
        return [_to_source(r, float(s), "trigram") for r, s in rows]

    async def search(
        self,
        query: str,
        semantic_query: str,
        filters: CatalogueFilters,
        *,
        k: int = 5,
        candidate_k: int = 20,
    ) -> list[Source]:
        """Full catalogue search: filters, then fused ranking within them."""
        title_hits = await self.by_title(query, filters, k=candidate_k)

        # A strong, unambiguous alias match means the user named a specific
        # series. Returning fuzzy "similar" results above the exact title they
        # typed would be actively wrong, so short-circuit.
        if title_hits and title_hits[0].score > 0.85:
            return title_hits[:k]

        if not semantic_query.strip():
            # Pure filter query: no semantic signal to rank on.
            filtered = await self.by_filters_only(filters, k=k)
            return reciprocal_rank_fusion([filtered, title_hits], k=k) if title_hits else filtered

        vector_hits = await self.by_vector(semantic_query, filters, k=candidate_k)
        if not title_hits:
            return vector_hits[:k]
        return reciprocal_rank_fusion([vector_hits, title_hits], k=k)
