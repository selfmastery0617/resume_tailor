"""Tailored resume PDFs.

Turns a stored experience extraction into a resume PDF and writes it to the
output folder configured in Settings:

    <outputFolder>/<Profile Name>/<mm-dd-yy>_<Company>_<Job Title>/<Profile Name>_resume.pdf

The extraction's two roles *replace* the profile's experience section — that is
the point of the feature, and the counts (6 and 8 bullets, two projects) are
already resume-shaped. Everything else on the resume — name, contact details,
education, skills, template and styling — still comes from the profile, so a
tailored PDF is the user's own resume with a job-specific experience section.
"""

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db import get_db
from app.models import generated_documents, profiles, templates
from app.schemas.resume import Experience, Profile, ResumeData, Skill
from app.services import experience_service, profile_service, resume_service, settings_service
from app.services.pdf.filename import (
    build_job_folder_name,
    build_profile_folder_name,
    build_tailored_pdf_filename,
)
from app.services.progress import progress


class TailoredResumeError(RuntimeError):
    """Anything the user can fix from the UI: no folder, no profile, no data."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# -- experience -> resume content -----------------------------------------

# "2019 - 2022", "2020 – Present", "2021 -" (still there), "2018".
_PRESENT = re.compile(r"^(present|current|now)$", re.IGNORECASE)


def _split_timeline(timeline: str) -> tuple[str, str, bool]:
    """`"2019 - 2022"` -> `("2019", "2022", False)`. Returns (start, end, current)."""
    text = (timeline or "").strip()
    if not text:
        return "", "", False

    # Both hyphen and en/em dash appear in hand-written database.json entries.
    parts = [p.strip() for p in re.split(r"\s*[-–—]\s*", text, maxsplit=1)]
    start = parts[0]
    if len(parts) == 1:
        # A bare "2018" says when the role started and nothing about its end.
        # Reading that as "still there" would put "Present" on the resume on the
        # strength of a guess, so leave the end date blank instead.
        return start, "", False

    end = parts[1]
    # An explicitly open-ended range ("2021 -", "2020 - Present") does mean the
    # role is ongoing; RG-FR-007 renders that as "Present".
    if not end or _PRESENT.match(end):
        return start, "", True
    return start, end, False


_YEAR = re.compile(r"(19|20)\d{2}")


def _year_only(text: str) -> str:
    """"Mar 2021" -> "2021". Resumes here carry years, never months."""
    match = _YEAR.search(text or "")
    return match.group(0) if match else ""


def _timelines(experience: dict[str, Any]) -> dict[str, tuple[str, str, bool]]:
    """The date range for each role, as (start, end, current).

    Two settings fix both roles. The first company is the earlier one and the
    user gives its exact years — 2016 to 2019. The later role then runs from
    that end year to now, because there is no gap between them: 2019 to
    Present. One number therefore appears twice, which is exactly why it is
    stored once rather than typed into two places that can disagree.

    With the years unset, the corpus timelines are used as before, reduced to
    years so the format is the same either way.
    """
    from app.services import settings_service

    stored = settings_service.get_settings()
    start = (stored.get("firstCompanyStartYear") or "").strip()
    end = (stored.get("firstCompanyEndYear") or "").strip()

    if start and end:
        return {"job1": (start, end, False), "job2": (end, "", True)}

    fallback: dict[str, tuple[str, str, bool]] = {}
    for key in ("job1", "job2"):
        raw = (experience.get(key) or {}).get("timeline") or ""
        from_year, to_year, current = _split_timeline(raw)
        fallback[key] = (_year_only(from_year), _year_only(to_year), current)
    return fallback


def _role_details(data: ResumeData, company: str) -> tuple[str, str, str]:
    """Job title, location, and company summary from what the user wrote.

    database.json records company/product/timeline but no job title, and
    inventing one would contradict the "do not invent employers or dates" rule
    the bullet prompt enforces. So: reuse the profile's own entry for that
    company when there is one, else fall back to the profile's professional
    title, which is the user's own claim about themselves.
    """
    target = (company or "").strip().casefold()
    for entry in data.experience:
        if (entry.company or "").strip().casefold() == target:
            return entry.title, entry.location, entry.companySummary
    return data.profile.professionalTitle, "", ""


def build_tailored_data(profile: Profile, experience: dict[str, Any]) -> ResumeData:
    """Profile content with its experience section replaced by the extraction.

    Job 2 is the recent role and Job 1 the earlier one, so they are emitted in
    that order — resumes read most-recent-first.
    """
    data = profile.data.model_copy(deep=True)
    timelines = _timelines(experience)

    roles: list[Experience] = []
    for key in ("job2", "job1"):
        selection = experience.get(key) or {}
        bullets = [b for b in (selection.get("bullets") or []) if b.strip()]
        if not bullets:
            continue

        company = selection.get("company") or ""
        fallback_title, location, profile_company_summary = _role_details(data, company)
        start, end, current = timelines.get(key, ("", "", False))

        # The extraction writes its own headline per role now (see
        # _revise_with_chatgpt in experience_service.py) -- it wins over the
        # profile-lookup fallback above, and renders below the company name
        # (ExperienceRoleTitle already renders Experience.title bold, so no
        # template change is needed for that part). Product name is left off
        # for now -- just the title alone.
        role_title = (selection.get("title") or "").strip()
        title = role_title or fallback_title

        roles.append(
            Experience(
                id=f"tailored-{key}",
                company=company,
                title=title,
                location=location,
                startDate=start,
                endDate=end,
                current=current,
                # Stored extractions created before company summaries existed
                # have neither key, so tailored roles remain backwards-safe.
                companySummary=(
                    selection.get("companySummary")
                    or selection.get("summary")
                    or profile_company_summary
                    or ""
                ).strip(),
                # RG-FR-005: one bullet per line.
                description="\n".join(b.strip() for b in bullets),
            )
        )

    if not roles:
        raise TailoredResumeError(
            "The stored extraction has no bullets. Re-run Extract for this job."
        )

    data.experience = roles

    # The extraction's summary and title are written for this specific job, so
    # they win over the profile's general ones. Empty values (DeepSeek
    # unavailable) leave the profile's own text in place rather than blanking
    # the headline of the resume.
    summary = (experience.get("summary") or "").strip()
    if summary:
        data.profile.summary = summary

    title = (experience.get("title") or "").strip()
    if title:
        data.profile.professionalTitle = title

    # Same reasoning as summary/title: a job-tailored skill set wins over the
    # profile's own static one, but only when there is one to use -- an empty
    # list (DeepSeek unavailable) leaves the profile's skills in place rather
    # than blanking the section. Where it renders is up to the template's own
    # "skills" block placement, not this function.
    #
    # skillGroups is ChatGPT's categorization of skillSet (see
    # _revise_with_chatgpt's step 7 in experience_service.py) -- real
    # categories, so SkillsContentBlock/SkillsSection
    # (frontend/src/resume/blocks.tsx) bold each one and put it on its own
    # line. When ChatGPT never ran or its categorization didn't parse,
    # skillGroups is empty and every skill falls into one uncategorized
    # group instead (Skill.category's own "Other" default).
    skill_groups = [
        (str(group.get("category") or "").strip(), [str(s).strip() for s in (group.get("skills") or []) if str(s).strip()])
        for group in (experience.get("skillGroups") or [])
    ]
    skill_groups = [(category, names) for category, names in skill_groups if category and names]

    if skill_groups:
        data.skills = [
            Skill(id=f"tailored-skill-{i}-{j}", name=name, category=category)
            for i, (category, names) in enumerate(skill_groups)
            for j, name in enumerate(names)
        ]
    else:
        skill_set = [s.strip() for s in (experience.get("skillSet") or []) if s.strip()]
        if skill_set:
            data.skills = [Skill(id=f"tailored-skill-{i}", name=name) for i, name in enumerate(skill_set)]

    return data


# -- generation ------------------------------------------------------------


def resolve_profile(profile_id: str | None = None) -> Profile:
    """Explicit id, else the Settings choice, else the only/first profile."""
    if profile_id:
        return profile_service.get_profile(profile_id)

    configured = (settings_service.get_settings().get("resumeProfile") or "").strip()
    if configured:
        try:
            return profile_service.get_profile(configured)
        except profile_service.ProfileNotFound:
            # Validation rejects a stale id at save time, but the profile can be
            # deleted afterwards. Fall through rather than dead-ending here.
            pass

    profiles = profile_service.list_profiles()
    if not profiles:
        raise TailoredResumeError(
            "No profile exists yet. Create one on the Profile tab first."
        )
    return profiles[0]


def _output_root() -> Path:
    configured = (settings_service.get_settings().get("outputFolder") or "").strip()
    if not configured:
        raise TailoredResumeError(
            "Set an output folder in Settings before generating resumes."
        )
    root = Path(configured).expanduser()
    if not root.is_dir():
        raise TailoredResumeError(f"The output folder no longer exists: {root}")
    return root


async def generate_for_job(
    job_id: str,
    company: str,
    job_title: str,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Render the tailored PDF, save it under the output folder, and record it."""
    experience = experience_service.get_experience(job_id)
    if experience is None:
        raise TailoredResumeError(
            "Extract experience for this job before generating a resume."
        )

    root = _output_root()
    profile = resolve_profile(profile_id)

    folder = root / build_profile_folder_name(profile.name) / build_job_folder_name(company, job_title)
    file_name = build_tailored_pdf_filename(profile.name)
    destination = folder / file_name

    progress.emit(
        "resume",
        f"Building resume for “{job_title or 'this role'}” as {profile.name}",
        level="step",
        folder=str(folder),
    )

    data = build_tailored_data(profile, experience)
    # persist=False: the record is written once below, with the storage key and
    # page count filled in, rather than twice with the first row incomplete.
    render_payload, _ = resume_service.build_render_payload(profile.id, draft_data=data)
    pdf_bytes, _download_name = await resume_service.generate_resume_pdf(
        profile_id=profile.id,
        draft_data=data,
        job_application_id=job_id,
        persist=False,
    )

    try:
        folder.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(pdf_bytes)
    except OSError as exc:
        raise TailoredResumeError(
            f"Could not write {destination}: {exc.strerror or exc}"
        ) from exc

    template_id = profile_service.get_template_settings(profile.id).templateId
    record = {
        "jobId": job_id,
        "profileId": profile.id,
        "profileName": profile.name,
        "templateId": template_id,
        "folder": str(folder),
        "fileName": file_name,
        "filePath": str(destination),
        "pageCount": _page_count_of(pdf_bytes),
        "byteSize": len(pdf_bytes),
        "generatedAt": _now(),
    }
    _save_record(record, render_payload)
    # A resume exists, so the row is ready to send. Never walks an applied row
    # backwards -- see mark_ready.
    from app.services import job_store

    job_store.mark_ready(job_id)

    progress.emit(
        "resume",
        f"Saved {file_name} ({record['pageCount']} page"
        f"{'s' if record['pageCount'] != 1 else ''}) to {folder}",
        level="result",
        preview=str(destination),
    )
    # Read back rather than returning `record`: the listing endpoint adds an
    # `exists` flag, and a response that omitted it would leave the freshly
    # generated row rendering as "file missing".
    return get_record(job_id) or record


