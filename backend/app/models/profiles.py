"""Resume profiles: a user's several identities.

Each profile is a framing of the same career, and owns its own job pipeline.
The repeating sections that lived inside ``data_json`` become real rows.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from .base import metadata, owned_by, pk_column, timestamps

profiles = Table(
    "profiles",
    metadata,
    pk_column(),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", Text, nullable=False),
    # Personal details, promoted out of data_json.
    Column("full_name", Text, nullable=False, server_default=text("''")),
    Column("professional_title", Text, nullable=False, server_default=text("''")),
    Column("email", Text, nullable=False, server_default=text("''")),
    Column("phone", Text, nullable=False, server_default=text("''")),
    # The full address. street and postal exist because the current profile
    # form collects them and real profiles have them filled in — dropping them
    # would lose data on migration, which a schema change should never do.
    Column("street", Text, nullable=False, server_default=text("''")),
    Column("city", Text, nullable=False, server_default=text("''")),
    Column("state", Text, nullable=False, server_default=text("''")),
    Column("postal", Text, nullable=False, server_default=text("''")),
    Column("country", Text, nullable=False, server_default=text("''")),
    # Carried across for the same reason. Unset on every profile today, and a
    # birthdate is rarely wanted on a resume — a candidate for removing from
    # the profile form, but not for silently discarding here.
    Column("birthday", Text, nullable=False, server_default=text("''")),
    Column("linkedin", Text, nullable=False, server_default=text("''")),
    Column("website", Text, nullable=False, server_default=text("''")),
    Column("summary", Text, nullable=False, server_default=text("''")),
    Column("is_default", Boolean, nullable=False, server_default=text("false")),
    Column("archived_at", DateTime(timezone=True), nullable=True),
    *timestamps(),
    UniqueConstraint("user_id", "name", name="uq_profiles_user_id_name"),
    # Anchors every composite key that pins a job or document to its owner.
    UniqueConstraint("id", "user_id", name="uq_profiles_id_user_id"),
)

# Exactly one default per user, enforced rather than assumed.
Index(
    "ix_profiles_one_default",
    profiles.c.user_id,
    unique=True,
    postgresql_where=text("is_default"),
)

profile_experiences = Table(
    "profile_experiences",
    metadata,
    pk_column(),
    Column("profile_id", UUID(as_uuid=True), nullable=False),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("company", Text, nullable=False),
    Column("title", Text, nullable=False, server_default=text("''")),
    Column("location", Text, nullable=False, server_default=text("''")),
    Column("start_date", Text, nullable=False, server_default=text("''")),
    Column("end_date", Text, nullable=False, server_default=text("''")),
    Column("is_current", Boolean, nullable=False, server_default=text("false")),
    # Newline-separated; each line renders as a bullet.
    Column("description", Text, nullable=False, server_default=text("''")),
    Column("sort_order", Integer, nullable=False, server_default=text("0")),
    *timestamps(),
    owned_by("profiles", column="profile_id"),
    CheckConstraint(
        "NOT (is_current AND end_date <> '')",
        name="current_has_no_end",
    ),
)

profile_educations = Table(
    "profile_educations",
    metadata,
    pk_column(),
    Column("profile_id", UUID(as_uuid=True), nullable=False),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("university", Text, nullable=False),
    Column("degree", Text, nullable=False, server_default=text("''")),
    Column("start_year", Text, nullable=False, server_default=text("''")),
    Column("end_year", Text, nullable=False, server_default=text("''")),
    Column("location", Text, nullable=False, server_default=text("''")),
    Column("sort_order", Integer, nullable=False, server_default=text("0")),
    *timestamps(),
    owned_by("profiles", column="profile_id"),
)

profile_skills = Table(
    "profile_skills",
    metadata,
    pk_column(),
    Column("profile_id", UUID(as_uuid=True), nullable=False),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    # Free text rather than a skills reference: what a resume lists and what a
    # challenge proves are different vocabularies, and forcing them to agree
    # would stop someone writing "Python (expert)" on a resume.
    Column("name", Text, nullable=False),
    Column("category", Text, nullable=False, server_default=text("'Other'")),
    Column("sort_order", Integer, nullable=False, server_default=text("0")),
    *timestamps(),
    owned_by("profiles", column="profile_id"),
    UniqueConstraint("profile_id", "name", name="uq_profile_skills_profile_id_name"),
)

__all__ = [
    "profile_educations",
    "profile_experiences",
    "profile_skills",
    "profiles",
]
