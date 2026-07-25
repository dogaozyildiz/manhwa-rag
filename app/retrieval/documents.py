"""Industry-prose retrieval: dense + lexical, fused.

This is the conventional half of the system — ordinary document RAG over
Wikipedia articles about publishers, platforms and business models. It exists
alongside the catalogue because the two answer different questions: "how does
Naver Webtoon monetise?" is not a catalogue lookup, and "completed romance
manhwa under 100 chapters" is not in any article.

Lexical search earns its place here for the same reason it does in the
catalogue: exact tokens. Publisher names, imprint names and platform names
("Shōnen Jump+", "Lezhin") are precisely the strings dense embeddings blur
together, and precisely what industry questions are about.
"""

from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.embedder import Embedder, get_embedder
from app.models import Chunk, Document
from app.retrieval.store import Source, reciprocal_rank_fusion


def _to_source(chunk: Chunk, doc: Document, score: float, origin: str) -> Source:
    return Source(
        ref=f"article:{doc.source_id}#{chunk.chunk_index}",
        kind="article",
        title=doc.title,
        text=chunk.text,
        score=score,
        url=doc.url,
        origin=origin,
        meta={"section": chunk.section, "source_id": doc.source_id},
    )


class DocumentRetriever:
    def __init__(self, session: AsyncSession, embedder: Embedder | None = None) -> None:
        self._session = session
        self._explicit_embedder = embedder

    @property
    def _embedder(self) -> Embedder:
        if self._explicit_embedder is None:
            self._explicit_embedder = get_embedder()
        return self._explicit_embedder

    async def count(self) -> int:
        return (
            await self._session.execute(select(func.count()).select_from(Chunk))
        ).scalar_one()

    async def by_vector(self, query: str, *, k: int = 5) -> list[Source]:
        vector = await self._embedder.embed_query(query)
        distance = Chunk.embedding.cosine_distance(vector).label("distance")
        stmt = (
            select(Chunk, Document, distance)
            .join(Document, Chunk.document_id == Document.id)
            .order_by(distance)
            .limit(k)
        )
        rows = (await self._session.execute(stmt)).all()
        return [_to_source(c, d, 1.0 - float(dist), "vector") for c, d, dist in rows]

    async def by_lexical(self, query: str, *, k: int = 5) -> list[Source]:
        # websearch_to_tsquery tolerates raw user phrasing — apostrophes,
        # question marks, quoted phrases — where to_tsquery raises on them.
        tsv = func.to_tsvector(text("'english'"), Chunk.text)
        tsq = func.websearch_to_tsquery(text("'english'"), query)
        rank = func.ts_rank(tsv, tsq).label("rank")
        stmt = (
            select(Chunk, Document, rank)
            .join(Document, Chunk.document_id == Document.id)
            .where(tsv.op("@@")(tsq))
            .order_by(rank.desc())
            .limit(k)
        )
        rows = (await self._session.execute(stmt)).all()
        return [_to_source(c, d, float(r), "lexical") for c, d, r in rows]

    async def search(
        self, query: str, *, k: int = 5, candidate_k: int = 20
    ) -> list[Source]:
        dense = await self.by_vector(query, k=candidate_k)
        lexical = await self.by_lexical(query, k=candidate_k)
        if not lexical:
            return dense[:k]
        return reciprocal_rank_fusion([dense, lexical], k=k)