def _page_count_of(pdf_bytes: bytes) -> int:
    """Read the count back from the PDF rather than trusting the renderer."""
    try:
        import io

        from pypdf import PdfReader

        return len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    except Exception:  # noqa: BLE001 - a page count is not worth failing a save
        return 0


# -- persistence -----------------------------------------------------------


def _save_record(record: dict[str, Any], payload: dict[str, Any]) -> None:
    """Record the document. One table now, not two saying overlapping things."""
    from app.services import resume_service

    resume_service.record_document(
        profile_id=record["profileId"],
        job_id=record["jobId"],
        payload=payload,
        file_name=record["fileName"],
        byte_size=record["byteSize"],
        page_count=record["pageCount"],
        # Where the bytes actually are. A filesystem path today; an object key
        # once this stops running on the machine that reads it.
        storage_key=record["filePath"],
    )


def _row_to_record(row) -> dict[str, Any]:
    record = {
        "jobId": str(row.job_id) if row.job_id else "",
        "profileId": str(row.profile_id),
        "profileName": row.profile_name or "",
        "templateId": row.template_key or "",
        "folder": str(Path(row.storage_key).parent) if row.storage_key else "",
        "fileName": row.file_name,
        "filePath": row.storage_key or "",
        "pageCount": row.page_count,
        "byteSize": row.byte_size,
        "generatedAt": row.generated_at.isoformat() if row.generated_at else "",
    }
    # The file can be moved or deleted from Explorer; the badge should say so
    # rather than offering a download that 404s.
    record["exists"] = bool(row.storage_key) and Path(row.storage_key).is_file()
    return record


