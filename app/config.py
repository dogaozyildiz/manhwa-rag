from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, from the environment or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://manhwa:manhwa@localhost:5434/manhwa"

    # Embeddings run locally — no key, no cost, no network at query time.
    # multilingual-e5-small handles Korean/Japanese/Chinese titles alongside
    # English, which matters because a single series carries aliases in all of
    # them. 384 dimensions.
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_dim: int = 384

    # Generation. The only piece needing an account (aistudio.google.com,
    # free tier, no card). Swappable via app/answer/provider.py.
    google_api_key: str = ""
    answer_model: str = "gemini-2.0-flash"

    # Corpus size
    n_manhwa: int = 350
    n_manga: int = 150

    # Chunking (industry prose only; catalogue records are not chunked)
    chunk_tokens: int = 500
    chunk_overlap_tokens: int = 80

    # Retrieval
    top_k: int = 5
    candidate_k: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
