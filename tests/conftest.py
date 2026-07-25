import asyncio

import pytest
from sqlalchemy import text

from app.db import get_engine


def _db_reachable() -> bool:
    async def check() -> bool:
        try:
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    try:
        return asyncio.run(check())
    except Exception:
        return False


DB_AVAILABLE = _db_reachable()

requires_db = pytest.mark.skipif(
    not DB_AVAILABLE,
    reason="Postgres not reachable — run `docker compose up -d` first",
)


class StubEmbedder:
    """Deterministic embeddings so retrieval tests need no model load.

    Vectors come from token hashes: enough for a round-trip and an ordering
    assertion, without pretending to model meaning.
    """

    dim = 384

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in text.lower().split():
            vec[hash(token) % self.dim] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]


@pytest.fixture
def stub_embedder() -> StubEmbedder:
    return StubEmbedder()


# Series chosen so that exactly two satisfy
# country=KR AND status=FINISHED AND chapters<100 AND genres ⊇ {Romance}.
# The other three each violate exactly one predicate, so a filter that silently
# fails to bind shows up as an extra row rather than as a pass.
_FIXTURE_SERIES = [
    # (anilist_id, title, country, status, chapters, year, genres)
    (900001, "Test Romance Short", "KR", "FINISHED", 60, 2020, ["Drama", "Romance"]),
    (900002, "Test Romance Short Two", "KR", "FINISHED", 95, 2019, ["Romance"]),
    (900003, "Test Romance Long", "KR", "FINISHED", 300, 2018, ["Romance"]),  # too long
    (900004, "Test Romance Ongoing", "KR", "RELEASING", 40, 2021, ["Romance"]),  # not finished
    (900005, "Test Action Short", "KR", "FINISHED", 50, 2020, ["Action"]),  # wrong genre
    (900006, "Test Japanese Romance", "JP", "FINISHED", 70, 2017, ["Romance"]),  # wrong country
]

SEEDED_MATCHING_IDS = {900001, 900002}


@pytest.fixture
async def seeded_catalogue(stub_embedder):
    """Insert a small known catalogue, then remove it.

    Exists so the filter-binding guarantee is exercised in CI, where the real
    corpus has never been ingested. Without this, `requires_db` passes on a
    reachable-but-empty database and the assertion silently tests nothing.
    """
    from sqlalchemy import delete

    from app.db import session_scope
    from app.models import Series

    ids = [row[0] for row in _FIXTURE_SERIES]
    vectors = await stub_embedder.embed_passages([row[1] for row in _FIXTURE_SERIES])

    async with session_scope() as session:
        await session.execute(delete(Series).where(Series.anilist_id.in_(ids)))
        for (aid, title, country, status, chapters, year, genres), vec in zip(
            _FIXTURE_SERIES, vectors, strict=True
        ):
            session.add(
                Series(
                    anilist_id=aid,
                    title_english=title,
                    title_romaji=title,
                    title_native=None,
                    titles=[title],
                    titles_blob=title,
                    description="fixture",
                    card=f"{title}. {country} {status} {chapters} chapters.",
                    country=country,
                    format="MANGA",
                    status=status,
                    chapters=chapters,
                    volumes=None,
                    start_year=year,
                    end_year=None,
                    genres=genres,
                    tags=[],
                    average_score=70,
                    # Far above any real row (real popularity tops out in the
                    # hundreds of thousands). Pure-filter queries rank by
                    # popularity, so without this the fixtures sort below the
                    # ~19 genuine matches and fall outside k — making the test
                    # pass or fail depending on whether the corpus is ingested.
                    popularity=10_000_000 + aid,
                    site_url=f"https://example.test/{aid}",
                    content_hash=f"hash{aid}",
                    embedding=vec,
                )
            )

    yield ids

    async with session_scope() as session:
        await session.execute(delete(Series).where(Series.anilist_id.in_(ids)))
