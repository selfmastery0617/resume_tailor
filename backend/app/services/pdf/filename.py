"""Filename sanitisation for generated PDFs (RG-FR-021).

Target shape:  <profile-name>-<template-id>-resume.pdf
Example:       alex-chen-template-4-resume.pdf
"""

import re

MAX_STEM_LENGTH = 100
FALLBACK = "resume.pdf"


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
