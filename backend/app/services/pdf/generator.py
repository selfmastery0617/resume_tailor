"""Resume PDF generation (section 6).

Playwright drives the *application's own* print route, so the PDF is produced
by the same React renderer as the preview (RG-FR-015). There is no second,
server-side resume renderer to drift out of sync.

Threading matches DeepSeekService: Playwright's sync API runs on a worker
thread because uvicorn selects a SelectorEventLoop on Windows under --reload,
and that loop cannot spawn the driver subprocess.
"""

import asyncio
import hashlib
import io
import os
import time
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

from app.schemas.layout import PAPER_DIMENSIONS_IN

from .render_cache import render_cache

load_dotenv()

DEFAULT_PAGE_SIZE = "letter"
DEFAULT_MARGINS_IN = {
    "top": 0.7,
    "bottom": 0.5,
    "left": 0.65,
    "right": 0.65,
}

READY_ATTR = "data-pdf-ready"
HARD_TIMEOUT_S = 30.0  # RG-FR-023
NAV_TIMEOUT_MS = 20_000
READY_TIMEOUT_MS = 20_000

APP_NAME = "JobTailor AI"
PRODUCER = "JobTailor AI PDF Service"


class PdfGenerationError(RuntimeError):
    """Raised for any failure that should surface as PDF_GENERATION_FAILED."""


def _page_spec(payload: dict[str, Any]) -> tuple[float, float, dict[str, float]]:
    """Validated template geometry, with legacy/built-in Letter fallbacks.

    A resume reads page size/margins from payload.layout.page (see
    TemplateLayoutV2 in layoutTypes.ts) -- a cover letter has no layout
    document at all (see CoverLetterStyle, app/schemas/cover_letter_style.py),
    so its own pageSize/marginTopIn/etc. live directly on payload.style
    instead. Both shapes use the same field names, so the rest of this
    function doesn't need to care which one it's reading.
    """

    if payload.get("documentType") == "coverLetter":
        page = payload.get("style") or {}
    else:
        layout = payload.get("layout")
        page = layout.get("page") if isinstance(layout, dict) else None
    page = page if isinstance(page, dict) else {}
    size = page.get("size") or page.get("pageSize") or DEFAULT_PAGE_SIZE
    width, height = PAPER_DIMENSIONS_IN.get(size, PAPER_DIMENSIONS_IN[DEFAULT_PAGE_SIZE])

    def margin(field: str, fallback: float) -> float:
        value = page.get(field, fallback)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return fallback
        return max(0.0, min(2.0, float(value)))

    margins = {
        "top": margin("marginTopIn", DEFAULT_MARGINS_IN["top"]),
        "bottom": margin("marginBottomIn", DEFAULT_MARGINS_IN["bottom"]),
        "left": margin("marginLeftIn", DEFAULT_MARGINS_IN["left"]),
        "right": margin("marginRightIn", DEFAULT_MARGINS_IN["right"]),
    }
    return width, height, margins


def frontend_base_url() -> str:
    return os.getenv("FRONTEND_URL", "http://127.0.0.1:5173").rstrip("/")


