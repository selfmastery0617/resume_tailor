"""The sample resume shown on Templates/Builder pages' preview.

Templates and Builder pages always preview with sample data now, never a
real profile's (see the reasoning in frontend/src/pages/TemplatesPage.tsx --
a real profile is often too sparse to judge a layout against). That makes
the sample resume itself worth editing, so every section a template can
have gets a realistic demonstration.

Stored as one JSONB row in the settings table (scope='user', key
'sampleResume') -- reusing that table rather than adding a new one, but read
and written directly here rather than through
settings_service.get_settings()/update_settings(): those assume every
setting is a plain string for a homogeneous DEFAULTS-merge, and this one is
a full ResumeData object.
"""

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import get_db
from app.models import settings
from app.schemas.resume import Education, Experience, ProfileInfo, ResumeData, Skill

SAMPLE_RESUME_KEY = "sampleResume"

# The built-in default, used until someone customizes it. Kept comprehensive
# on purpose -- this exists to exercise every section a template can have,
# so every field here should stay populated rather than realistic-empty.
DEFAULT_SAMPLE_RESUME = ResumeData(
    profile=ProfileInfo(
        fullName="Alex Chen",
        professionalTitle="Senior Backend Engineer",
        email="alex.chen@example.com",
        phone="(555) 010-4477",
        street="128 Harbor Street",
        city="Austin",
        state="TX",
        postal="78701",
        birthday="1990-05-14",
        linkedin="linkedin.com/in/alexchen",
        website="alexchen.dev",
        summary=(
            "Backend engineer with 8 years building **distributed services** at scale. "
            "Focused on reliability, developer experience, and pragmatic API design."
        ),
    ),
    experience=[
        Experience(
            id="exp-1",
            company="Northwind Systems",
            title="Senior Backend Engineer",
            location="Remote",
            startDate="Mar 2021",
            endDate="",
            current=True,
            companySummary="Platform engineering for a high-volume logistics network.",
            description=(
                "Led migration of a monolith to **event-driven services**, cutting p99 latency by 42%.\n"
                "Designed the public REST API now serving 30M requests per day.\n"
                "Mentored five engineers and introduced a lightweight RFC process."
            ),
        ),
        Experience(
            id="exp-2",
            company="Bright Harbor Analytics",
            title="Backend Engineer",
            location="Austin, TX",
            startDate="Jun 2018",
            endDate="Feb 2021",
            current=False,
            companySummary="Analytics products for operational and product teams.",
            description=(
                "Built the ingestion pipeline processing 4TB of daily telemetry.\n"
                "Reduced infrastructure spend 28% by right-sizing the warehouse workload."
            ),
        ),
    ],
    education=[
        Education(
            id="edu-1",
            university="University of Texas at Austin",
            degree="B.S. Computer Science",
            startYear="2013",
            endYear="2017",
            location="Austin, TX",
        ),
    ],
    skills=[
        Skill(id="sk-1", name="Python", category="Languages"),
        Skill(id="sk-2", name="TypeScript", category="Languages"),
        Skill(id="sk-3", name="Go", category="Languages"),
        Skill(id="sk-4", name="PostgreSQL", category="Data"),
        Skill(id="sk-5", name="Kafka", category="Data"),
        Skill(id="sk-6", name="AWS", category="Infrastructure"),
        Skill(id="sk-7", name="Kubernetes", category="Infrastructure"),
        Skill(id="sk-8", name="Mentoring", category="Other"),
    ],
)


def get_sample_resume() -> ResumeData:
    from app.bootstrap import current_user_id

    user_id = current_user_id()
    with get_db() as conn:
        row = conn.execute(
            select(settings.c.value).where(
                settings.c.scope == "user",
                settings.c.user_id == user_id,
                settings.c.key == SAMPLE_RESUME_KEY,
            )
        ).first()
    if row is None:
        return DEFAULT_SAMPLE_RESUME
    return ResumeData.model_validate(row.value)


def save_sample_resume(data: ResumeData) -> ResumeData:
    from app.bootstrap import current_user_id
    from app.ids import uuid7

    user_id = current_user_id()
    with get_db() as conn:
        statement = pg_insert(settings).values(
            id=uuid7(),
            scope="user",
            user_id=user_id,
            key=SAMPLE_RESUME_KEY,
            value=data.model_dump(),
        )
        conn.execute(
            statement.on_conflict_do_update(
                index_elements=[settings.c.user_id, settings.c.key],
                index_where=text("scope = 'user'"),
                set_={"value": statement.excluded.value, "updated_at": func.now()},
            )
        )
    return data


def reset_sample_resume() -> ResumeData:
    """Drop the customization, so get_sample_resume() falls back to
    DEFAULT_SAMPLE_RESUME again."""
    from app.bootstrap import current_user_id

    user_id = current_user_id()
    with get_db() as conn:
        conn.execute(
            delete(settings).where(
                settings.c.scope == "user",
                settings.c.user_id == user_id,
                settings.c.key == SAMPLE_RESUME_KEY,
            )
        )
    return DEFAULT_SAMPLE_RESUME
