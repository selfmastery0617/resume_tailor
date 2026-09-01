/** Print-only route consumed by the PDF generator (RG-FR-016, RG-FR-017).
 *
 *  Deliberately contains no application chrome: no nav, buttons, dialogs,
 *  toasts, editing controls or app background — only the document itself.
 *
 *  Signals readiness with data-pdf-ready="true" (or "error"), which Playwright
 *  waits for instead of sleeping. Renders either a resume (the default) or a
 *  cover letter, dispatching on payload.documentType -- see _page_spec's own
 *  matching branch in pdf/generator.py, which resolves page geometry the
 *  same way for both.
 */

import { useEffect, useState } from "react";
import { BACKEND_URL } from "../config";
import { CoverLetterRenderer } from "../resume/CoverLetterRenderer";
import type { CoverLetterData, CoverLetterStyle } from "../resume/coverLetterTypes";
import { coverLetterPageGeometry, pageGeometry } from "../resume/pageGeometry";
import { getRenderer } from "../resume/templates";
import type { ResumeData, ResumeStyle } from "../resume/types";

interface ResumeRenderPayload {
  documentType?: "resume";
  templateId: string;
  templateVersion: number;
  rendererKey: string;
  data: ResumeData;
  style: ResumeStyle;
  /** Present for user templates; the layout-v1 renderer needs it. */
  layout?: unknown;
}

interface CoverLetterRenderPayload {
  documentType: "coverLetter";
  templateId: string;
  data: CoverLetterData;
  style: CoverLetterStyle;
}

type RenderPayload = ResumeRenderPayload | CoverLetterRenderPayload;

export function PrintPage() {
  const [payload, setPayload] = useState<RenderPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const token = new URLSearchParams(window.location.search).get("token");
  const isCoverLetter = payload?.documentType === "coverLetter";
  const geometry = isCoverLetter
    ? coverLetterPageGeometry(payload.style)
    : pageGeometry(payload && "layout" in payload ? payload.layout : undefined);

  useEffect(() => {
    if (!token) {
      setError("Missing render token");
      return;
    }
    (async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/api/render/${encodeURIComponent(token)}`);
        if (!response.ok) throw new Error(`payload fetch failed (${response.status})`);
        setPayload((await response.json()) as RenderPayload);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load render payload");
      }
    })();
  }, [token]);

  // Only signal ready once fonts are settled and a frame has painted —
  // otherwise Chromium can capture mid-layout with fallback fonts.
  useEffect(() => {
    if (!payload) return;
    let cancelled = false;
    (async () => {
      try {
        await document.fonts?.ready;
      } catch {
        /* font loading is best-effort */
      }
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          if (cancelled) return;
          // Exposed for the generator's page-count metric.
          const el = document.querySelector(".resume-document, .cover-letter-document");
          const pageHeightPx = geometry.contentHeightIn * 96;
          (window as unknown as { __resumePageCount?: number }).__resumePageCount = el
            ? Math.max(1, Math.ceil(el.getBoundingClientRect().height / pageHeightPx))
            : 1;
          setReady(true);
        }),
      );
    })();
    return () => {
      cancelled = true;
    };
  }, [payload, geometry.contentHeightIn]);

  if (error) {
    return <div data-pdf-ready="error" data-pdf-error={error} />;
  }
  if (!payload) {
    // No ready attribute yet: the generator keeps waiting.
    return <div />;
  }

  return (
    <div {...(ready ? { "data-pdf-ready": "true" } : {})}>
      <div style={{ width: `${geometry.contentWidthIn}in` }}>
        {isCoverLetter ? (
          <CoverLetterRenderer data={payload.data} style={payload.style} />
        ) : (
          (() => {
            const Renderer = getRenderer(payload.rendererKey);
            return <Renderer data={payload.data} style={payload.style} layout={payload.layout} />;
          })()
        )}
      </div>
    </div>
  );
}
