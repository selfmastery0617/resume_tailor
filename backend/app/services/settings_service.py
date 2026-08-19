"""Application settings.

Three scopes exist in the schema; two are used today. Most settings belong to
the account, but anything tied to one resume identity is stored against the
profile — `firstCompany` names a company from that profile's own corpus, so a
single account-wide value would be validated against the wrong history.

Prompts live in their own table keyed by kind. The API still presents them as
ordinary settings keys, so nothing above this module has to care.
"""

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import get_db
from app.models import prompts, settings

DEFAULT_SKILLS_PROMPT = """Extract the following from this job description:
1. Main Skills - the key technical and professional skills required, as a concise comma-separated list.
2. Job Mission - the core purpose of this role, in one sentence.

Respond in exactly this format:
Skills: <comma-separated list>
Mission: <one sentence>"""

# Used to turn selected challenges into resume bullets. Placeholders in braces
# are substituted before the prompt is sent; unknown ones are left untouched.
DEFAULT_TAILORING_PROMPT = """Write exactly {count} resume bullet points for a role at {company} on {product}.

Rules:
- Output exactly {count} lines, one bullet per line, with no numbering or headings.
- Start each bullet with a strong past-tense verb.
- Keep every metric and fact exactly as given. Do not invent numbers, employers,
  dates, or technologies.
- Tailor the emphasis to the target job description below.

Target job description:
{job_description}

Source achievements:
{achievements}"""

# Substituted into the tailoring prompt. Surfaced in the Settings UI so the
# prompt can be edited without guessing what is available.
TAILORING_PLACEHOLDERS: tuple[str, ...] = (
    "count",
    "company",
    "product",
    "job_description",
    "achievements",
)

# Runs last, in the same chat that just wrote the bullets, so the model already
# has them in context; {bullets} is included anyway so the prompt still works if
# the session drops and a fresh chat has to be opened.
DEFAULT_SUMMARY_PROMPT = """Write a {sentences}-sentence professional summary for the top of a resume targeting this role.

Rules:
- Output only the summary itself — no heading, no label, no bullet points, no quotes.
- Write in the implied first person: no "I", "my", or the candidate's name.
- Use only what the experience below supports. Do not invent employers, titles,
  metrics, technologies, or years of experience.
- Lead with the strongest match to the target role.

Target role: {job_title}

Target job description:
{job_description}

Experience just written for this resume ({companies}):
{bullets}"""

# Runs last, after the summary, in the same chat. The headline on a tailored
# resume should match the role being applied for rather than stay generic.
DEFAULT_TITLE_PROMPT = """Write the professional title for the top of a resume targeting this role.

Rules:
- Output only the title itself. No quotes, no explanation, no trailing punctuation.
- Keep it under 60 characters.
- Use a title a recruiter would actually search for, not an invented one.
- Do not claim more seniority than the experience below supports.

Target role: {job_title}
Current title on the profile: {current_title}

Target job description:
{job_description}

Summary just written:
{summary}

Experience just written for this resume:
{bullets}"""

TITLE_PLACEHOLDERS: tuple[str, ...] = (
    "job_title",
    "current_title",
    "job_description",
    "summary",
    "bullets",
)

# The prompt used to produce a profile's database.json. Stored only — the
# application never sends it. It is kept here so the wording that produced a
# corpus is recorded beside the corpus, rather than living in someone's notes
# app, and so the next profile can start from the same instructions.
#
# Written to stand alone, with the schema inline and no placeholders, because
# it is copied into an AI tool by hand. A {token} nothing substitutes would be
# pasted verbatim and confuse the model.
DEFAULT_CORPUS_PROMPT = """Convert my experience into a career database, as JSON.

Rules:
- Output only the JSON array. No markdown fence, no commentary before or after.
- Use only what my experience states. Do not invent employers, products, dates,
  metrics, or technologies. If something is not stated, leave it out.
- Give every challenge a unique id: lowercase, company_product_project_challengeN.
- challenge, action, achievement and business_impact are one sentence each.
- seniority_indicator describes scope: who was led, who it was presented to.
- skills_used lists the technologies and disciplines each challenge names.
  Never leave it empty when any are mentioned.
- Split each role into two projects where my experience describes two distinct
  pieces of work, and give each project two challenges where there is enough
  detail for two. Where there is not, write fewer — one real challenge beats two
  with an invented half.

Schema:
[
  {
    "company": "Acme",
    "product": "Acme Payments",
    "timeline": "2019 - 2022",
    "summary": "One sentence on what the product does and my part in it.",
    "projects": [
      {
        "name": "Settlement pipeline",
        "description": "One sentence on the project.",
        "challenges": [
          {
            "id": "acme_payments_settlement_challenge1",
            "challenge": "The problem, in one sentence.",
            "action": "What I did about it, in one sentence.",
            "achievement": "The measurable result, in one sentence.",
            "business_impact": "Why it mattered to the business.",
            "skills_used": ["Python", "PostgreSQL"],
            "seniority_indicator": "Who I led and who I presented to."
          }
        ]
      }
    ]
  }
]

My experience:
"""

