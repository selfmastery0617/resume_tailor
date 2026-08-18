"""Tailored resume PDFs.

Turns a stored experience extraction into a resume PDF and writes it to the
output folder configured in Settings:

    <outputFolder>/<mm-dd-yy>_<Company>_<Job Title>/<Profile Name>_resume.pdf

The extraction's two roles *replace* the profile's experience section — that is
the point of the feature, and the counts (6 and 8 bullets, two projects) are
already resume-shaped. Everything else on the resume — name, contact details,
education, skills, template and styling — still comes from the profile, so a
tailored PDF is the user's own resume with a job-specific experience section.
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db import get_db
from app.schemas.resume import Experience, Profile, ResumeData
from app.services import experience_service, profile_service, resume_service, settings_service
from app.services.pdf.filename import build_job_folder_name, build_tailored_pdf_filename
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


def _role_details(data: ResumeData, company: str) -> tuple[str, str]:
    """Job title and location for `company`, taken from what the user wrote.

    database.json records company/product/timeline but no job title, and
    inventing one would contradict the "do not invent employers or dates" rule
    the bullet prompt enforces. So: reuse the profile's own entry for that
    company when there is one, else fall back to the profile's professional
    title, which is the user's own claim about themselves.
    """
    target = (company or "").strip().casefold()
    for entry in data.experience:
        if (entry.company or "").strip().casefold() == target:
            return entry.title, entry.location
    return data.profile.professionalTitle, ""


def build_tailored_data(profile: Profile, experience: dict[str, Any]) -> ResumeData:
    """Profile content with its experience section replaced by the extraction.

    Job 2 is the recent role and Job 1 the earlier one, so they are emitted in
    that order — resumes read most-recent-first.
    """
    data = profile.data.model_copy(deep=True)

    roles: list[Experience] = []
    for key in ("job2", "job1"):
        selection = experience.get(key) or {}
        bullets = [b for b in (selection.get("bullets") or []) if b.strip()]
        if not bullets:
            continue

        company = selection.get("company") or ""
        title, location = _role_details(data, company)
        start, end, current = _split_timeline(selection.get("timeline") or "")

        roles.append(
            Experience(
                id=f"tailored-{key}",
                company=company,
                title=title,
                location=location,
                startDate=start,
                endDate=end,
                current=current,
                # RG-FR-005: one bullet per line.
                description="\n".join(b.strip() for b in bullets),
            )
        )

    if not roles:
        raise TailoredResumeError(
            "The stored extraction has no bullets. Re-run Extract for this job."
        )

    data.experience = roles

    # The extraction's summary is written for this specific job, so it wins over
    # the profile's general one. An empty summary (DeepSeek unavailable) leaves
    # the profile's own text in place rather than blanking the section.
    summary = (experience.get("summary") or "").strip()
    if summary:
        data.profile.summary = summary

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

    folder = root / build_job_folder_name(company, job_title)
    file_name = build_tailored_pdf_filename(profile.name)
    destination = folder / file_name

    progress.emit(
        "resume",
        f"Building resume for “{job_title or 'this role'}” as {profile.name}",
        level="step",
        folder=str(folder),
    )

    data = build_tailored_data(profile, experience)
    pdf_bytes, _download_name = await resume_service.generate_resume_pdf(
        profile_id=profile.id,
        draft_data=data,
        job_application_id=job_id,
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
    _save_record(record)
    # The path in generated_resumes is what makes the history row point at a
    # real file instead of just naming one.
    _link_generated_row(job_id, str(destination))

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


def _save_record(record: dict[str, Any]) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO job_resume"
            " (job_id, profile_id, profile_name, template_id, folder, file_name,"
            "  file_path, page_count, byte_size, generated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(job_id) DO UPDATE SET"
            "   profile_id = excluded.profile_id,"
            "   profile_name = excluded.profile_name,"
            "   template_id = excluded.template_id,"
            "   folder = excluded.folder,"
            "   file_name = excluded.file_name,"
            "   file_path = excluded.file_path,"
            "   page_count = excluded.page_count,"
            "   byte_size = excluded.byte_size,"
            "   generated_at = excluded.generated_at",
            (
                record["jobId"],
                record["profileId"],
                record["profileName"],
                record["templateId"],
                record["folder"],
                record["fileName"],
                record["filePath"],
                record["pageCount"],
                record["byteSize"],
                record["generatedAt"],
            ),
        )


def _link_generated_row(job_id: str, path: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE generated_resumes SET file_path = ?"
            " WHERE id = (SELECT id FROM generated_resumes"
            "             WHERE job_application_id = ?"
            "             ORDER BY generated_at DESC LIMIT 1)",
            (path, job_id),
        )


def _row_to_record(row) -> dict[str, Any]:
    record = {
        "jobId": row["job_id"],
        "profileId": row["profile_id"],
        "profileName": row["profile_name"],
        "templateId": row["template_id"],
        "folder": row["folder"],
        "fileName": row["file_name"],
        "filePath": row["file_path"],
        "pageCount": row["page_count"],
        "byteSize": row["byte_size"],
        "generatedAt": row["generated_at"],
    }
    # The file can be moved or deleted from Explorer; the badge should say so
    # rather than offering a download that 404s.
    record["exists"] = Path(row["file_path"]).is_file()
    return record


def get_record(job_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM job_resume WHERE job_id = ?", (job_id,)).fetchone()
    return _row_to_record(row) if row else None


def all_records() -> dict[str, dict[str, Any]]:
    """Every saved resume, so the table can restore its badges after a reload."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM job_resume").fetchall()
    return {row["job_id"]: _row_to_record(row) for row in rows}


def read_pdf(job_id: str) -> tuple[bytes, str]:
    """Bytes of the saved PDF, for serving it back to the browser."""
    record = get_record(job_id)
    if record is None:
        raise TailoredResumeError("No resume has been generated for this job.")
    path = Path(record["filePath"])
    if not path.is_file():
        raise TailoredResumeError(f"The saved file is missing: {path}")
    return path.read_bytes(), record["fileName"]


__all__ = [
    "TailoredResumeError",
    "all_records",
    "build_tailored_data",
    "generate_for_job",
    "get_record",
    "read_pdf",
    "resolve_profile",
]
