"""Embedding storage. Deliberately NOT part of the default metadata.

This table needs the pgvector extension, which is a separate download and, on
Windows, a compile step. Nothing reads it yet: ranking encodes with
sentence-transformers in Python and computes similarity there.

Importing it into `app.models` would put it in the metadata Alembic compares
against, so every autogenerate would try to create it and every migration would
depend on an extension the server may not have.

When similarity search moves into the database, import this module from
`app/models/__init__.py` and autogenerate the migration — it will be the newest
revision at that point, which is exactly where a new dependency belongs.
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, Index, Table, Text, text
from sqlalchemy.dialects.postgresql import UUID

from .base import metadata
from .corpus import EMBEDDING_DIMENSIONS

challenge_embeddings = Table(
    "challenge_embeddings",
    metadata,
    Column(
        "challenge_id",
        UUID(as_uuid=True),
        ForeignKey("challenges.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("model", Text, primary_key=True),
    # sha256 of search_text at the time of encoding. Matching means the stored
    # vector is still valid, so an unchanged challenge is never re-embedded.
    Column("content_hash", Text, nullable=False),
    Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
    Column(
        "computed_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
)

# Pointless at 32 rows — Postgres will sequential-scan and be right to. Correct
# and free once the corpus is thousands of rows.
Index(
    "ix_challenge_embeddings_vector",
    challenge_embeddings.c.embedding,
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "vector_cosine_ops"},
)
