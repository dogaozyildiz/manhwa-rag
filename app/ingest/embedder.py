"""Embeddings, computed locally.

No API key, no cost, no network at query time. `multilingual-e5-small` is used
because this catalogue is genuinely multilingual: one series carries English,
romaji, Korean and Japanese aliases, and an English-only model embeds
"나 혼자만 레벨업" as noise.

**The asymmetric-prefix gotcha.** E5 models are trained with `query: ` and
`passage: ` prefixes, and using the wrong one — or none — measurably degrades
retrieval. This is easy to miss because it fails silently: results still come
back, just worse. Hence two distinct methods rather than one `embed()`, so a
caller cannot accidentally embed a query as a passage.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from app.config import get_settings

BATCH_SIZE = 64


class Embedder(Protocol):
    dim: int

    async def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class LocalEmbedder:
    """sentence-transformers, run on CPU in a worker thread."""

    def __init__(self, model_name: str | None = None, dim: int | None = None) -> None:
        settings = get_settings()
        self.model_name = model_name or settings.embedding_model
        self.dim = dim or settings.embedding_dim
        self._model = None

    def _load(self):
        """Loaded lazily: importing torch is slow, and callers that only need
        the protocol (tests, /health) should not pay for it."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            print(f"loading embedding model {self.model_name} ...")
            self._model = SentenceTransformer(self.model_name)
            # Renamed in sentence-transformers 5.x; fall back for older versions.
            get_dim = getattr(
                self._model,
                "get_embedding_dimension",
                self._model.get_sentence_embedding_dimension,
            )
            actual = get_dim()
            if actual != self.dim:
                raise RuntimeError(
                    f"{self.model_name} produces {actual}-dim vectors but the "
                    f"schema expects {self.dim}. Update EMBEDDING_DIM and the "
                    f"migration together — they must not drift."
                )
        return self._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(
            texts,
            batch_size=BATCH_SIZE,
            normalize_embeddings=True,  # cosine distance assumes unit vectors
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [v.tolist() for v in vectors]

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        prefixed = [f"passage: {t}" for t in texts]
        return await asyncio.to_thread(self._encode, prefixed)

    async def embed_query(self, text: str) -> list[float]:
        result = await asyncio.to_thread(self._encode, [f"query: {text}"])
        return result[0]


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    """Process-wide singleton — the model is ~470MB and must load only once."""
    global _embedder
    if _embedder is None:
        _embedder = LocalEmbedder()
    return _embedder