def _saved_documents():
    """Documents that were written to the output folder, newest per job."""
    from sqlalchemy import select

    return (
        select(
            generated_documents.c.job_id,
            generated_documents.c.profile_id,
            generated_documents.c.file_name,
            generated_documents.c.storage_key,
            generated_documents.c.page_count,
            generated_documents.c.byte_size,
            generated_documents.c.generated_at,
            profiles.c.name.label("profile_name"),
            templates.c.key.label("template_key"),
        )
        .select_from(
            generated_documents.join(
                profiles, profiles.c.id == generated_documents.c.profile_id
            ).outerjoin(templates, templates.c.id == generated_documents.c.template_id)
        )
        .where(
            generated_documents.c.storage_key.isnot(None),
            generated_documents.c.deleted_at.is_(None),
            # Without this, the newest-per-job pick below could surface a
            # cover letter row instead of the resume (both now live in this
            # same table, told apart only by kind).
            generated_documents.c.kind == "resume",
        )
    )


def get_record(job_id: str) -> dict[str, Any] | None:
    from app.services import job_store

    with get_db() as conn:
        job_row = job_store._find(conn, job_id)
        if job_row is None:
            return None
        row = conn.execute(
            _saved_documents()
            .where(generated_documents.c.job_id == job_row.id)
            .order_by(generated_documents.c.generated_at.desc())
            .limit(1)
        ).first()
    return _row_to_record(row) if row else None


