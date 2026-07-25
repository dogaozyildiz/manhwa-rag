"""init: series catalogue + industry documents, with vector/trigram/FTS indexes

Revision ID: 0001
Revises:
Create Date: 2026-07-25

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 384


def upgrade() -> None:
    # vector: similarity. pg_trgm: fuzzy alias matching on titles.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "series",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("anilist_id", sa.Integer(), nullable=False),
        sa.Column("title_romaji", sa.String(length=512), nullable=True),
        sa.Column("title_english", sa.String(length=512), nullable=True),
        sa.Column("title_native", sa.String(length=512), nullable=True),
        sa.Column("titles", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("titles_blob", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("card", sa.Text(), nullable=False),
        sa.Column("country", sa.String(length=8), nullable=True),
        sa.Column("format", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("chapters", sa.Integer(), nullable=True),
        sa.Column("volumes", sa.Integer(), nullable=True),
        sa.Column("start_year", sa.Integer(), nullable=True),
        sa.Column("end_year", sa.Integer(), nullable=True),
        sa.Column("genres", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("average_score", sa.Integer(), nullable=True),
        sa.Column("popularity", sa.Integer(), nullable=True),
        sa.Column("site_url", sa.String(length=512), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBEDDING_DIM), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("anilist_id"),
    )
    op.create_index("ix_series_anilist_id", "series", ["anilist_id"])
    op.create_index("ix_series_content_hash", "series", ["content_hash"])
    op.create_index(
        "ix_series_filters", "series", ["country", "status", "chapters", "start_year"]
    )
    op.create_index("ix_series_genres", "series", ["genres"], postgresql_using="gin")
    op.create_index("ix_series_tags", "series", ["tags"], postgresql_using="gin")
    op.execute(
        "CREATE INDEX ix_series_embedding_hnsw ON series "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    # Fuzzy alias lookup: "Kimetsu no Yaiba" -> Demon Slayer. Trigram similarity
    # tolerates romanisation and spacing differences that neither exact match
    # nor dense embeddings handle reliably.
    op.execute(
        "CREATE INDEX ix_series_titles_trgm ON series "
        "USING gin (titles_blob gin_trgm_ops)"
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(length=512), nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id"),
    )
    op.create_index("ix_documents_source_id", "documents", ["source_id"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("section", sa.String(length=1024), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBEDDING_DIM), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunk_doc_index"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_content_hash", "chunks", ["content_hash"])
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    # Lexical half of hybrid retrieval over prose. The expression must match the
    # query's to_tsvector('english', text) exactly or the index is not used.
    op.execute(
        "CREATE INDEX ix_chunks_text_fts ON chunks "
        "USING gin (to_tsvector('english', text))"
    )


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("series")