def content_hash(payload: dict[str, Any]) -> str:
    """Stable SHA-256 over the exact inputs that determine the document."""
    import json

    canonical = json.dumps(
        {
            "templateId": payload.get("templateId"),
            "templateVersion": payload.get("templateVersion"),
            "data": payload.get("data"),
            "style": payload.get("style"),
            # Part of what determines the document, so two renders of the same
            # template id at different layouts must not share a hash.
            "layout": payload.get("layout"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _apply_metadata(pdf_bytes: bytes, payload: dict[str, Any]) -> bytes:
    """Attach document metadata (RG-FR-022).

    /Title is what a browser shows as the new tab's title when a PDF is
    opened inline -- a cover letter's payload.data has no `profile` key at
    all (see CoverLetterData, app/schemas/cover_letter.py), so reading
    resume-shaped fields from it always fell through to the "Resume"
    fallback below, regardless of which document this actually was.
    """
    from pypdf import PdfReader, PdfWriter

    data = payload.get("data") or {}
    if payload.get("documentType") == "coverLetter":
        name = (data.get("candidateName") or "").strip() or "Cover Letter"
        job_title = (data.get("jobTitle") or "").strip()
        company = (data.get("companyName") or "").strip()
        subject = "Cover Letter"
        title = f"{name} — Cover Letter" + (f" ({job_title} at {company})" if job_title and company else "")
        keywords = ", ".join(p for p in [job_title, company] if p)
    else:
        profile = data.get("profile") or {}
        name = (profile.get("fullName") or "").strip() or "Resume"
        role_title = (profile.get("professionalTitle") or "").strip()
        skills = [s.get("name", "") for s in data.get("skills", [])]
        subject = "Resume"
        title = f"{name} — {role_title}" if role_title else name
        keywords = ", ".join([p for p in [role_title, *skills[:10]] if p])

    now = datetime.now(timezone.utc).strftime("D:%Y%m%d%H%M%SZ")

    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata(
        {
            "/Author": name,
            "/Title": title,
            "/Subject": subject,
            "/Keywords": keywords,
            "/Creator": APP_NAME,
            "/Producer": PRODUCER,
            "/CreationDate": now,
            "/ModDate": now,
        }
    )
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _render_sync(token: str, headless: bool = True) -> tuple[bytes, int]:
    """Navigate the print route and return (pdf_bytes, page_count)."""
    from playwright.sync_api import sync_playwright

    url = f"{frontend_base_url()}/print?token={token}"
    started = time.monotonic()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless, args=["--no-sandbox"])
        # RG-FR-018: the browser must close on every path — navigation failure,
        # ready-selector timeout, PDF failure, metadata failure.
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")

            # RG-FR-017: wait for an explicit ready signal rather than a sleep.
            # state="attached", not the default "visible": the error signal is an
            # empty div, which is attached but has zero size, so waiting for
            # visibility would hang until timeout instead of reporting the error.
            page.wait_for_selector(
                f"[{READY_ATTR}]", state="attached", timeout=READY_TIMEOUT_MS
            )
            state = page.get_attribute(f"[{READY_ATTR}]", READY_ATTR)
            if state == "error":
                message = page.get_attribute(f"[{READY_ATTR}]", "data-pdf-error") or "unknown"
                raise PdfGenerationError(f"The print page reported an error: {message}")
            if state != "true":
                raise PdfGenerationError(f"Print page never became ready (state={state!r}).")

            if time.monotonic() - started > HARD_TIMEOUT_S:
                raise PdfGenerationError("PDF generation exceeded the 30s timeout.")

            payload = render_cache.get(token) or {}
            page_width, page_height, margins = _page_spec(payload)
            pdf_bytes = page.pdf(
                width=f"{page_width}in",
                height=f"{page_height}in",
                print_background=True,  # 6.1
                margin={
                    side: f"{value}in" for side, value in margins.items()
                },
            )
            page_count = page.evaluate("() => window.__resumePageCount ?? 0")
            return pdf_bytes, int(page_count or 0)
        finally:
            browser.close()


async def generate_pdf(payload: dict[str, Any]) -> tuple[bytes, int]:
    """Render `payload` to PDF bytes. Returns (bytes, page_count)."""
    token = render_cache.put(payload)
    try:
        pdf_bytes, page_count = await asyncio.wait_for(
            asyncio.to_thread(_render_sync, token),
            timeout=HARD_TIMEOUT_S,
        )
    except asyncio.TimeoutError as exc:
        raise PdfGenerationError("PDF generation exceeded the 30s timeout.") from exc
    finally:
        # One token, one render — invalidate immediately rather than waiting
        # for the TTL to lapse.
        render_cache.discard(token)

    pdf_bytes = _apply_metadata(pdf_bytes, payload)
    return pdf_bytes, page_count