def all_records() -> dict[str, dict[str, Any]]:
    """Every saved resume, so the table can restore its badges after a reload."""
    with get_db() as conn:
        rows = conn.execute(
            _saved_documents().order_by(generated_documents.c.generated_at.desc())
        ).all()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        # Newest first, so the first row seen for a job is the current one.
        key = str(row.job_id) if row.job_id else ""
        if key and key not in out:
            out[key] = _row_to_record(row)
    return out


def read_pdf(job_id: str) -> tuple[bytes, str]:
    """Bytes of the saved PDF, for serving it back to the browser."""
    record = get_record(job_id)
    if record is None:
        raise TailoredResumeError("No resume has been generated for this job.")
    path = Path(record["filePath"])
    if not path.is_file():
        raise TailoredResumeError(f"The saved file is missing: {path}")
    return path.read_bytes(), record["fileName"]


def open_folder(job_id: str) -> None:
    """Open the saved PDF's folder in Explorer, with the file itself selected.

    Backend and browser run on the same machine here (a local desktop app,
    not a hosted multi-user one) -- see shared_browser.py's shared sign-in
    window for the same assumption elsewhere in this app -- so it's safe for
    the backend to launch a native Explorer window directly.
    """
    record = get_record(job_id)
    if record is None:
        raise TailoredResumeError("No resume has been generated for this job.")

    path = Path(record["filePath"])
    if path.is_file():
        # Explorer's own exit code is unreliable (often non-zero even when it
        # opens fine), so this doesn't check returncode -- only that the
        # process could be launched at all.
        subprocess.Popen(["explorer", "/select,", str(path)])
        return

    folder = Path(record["folder"])
    if folder.is_dir():
        subprocess.Popen(["explorer", str(folder)])
        return

    raise TailoredResumeError(f"The saved file and its folder are both missing: {path}")


__all__ = [
    "TailoredResumeError",
    "all_records",
    "build_tailored_data",
    "generate_for_job",
    "get_record",
    "open_folder",
    "read_pdf",
    "resolve_profile",
]
