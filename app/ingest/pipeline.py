"""Ingest both corpora: catalogue records and industry prose.

Idempotent by content hash at the record level (series) and the chunk level
(articles), so re-running after a corpus refresh only embeds what actually
changed. Embedding here is free and local, but idempotency still matters: it
keeps re-ingest fast, and it is the same discipline a paid embedding provider
would demand.

    python -m app.ingest.pipeline            # fetch (or use cache) and ingest
    python -m app.ingest.pipeline --force    # re-embed everything
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import session_scope
from app.ingest.anilist import FetchPlan, fetch_catalogue
from app.ingest.chunker import chunk_document
from app.ingest.clean import clean_wikipedia, drop_boilerplate_sections
from app.ingest.embedder import Embedder, get_embedder
from app.ingest.enrich import to_record
from app.ingest.wikipedia import fetch_articles
from app.models import Chunk, Document, Series

DATA_DIR = Path("data/raw")


async def ingest_series(
    session: AsyncSession, media: list[dict], embedder: Embedder, *, force: bool
) -> dict:
    stats = {"created": 0, "updated": 0, "skipped": 0, "embedded": 0}

    existing = {
        row.anilist_id: row
        for row in (await session.execute(select(Series))).scalars().all()
    }

    pending: list[tuple] = []  # (record, existing_row_or_None)
    for item in media:
        record = to_record(item)
        if record is None:
            continue
        current = existing.get(record.anilist_id)
        if current is not None and current.content_hash == record.content_hash and not force:
            stats["skipped"] += 1
            continue
        pending.append((record, current))

    if not pending:
        return stats

    # One batched encode for everything that changed — far faster than
    # per-record calls, which matters at 500 records on CPU.
    vectors = await embedder.embed_passages([r.card for r, _ in pending])
    stats["embedded"] = len(vectors)

    for (record, current), vector in zip(pending, vectors, strict=True):
        target = current or Series(anilist_id=record.anilist_id)
        target.title_romaji = record.title_romaji
        target.title_english = record.title_english
        target.title_native = record.title_native
        target.titles = record.titles
        target.titles_blob = record.titles_blob
        target.description = record.description
        target.card = record.card
        target.country = record.country
        target.format = record.format
        target.status = record.status
        target.chapters = record.chapters
        target.volumes = record.volumes
        target.start_year = record.start_year
        target.end_year = record.end_year
        target.genres = record.genres
        target.tags = record.tags
        target.average_score = record.average_score
        target.popularity = record.popularity
        target.site_url = record.site_url
        target.content_hash = record.content_hash
        target.embedding = vector
        if current is None:
            session.add(target)
            stats["created"] += 1
        else:
            stats["updated"] += 1

    return stats


async def ingest_articles(
    session: AsyncSession, articles: list[dict], embedder: Embedder, *, force: bool
) -> dict:
    settings = get_settings()
    stats = {"created": 0, "updated": 0, "skipped": 0, "embedded": 0}

    for article in articles:
        source_id = article["title"].replace(" ", "_")
        text = drop_boilerplate_sections(clean_wikipedia(article["extract"]))
        body = f"# {article['title']}\n\n{text}"
        doc_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

        current = (
            await session.execute(
                select(Document).where(Document.source_id == source_id)
            )
        ).scalar_one_or_none()

        if current is not None and current.content_hash == doc_hash and not force:
            stats["skipped"] += 1
            continue

        drafts = chunk_document(
            body,
            doc_title=article["title"],
            max_tokens=settings.chunk_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
        )
        if not drafts:
            continue

        if current is None:
            current = Document(
                source_id=source_id,
                title=article["title"],
                url=article.get("url"),
                content_hash=doc_hash,
            )
            session.add(current)
            await session.flush()
            reusable: dict[str, list[float]] = {}
            stats["created"] += 1
        else:
            current.title = article["title"]
            current.url = article.get("url")
            current.content_hash = doc_hash
            prior = (
                await session.execute(
                    select(Chunk.content_hash, Chunk.embedding).where(
                        Chunk.document_id == current.id
                    )
                )
            ).all()
            reusable = {h: e for h, e in prior}
            await session.execute(delete(Chunk).where(Chunk.document_id == current.id))
            stats["updated"] += 1

        needed = [d for d in drafts if d.content_hash not in reusable]
        if needed:
            vectors = await embedder.embed_passages(
                [d.embed_text(article["title"]) for d in needed]
            )
            stats["embedded"] += len(vectors)
            for draft, vector in zip(needed, vectors, strict=True):
                reusable[draft.content_hash] = vector

        session.add_all(
            [
                Chunk(
                    document_id=current.id,
                    chunk_index=d.chunk_index,
                    text=d.text,
                    section=d.section or None,
                    token_count=d.token_count,
                    content_hash=d.content_hash,
                    embedding=reusable[d.content_hash],
                )
                for d in drafts
            ]
        )

    return stats


async def run(*, force: bool = False) -> None:
    settings = get_settings()
    embedder = get_embedder()

    print("Fetching catalogue ...")
    media = await fetch_catalogue(
        [
            FetchPlan("KR", settings.n_manhwa),
            FetchPlan("JP", settings.n_manga),
        ],
        DATA_DIR,
    )
    print(f"  {len(media)} series")

    print("Fetching industry articles ...")
    articles = await fetch_articles(DATA_DIR)
    print(f"  {len(articles)} articles")

    print("Ingesting catalogue ...")
    async with session_scope() as session:
        series_stats = await ingest_series(session, media, embedder, force=force)
    print(f"  {series_stats}")

    print("Ingesting articles ...")
    async with session_scope() as session:
        article_stats = await ingest_articles(session, articles, embedder, force=force)
    print(f"  {article_stats}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest catalogue and industry corpora.")
    parser.add_argument("--force", action="store_true", help="re-embed everything")
    args = parser.parse_args()
    asyncio.run(run(force=args.force))


if __name__ == "__main__":
    main()
