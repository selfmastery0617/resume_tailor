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

from .render_cache import render_cache

load_dotenv()

# Page specification (6.1). These values are the single source of truth; the
# React renderer mirrors them so preview and PDF agree.
PAGE_FORMAT = "Letter"
MARGIN_TOP_IN = 0.7
MARGIN_BOTTOM_IN = 0.5
MARGIN_LEFT_IN = 0.65
MARGIN_RIGHT_IN = 0.65

READY_ATTR = "data-pdf-ready"
HARD_TIMEOUT_S = 30.0  # RG-FR-023
NAV_TIMEOUT_MS = 20_000
READY_TIMEOUT_MS = 20_000

APP_NAME = "JobTailor AI"
PRODUCER = "JobTailor AI PDF Service"


class PdfGenerationError(RuntimeError):
    """Raised for any failure that should surface as PDF_GENERATION_FAILED."""


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
    """Attach document metadata (RG-FR-022)."""
    from pypdf import PdfReader, PdfWriter

    profile = (payload.get("data") or {}).get("profile") or {}
    name = (profile.get("fullName") or "").strip() or "Resume"
    title = (profile.get("professionalTitle") or "").strip()
    skills = [s.get("name", "") for s in (payload.get("data") or {}).get("skills", [])]
    keywords = ", ".join([p for p in [title, *skills[:10]] if p])

    now = datetime.now(timezone.utc).strftime("D:%Y%m%d%H%M%SZ")

    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata(
        {
            "/Author": name,
            "/Title": f"{name} — {title}" if title else name,
            "/Subject": "Resume",
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

            pdf_bytes = page.pdf(
                format=PAGE_FORMAT,
                print_background=True,  # 6.1
                margin={
                    "top": f"{MARGIN_TOP_IN}in",
                    "bottom": f"{MARGIN_BOTTOM_IN}in",
                    "left": f"{MARGIN_LEFT_IN}in",
                    "right": f"{MARGIN_RIGHT_IN}in",
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
