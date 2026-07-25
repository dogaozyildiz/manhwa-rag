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

    # Generation. The only piece needing an account. Swappable via
    # app/answer/provider.py — "groq", "gemini" or "ollama".
    #
    # Groq is the default because Google's Gemini free tier allocates zero
    # generation quota in the EEA: the key authenticates and lists models, but
    # every call returns `limit: 0` on the free-tier quota metric.
    llm_provider: str = "groq"

    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    google_api_key: str = ""
    answer_model: str = "gemini-2.0-flash"

    # Local generation via Ollama — no account, no network, no region limits.
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    # Corpus size
    n_manhwa: int = 350
    n_manga: int = 150

    # Chunking (industry prose only; catalogue records are not chunked)
    chunk_tokens: int = 500
    chunk_overlap_tokens: int = 80

    # Retrieval
    top_k: int = 5
    candidate_k: int = 20

    # Per-source character cap applied before generation. Free-tier providers
    # enforce hard per-request token ceilings (Groq's 8B model: 6000 TPM), and a
    # `both` route returns 2*k sources, so untruncated chunks overflow it with a
    # 413 that retrying cannot fix.
    max_source_chars: int = 1200

    # Completion tokens requested. Providers reserve this against per-minute
    # quotas up front, so it is a rate-limit parameter as much as a length one.
    max_output_tokens: int = 1200

    # Load the embedding model when the server boots rather than on the first
    # question. Importing torch and loading the model costs ~80s on a cold
    # process; paid lazily, that lands on whoever asks first, and an 80-second
    # question looks like a hung app rather than a warming one. Off for tests,
    # which stub the embedder and must not pay for torch.
    warm_embedder: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
