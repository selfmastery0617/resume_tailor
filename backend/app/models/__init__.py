"""The Postgres schema, as SQLAlchemy Core tables.

Importing this module registers every table on :data:`metadata`, which is what
Alembic autogenerates against. Import order matters only in that foreign keys
are resolved by name at create time, so the modules can be listed in any order.
"""

from __future__ import annotations

from .base import metadata
from .config import prompts, provider_accounts, settings, work_queue
from .corpus import (
    EMBEDDING_DIMENSIONS,
    challenge_embeddings,
    challenge_skills,
    challenges,
    companies,
    products,
    projects,
    skills,
)
from .documents import (
    generated_documents,
    profile_template_settings,
    templates,
    templates_versions,
)
from .extraction import (
    extraction_bullets,
    extraction_events,
    extraction_role_projects,
    extraction_roles,
    extraction_runs,
    extraction_skills,
)
from .identity import (
    audit_log,
    invitations,
    memberships,
    organizations,
    sessions,
    users,
)
from .jobs import application_events, import_batches, jobs
from .profiles import (
    profile_educations,
    profile_experiences,
    profile_skills,
    profiles,
)

# Extensions the schema depends on. Created by the first migration.
REQUIRED_EXTENSIONS = ("pgcrypto", "vector")

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "REQUIRED_EXTENSIONS",
    "application_events",
    "audit_log",
    "challenge_embeddings",
    "challenge_skills",
    "challenges",
    "companies",
    "extraction_bullets",
    "extraction_events",
    "extraction_role_projects",
    "extraction_roles",
    "extraction_runs",
    "extraction_skills",
    "generated_documents",
    "import_batches",
    "invitations",
    "jobs",
    "memberships",
    "metadata",
    "organizations",
    "products",
    "profile_educations",
    "profile_experiences",
    "profile_skills",
    "profile_template_settings",
    "profiles",
    "projects",
    "prompts",
    "provider_accounts",
    "sessions",
    "settings",
    "skills",
    "templates",
    "templates_versions",
    "users",
    "work_queue",
]
