"""Filename sanitisation for generated PDFs (RG-FR-021).

Two shapes, deliberately different:

* Download name:  <profile-name>-<template-id>-resume.pdf   (slug, ASCII-only)
* Saved on disk:  <output>/<Profile Name>/<mm-dd-yy-HHMM>_<Company>_<Job Title>/<Profile>_resume.pdf

The on-disk shape is specified by the user and keeps spaces and capitals, so it
gets its own sanitiser: strict enough to be traversal-proof and legal on
Windows, loose enough to stay readable in Explorer. The HHMM component (local,
24-hour) exists so re-extracting the same company/role later the same day
gets its own folder instead of silently overwriting the earlier one.
"""

import re
from datetime import datetime

MAX_STEM_LENGTH = 100
FALLBACK = "resume.pdf"

MAX_COMPONENT_LENGTH = 80

# Windows refuses these as a filename stem regardless of extension.
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _slugify(value: str) -> str:
    text = (value or "").strip().lower()
    # Whitespace becomes hyphens; everything outside a conservative allowlist is
    # dropped. This also removes path separators, "..", drive letters, NUL and
    # every other traversal vector, so the result can never escape a directory.
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^a-z0-9\-_]", "", text)
    text = re.sub(r"-{2,}", "-", text).strip("-_")
    return text


def build_pdf_filename(profile_name: str, template_id: str) -> str:
    parts = [p for p in (_slugify(profile_name), _slugify(template_id)) if p]
    if not parts:
        return FALLBACK
    stem = "-".join([*parts, "resume"])[:MAX_STEM_LENGTH].strip("-")
    return f"{stem}.pdf" if stem else FALLBACK


def build_cover_letter_pdf_filename(profile_name: str, template_id: str) -> str:
    """Download-name shape for an ad-hoc cover letter PDF, mirroring
    build_pdf_filename's <profile-slug>-<template-slug>-resume.pdf."""
    parts = [p for p in (_slugify(profile_name), _slugify(template_id)) if p]
    if not parts:
        return "cover-letter.pdf"
    stem = "-".join([*parts, "cover-letter"])[:MAX_STEM_LENGTH].strip("-")
    return f"{stem}.pdf" if stem else "cover-letter.pdf"


def sanitize_component(value: str, fallback: str = "Unknown") -> str:
    """Make `value` safe as a single path component, preserving readability.

    Company names and job titles come straight from the scraped listing, so they
    routinely contain "/", ":" and similar. Every path separator is replaced
    rather than escaped, which also makes traversal ("..", "C:\\", leading "\\")
    impossible: the result cannot contain a separator at all.
    """
    text = (value or "").strip()
    # Path separators, Windows-illegal characters, and control codes.
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Windows silently strips trailing dots and spaces, which would make the
    # path we record differ from the path that actually exists on disk.
    text = text.strip(". ")
    if text.split(".")[0].upper() in WINDOWS_RESERVED:
        text = f"_{text}"
    text = text[:MAX_COMPONENT_LENGTH].strip(". ")
    return text or fallback


def build_job_folder_name(company: str, job_title: str, when: datetime | None = None) -> str:
    """`[mm-dd-yy-HHMM]_[Company]_[Job Title]`, one folder per generation run.

    `when` should be the extraction's own completion time (local), not
    "now" at whatever moment a PDF happens to render -- see
    tailored_resume_service._extraction_folder_timestamp(). That keeps the
    resume and cover letter from the same extraction in the same folder
    even if they're rendered a few seconds apart, while a genuinely new
    extraction still gets its own new folder.
    """
    stamp = (when or datetime.now()).strftime("%m-%d-%y-%H%M")
    return (
        f"{stamp}_{sanitize_component(company, 'Company')}"
        f"_{sanitize_component(job_title, 'Role')}"
    )


def build_tailored_pdf_filename(profile_name: str) -> str:
    """`<Profile Name>_resume.pdf`, as specified for the saved file."""
    return f"{sanitize_component(profile_name, 'profile')}_resume.pdf"


def build_tailored_cover_letter_filename(profile_name: str) -> str:
    """`<Profile Name>_cover_letter.pdf`, saved alongside the resume in the
    same per-job folder (see build_job_folder_name)."""
    return f"{sanitize_component(profile_name, 'profile')}_cover_letter.pdf"


def build_profile_folder_name(profile_name: str) -> str:
    """`<Profile Name>`, the top-level folder under the output root -- each
    profile's applications live in their own sibling folder there."""
    return sanitize_component(profile_name, "Profile")