SUMMARY_PLACEHOLDERS: tuple[str, ...] = (
    "sentences",
    "job_title",
    "job_description",
    "companies",
    "bullets",
)

DEFAULTS: dict[str, Any] = {
    "skillsPrompt": DEFAULT_SKILLS_PROMPT,
    "tailoringPrompt": DEFAULT_TAILORING_PROMPT,
    # Step 4: a resume summary written from the bullets the pipeline just made.
    "summaryPrompt": DEFAULT_SUMMARY_PROMPT,
    # Step 5: the headline title, written once the summary exists.
    "titlePrompt": DEFAULT_TITLE_PROMPT,
    # Not part of extraction: builds a profile's database.json on demand.
    "corpusPrompt": DEFAULT_CORPUS_PROMPT,
    "outputFolder": "",
    # Which signed-in provider Phase 5 uses to generate content.
    "generationModel": "deepseek",
    # Company used as Job 1 (the earlier role) in experience extraction.
    # Scoped to a profile, not the user: each profile has its own corpus, so a
    # company valid for one is meaningless for another.
    "firstCompany": "",
    # Profile whose details and template are used for tailored resume PDFs, and
    # whose name becomes "<Profile>_resume.pdf". Empty = use the first profile.
    "resumeProfile": "",
}

ALLOWED_MODELS = ("deepseek", "chatgpt")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# Settings that belong to one resume identity rather than the whole account.
PROFILE_SCOPED: frozenset[str] = frozenset({"firstCompany"})

PROMPT_KEYS: dict[str, str] = {
    "skillsPrompt": "skills",
    "tailoringPrompt": "tailoring",
    "summaryPrompt": "summary",
    "titlePrompt": "title",
    "corpusPrompt": "corpus",
}


def _active_profile():
    """The profile whose settings apply. None before any profile exists."""
    from app.services import job_store

    try:
        return job_store.active_profile_id()
    except Exception:  # noqa: BLE001 - no profile yet is a normal first-run state
        return None


def get_settings() -> dict[str, Any]:
    """Stored settings merged over defaults, so a new key never returns None."""
    from app.bootstrap import current_user_id

    user_id = current_user_id()
    stored: dict[str, Any] = {}

    profile_id = _active_profile()

    with get_db() as conn:
        for row in conn.execute(
            select(settings.c.key, settings.c.value).where(
                settings.c.scope == "user", settings.c.user_id == user_id
            )
        ):
            stored[row.key] = row.value

        # Profile-scoped values win, and are the only source for their keys.
        if profile_id is not None:
            for row in conn.execute(
                select(settings.c.key, settings.c.value).where(
                    settings.c.scope == "profile", settings.c.profile_id == profile_id
                )
            ):
                stored[row.key] = row.value

        by_kind = {v: k for k, v in PROMPT_KEYS.items()}
        for row in conn.execute(
            select(prompts.c.kind, prompts.c.body).where(
                prompts.c.scope == "user", prompts.c.user_id == user_id
            )
        ):
            if row.kind in by_kind:
                stored[by_kind[row.kind]] = row.body

    return {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}


def validate_settings(patch: dict[str, Any]) -> dict[str, Any]:
    """Reject unknown keys and invalid values before anything is written."""
    cleaned: dict[str, Any] = {}
    for key, value in patch.items():
        if key not in DEFAULTS:
            raise ValueError(f"Unknown setting: {key!r}")

        if key == "generationModel":
            if value not in ALLOWED_MODELS:
                raise ValueError(
                    f"generationModel must be one of {', '.join(ALLOWED_MODELS)}"
                )
        elif key == "outputFolder":
            if value:
                path = Path(str(value)).expanduser()
                if not path.is_absolute():
                    raise ValueError("Output folder must be an absolute path.")
                if not path.exists():
                    raise ValueError(f"Folder does not exist: {path}")
                if not path.is_dir():
                    raise ValueError(f"Not a folder: {path}")
                value = str(path)
        elif key == "firstCompany":
            if value:
                # Reject a company that isn't in this profile's corpus now,
                # rather than letting extraction fail later with a confusing
                # error. Validated against the active profile, because that is
                # the corpus the extraction will actually read.
                from app.services import experience_db_store, job_store

                try:
                    db = experience_db_store.load_database(job_store.active_profile_id())
                except Exception:  # noqa: BLE001 - no corpus yet, or a broken one
                    db = None
                if db is not None and db.find_company(str(value)) is None:
                    raise ValueError(
                        f"{value!r} is not a company in this profile's database.json."
                    )
                value = str(value).strip()
        elif key == "resumeProfile":
            if value:
                # A deleted profile would otherwise fail at generation time with
                # a 404 that says nothing about where the stale id came from.
                from app.services import profile_service

                value = str(value).strip()
                if all(p.id != value for p in profile_service.list_profiles()):
                    raise ValueError("That profile no longer exists.")
        elif not isinstance(value, str):
            raise ValueError(f"{key} must be text.")

        cleaned[key] = value
    return cleaned


