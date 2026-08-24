"""The career corpus: what database.json becomes.

Four nesting levels in the file collapse to four tables, plus skills and
embeddings. Ownership sits at the *user*, not the profile: a career happened
once, and profiles are different framings of it.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from .base import metadata, owned_by, pk_column, timestamps

# all-MiniLM-L6-v2 output width. Used by app/models/embeddings.py, which is
# deliberately not imported here — see that module.
EMBEDDING_DIMENSIONS = 384

companies = Table(
    "companies",
    metadata,
    pk_column(),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", Text, nullable=False),
    # Replaces the FAANG_COMPANIES set hardcoded in experience_db.py: which
    # companies may be chosen automatically as the recent role.
    Column("is_faang", Boolean, nullable=False, server_default=text("false")),
    Column("sort_order", Integer, nullable=False, server_default=text("0")),
    *timestamps(),
    UniqueConstraint("user_id", "name", name="uq_companies_user_id_name"),
    # Anchors the composite foreign keys used by everything below.
    UniqueConstraint("id", "user_id", name="uq_companies_id_user_id"),
)

products = Table(
    "products",
    metadata,
    pk_column(),
    Column("company_id", UUID(as_uuid=True), nullable=False),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("name", Text, nullable=False),
    Column("summary", Text, nullable=False, server_default=text("''")),
    # Years, not dates: every timeline in the source file is "YYYY - YYYY", and
    # the resume renders years. A date column would have to invent a month.
    Column("start_year", SmallInteger, nullable=True),
    Column("end_year", SmallInteger, nullable=True),
    Column("is_current", Boolean, nullable=False, server_default=text("false")),
    # Parsing is lossy; keeping the original lets the corpus round-trip to JSON.
    Column("timeline_raw", Text, nullable=False, server_default=text("''")),
    Column("sort_order", Integer, nullable=False, server_default=text("0")),
    *timestamps(),
    owned_by("companies", column="company_id"),
    UniqueConstraint("company_id", "name", name="uq_products_company_id_name"),
    UniqueConstraint("id", "user_id", name="uq_products_id_user_id"),
    CheckConstraint(
        "end_year IS NULL OR start_year IS NULL OR end_year >= start_year",
        name="years_ordered",
    ),
    # A role cannot be ongoing and finished at once. This is the constraint that
    # would have caught a bare "2018" being read as "still employed here".
    CheckConstraint(
        "NOT (is_current AND end_year IS NOT NULL)",
        name="current_has_no_end",
    ),
)

projects = Table(
    "projects",
    metadata,
    pk_column(),
    Column("product_id", UUID(as_uuid=True), nullable=False),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=text("''")),
    Column("sort_order", Integer, nullable=False, server_default=text("0")),
    *timestamps(),
    owned_by("products", column="product_id"),
    UniqueConstraint("product_id", "name", name="uq_projects_product_id_name"),
    UniqueConstraint("id", "user_id", name="uq_projects_id_user_id"),
)

challenges = Table(
    "challenges",
    metadata,
    pk_column(),
    Column("project_id", UUID(as_uuid=True), nullable=False),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    # The readable id from database.json, e.g. amazon_s3_globalmetaindex_challenge1.
    Column("slug", Text, nullable=False),
    # The narrative. Four fields the tailoring prompt sends verbatim...
    Column("situation", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("achievement", Text, nullable=False),
    Column("business_impact", Text, nullable=False),
    # ...and the one the file misnames "seniority_indicator". All 32 values are
    # unique prose describing scope, not a category, so it is modelled as text.
    Column("leadership_note", Text, nullable=False, server_default=text("''")),
    # Retire a challenge without deleting it, so bullets that cited it keep
    # their provenance.
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("sort_order", Integer, nullable=False, server_default=text("0")),
    # What ranking reads. Generated rather than computed in Python, so it can
    # never drift from the fields it summarises.
    Column(
        "search_text",
        Text,
        Computed(
            "situation || ' ' || action || ' ' || achievement || ' ' || business_impact",
            persisted=True,
        ),
    ),
    *timestamps(),
    owned_by("projects", column="project_id"),
    UniqueConstraint("user_id", "slug", name="uq_challenges_user_id_slug"),
    UniqueConstraint("id", "user_id", name="uq_challenges_id_user_id"),
    # Lets ts_rank replace the hand-rolled TF-IDF fallback in vector_search.py.
    #
    # Declared inline rather than after the Table: SQLAlchemy binds an index to
    # its table by inspecting the expression's columns, and that inference does
    # not work over a Computed column — the index would be built and silently
    # never created. Passing it to Table() attaches it explicitly.
    Index(
        "ix_challenges_search_fts",
        text("to_tsvector('english', search_text)"),
        postgresql_using="gin",
    ),
)

skills = Table(
    "skills",
    metadata,
    pk_column(),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", Text, nullable=False),
    # "Python" and "python " cannot both exist for one user.
    Column("normalized", Text, Computed("lower(btrim(name))", persisted=True)),
    *timestamps(),
    UniqueConstraint("user_id", "normalized", name="uq_skills_user_id_normalized"),
)

challenge_skills = Table(
    "challenge_skills",
    metadata,
    Column(
        "challenge_id",
        UUID(as_uuid=True),
        ForeignKey("challenges.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "skill_id",
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "challenge_skills",
    "challenges",
    "companies",
    "products",
    "projects",
    "skills",
]
