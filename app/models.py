"""Schema for the two corpora.

`Series` is the catalogue: deliberately *typed* columns rather than a blob of
JSON, because those columns are what structured filters query. "Completed
manhwa under 100 chapters" has to become `status = 'FINISHED' AND chapters <
100 AND country = 'KR'` in SQL — you cannot get that from a vector search, and
storing them untyped would force casting on every query.

`Document`/`Chunk` is the industry prose half, and is an ordinary RAG document
store.
"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

# The PostgreSQL-dialect ARRAY, not sqlalchemy.ARRAY. Only the dialect version
# implements the containment operators (`@>` via .contains(), `&&` via
# .overlap()) that genre filtering depends on; the base type raises
# NotImplementedError at query-build time.
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import get_settings

EMBEDDING_DIM = get_settings().embedding_dim


class Base(DeclarativeBase):
    pass


class Series(Base):
    """One catalogue entry (a manhwa or manga)."""

    __tablename__ = "series"
    __table_args__ = (
        Index(
            "ix_series_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # Array containment for genre/tag filters: genres @> ARRAY['Romance']
        Index("ix_series_genres", "genres", postgresql_using="gin"),
        Index("ix_series_tags", "tags", postgresql_using="gin"),
        # Filter columns. Cheap, and they turn "under 100 chapters" into an
        # index scan instead of a sequential one.
        Index("ix_series_filters", "country", "status", "chapters", "start_year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    anilist_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)

    title_romaji: Mapped[str | None] = mapped_column(String(512), nullable=True)
    title_english: Mapped[str | None] = mapped_column(String(512), nullable=True)
    title_native: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Every alias, for exact array matching.
    titles: Mapped[list[str]] = mapped_column(ARRAY(Text))
    # The same aliases flattened into one string. pg_trgm indexes text, not
    # text[], and fuzzy alias matching ("Kimetsu no Yaiba" -> Demon Slayer) is
    # the single most important lookup in this catalogue.
    titles_blob: Mapped[str] = mapped_column(Text)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Enriched text actually embedded — title aliases + facts + synopsis. A bare
    # 300-character synopsis is too thin to retrieve reliably on its own.
    card: Mapped[str] = mapped_column(Text)

    country: Mapped[str | None] = mapped_column(String(8), nullable=True)  # KR / JP
    format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    chapters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    volumes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    genres: Mapped[list[str]] = mapped_column(ARRAY(Text))
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text))
    average_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    popularity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    site_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def display_title(self) -> str:
        return self.title_english or self.title_romaji or self.title_native or "Untitled"


class Document(Base):
    """One industry article (Wikipedia)."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(1024))
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_doc_index"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    section: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    token_count: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))

    document: Mapped[Document] = relationship(back_populates="chunks")