def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    cleaned = validate_settings(patch)
    from app.bootstrap import current_user_id
    from app.ids import uuid7

    user_id = current_user_id()
    profile_id = _active_profile()

    with get_db() as conn:
        for key, value in cleaned.items():
            if kind := PROMPT_KEYS.get(key):
                # The partial unique index covers (user_id, kind) where the
                # scope is 'user', which is what makes this upsert land on one
                # row instead of accumulating revisions.
                statement = pg_insert(prompts).values(
                    id=uuid7(),
                    scope="user",
                    user_id=user_id,
                    kind=kind,
                    body=str(value),
                )
                conn.execute(
                    statement.on_conflict_do_update(
                        index_elements=[prompts.c.user_id, prompts.c.kind],
                        index_where=prompts.c.scope == "user",
                        set_={"body": statement.excluded.body, "updated_at": func.now()},
                    )
                )
            elif key in PROFILE_SCOPED:
                if profile_id is None:
                    raise ValueError(
                        f"{key} belongs to a profile, and none exists yet."
                    )
                statement = pg_insert(settings).values(
                    id=uuid7(),
                    scope="profile",
                    profile_id=profile_id,
                    key=key,
                    value=value,
                )
                conn.execute(
                    statement.on_conflict_do_update(
                        index_elements=[settings.c.profile_id, settings.c.key],
                        index_where=settings.c.scope == "profile",
                        set_={"value": statement.excluded.value, "updated_at": func.now()},
                    )
                )
            else:
                statement = pg_insert(settings).values(
                    id=uuid7(),
                    scope="user",
                    user_id=user_id,
                    key=key,
                    value=value,
                )
                conn.execute(
                    statement.on_conflict_do_update(
                        index_elements=[settings.c.user_id, settings.c.key],
                        index_where=settings.c.scope == "user",
                        set_={"value": statement.excluded.value, "updated_at": func.now()},
                    )
                )
    return get_settings()


def render_template(text: str, values: dict[str, Any]) -> str:
    """Substitute {placeholders} without str.format's brace fragility.

    A user prompt may legitimately contain braces (JSON examples, code), which
    str.format would treat as fields and raise on. Only the keys actually
    supplied are replaced; anything else is left exactly as written.
    """
    rendered = text or ""
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def check_folder(path_text: str) -> dict[str, Any]:
    """Report whether a folder is usable for saving generated documents."""
    raw = (path_text or "").strip()
    if not raw:
        return {"valid": False, "detail": "Enter a folder path."}
    path = Path(raw).expanduser()
    if not path.is_absolute():
        return {"valid": False, "detail": "Please use an absolute path."}
    if not path.exists():
        return {"valid": False, "detail": "That folder does not exist."}
    if not path.is_dir():
        return {"valid": False, "detail": "That path is a file, not a folder."}

    # Writability is what actually matters, and it can't be inferred reliably
    # from permissions on Windows — so test it directly.
    try:
        # A unique temporary file avoids colliding with or deleting a file the
        # user may already have created with a fixed probe name.
        with tempfile.NamedTemporaryFile(prefix=".jobtailor-write-test-", dir=path):
            pass
    except OSError as exc:
        return {"valid": False, "detail": f"Folder is not writable: {exc.strerror or exc}"}

    return {"valid": True, "detail": f"Ready to save into {path}", "resolved": str(path)}


def _show_folder_dialog(initial_directory: Path) -> str:
    """Open the host operating system's native directory chooser."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
        root.update_idletasks()
        return str(
            filedialog.askdirectory(
                parent=root,
                title="Select JobTailor output folder",
                initialdir=str(initial_directory),
                mustexist=True,
            )
            or ""
        )
    finally:
        root.destroy()


def select_folder(initial_path: str | None = None) -> dict[str, Any]:
    """Open a folder chooser and validate the selected directory immediately."""
    initial = Path(initial_path).expanduser() if initial_path else Path.home()
    if not initial.exists() or not initial.is_dir():
        initial = Path.home()

    selected = _show_folder_dialog(initial)
    if not selected:
        return {
            "cancelled": True,
            "valid": False,
            "detail": "Folder selection cancelled.",
        }

    result = check_folder(selected)
    return {"cancelled": False, **result}
