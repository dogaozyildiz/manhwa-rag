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
