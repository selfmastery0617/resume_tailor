"""Application settings, persisted in SQLite.

The existing skill-extraction prompt lived only in React state and reset on
every reload; storing settings here fixes that and gives Phase 5 somewhere to
read the tailoring prompt and output folder from.
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db import get_db

DEFAULT_SKILLS_PROMPT = """Extract the following from this job description:
1. Main Skills - the key technical and professional skills required, as a concise comma-separated list.
2. Job Mission - the core purpose of this role, in one sentence.

Respond in exactly this format:
Skills: <comma-separated list>
Mission: <one sentence>"""

DEFAULT_TAILORING_PROMPT = """You are tailoring a resume and cover letter for a specific job.

Using the candidate profile and the job description below, produce:
1. A resume summary (2-3 sentences) aligned to this role.
2. Rewritten experience bullets that emphasise the most relevant achievements.
   Keep every claim truthful to the original profile - do not invent employers,
   titles, dates, or metrics.
3. A concise cover letter (3 short paragraphs) addressed to the hiring team.

Return the sections clearly separated with these exact headings:
=== SUMMARY ===
=== EXPERIENCE ===
=== COVER LETTER ==="""

DEFAULTS: dict[str, Any] = {
    "skillsPrompt": DEFAULT_SKILLS_PROMPT,
    "tailoringPrompt": DEFAULT_TAILORING_PROMPT,
    "outputFolder": "",
    # Which signed-in provider Phase 5 uses to generate content.
    "generationModel": "deepseek",
}

ALLOWED_MODELS = ("deepseek", "chatgpt")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def get_settings() -> dict[str, Any]:
    """Stored settings merged over defaults, so a new key never returns None."""
    with get_db() as conn:
        rows = conn.execute("SELECT key, value_json FROM app_settings").fetchall()
    stored = {row["key"]: json.loads(row["value_json"]) for row in rows}
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
        elif not isinstance(value, str):
            raise ValueError(f"{key} must be text.")

        cleaned[key] = value
    return cleaned


def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    cleaned = validate_settings(patch)
    now = _now()
    with get_db() as conn:
        for key, value in cleaned.items():
            conn.execute(
                "INSERT INTO app_settings (key, value_json, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET"
                "   value_json = excluded.value_json, updated_at = excluded.updated_at",
                (key, json.dumps(value), now),
            )
    return get_settings()


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
