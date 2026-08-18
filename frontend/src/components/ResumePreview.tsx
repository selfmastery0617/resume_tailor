/** Paginated US-Letter preview.
 *
 *  Shows *every* page, not just the first, and uses exactly the PDF's page
 *  geometry (section 6.1) so preview and output stay in parity (RG-FR-015):
 *
 *    - page frame  = 8.5in x 11in
 *    - content box = 7.2in x 9.8in (page minus the 0.7/0.5/0.65/0.65 margins)
 *
 *  The document itself renders content only; page geometry lives here, and in
 *  the PDF it comes from Playwright's margin box. Both therefore wrap the same
 *  content at the same width.
 *
 *  Pagination works by measuring the flowed content once and showing each
 *  page-height slice through its own window. 9.5 allows scaling the preview
 *  visually as long as the internal page dimensions stay US Letter, which is
 *  why the transform is applied to a true-size frame.
 */

import { useLayoutEffect, useRef, useState } from "react";
import { CONTENT_HEIGHT_IN, CONTENT_WIDTH_IN, PAGE } from "../resume/ResumeDocument";
import { getRenderer } from "../resume/templates";
import type { ResumeData, ResumeStyle, TemplateDefinition } from "../resume/types";

const DPI = 96;
const CONTENT_HEIGHT_PX = CONTENT_HEIGHT_IN * DPI;
const MAX_PAGES = 20; // guard against a runaway measurement

interface ResumePreviewProps {
  data: ResumeData;
  style: ResumeStyle;
  template: TemplateDefinition | null;
  /** 1 = actual size. */
  scale?: number;
  isSample?: boolean;
  /** Layout document for user templates. Overrides template.layout, so the
   *  builder can preview unsaved edits. Built-in renderers ignore it. */
  layout?: unknown;
}

export function ResumePreview({
  data,
  style,
  template,
  scale = 0.8,
  isSample,
  layout,
}: ResumePreviewProps) {
  const activeLayout = layout ?? template?.layout ?? undefined;
  const Renderer = getRenderer(template?.rendererKey);
  const measureRef = useRef<HTMLDivElement>(null);
  const [pageCount, setPageCount] = useState(1);

  // Re-measure whenever anything that affects layout changes. A ResizeObserver
  // also catches late reflows such as webfonts finishing loading.
  useLayoutEffect(() => {
    const node = measureRef.current;
    if (!node) return;

    const recount = () => {
      const height = node.getBoundingClientRect().height;
      const pages = Math.max(1, Math.min(MAX_PAGES, Math.ceil(height / CONTENT_HEIGHT_PX)));
      setPageCount((prev) => (prev === pages ? prev : pages));
    };

    recount();
    const observer = new ResizeObserver(recount);
    observer.observe(node);
    return () => observer.disconnect();
  }, [data, style, template]);

  const pages = Array.from({ length: pageCount }, (_, index) => index);

  return (
    <div className="resume-preview">
      {isSample && (
        <div className="sample-badge" role="status">
          Sample data
        </div>
      )}

      {/* Off-screen measurement copy at exact content width. */}
      <div className="resume-measure" aria-hidden="true">
        <div ref={measureRef} style={{ width: `${CONTENT_WIDTH_IN}in` }}>
          <Renderer data={data} style={style} layout={activeLayout} />
        </div>
      </div>

      <div className="resume-pages">
        {pages.map((pageIndex) => (
          <div
            key={pageIndex}
            className="resume-page-shell"
            style={{
              width: `${PAGE.widthIn * scale}in`,
              height: `${PAGE.heightIn * scale}in`,
            }}
          >
            <div
              className="resume-page"
              style={{
                width: `${PAGE.widthIn}in`,
                height: `${PAGE.heightIn}in`,
                paddingTop: `${PAGE.marginTopIn}in`,
                paddingBottom: `${PAGE.marginBottomIn}in`,
                paddingLeft: `${PAGE.marginLeftIn}in`,
                paddingRight: `${PAGE.marginRightIn}in`,
                transform: `scale(${scale})`,
                transformOrigin: "top left",
              }}
            >
              <div
                className="resume-page-window"
                style={{ width: `${CONTENT_WIDTH_IN}in`, height: `${CONTENT_HEIGHT_IN}in` }}
              >
                <div style={{ transform: `translateY(-${pageIndex * CONTENT_HEIGHT_IN}in)` }}>
                  <Renderer data={data} style={style} layout={activeLayout} />
                </div>
              </div>
            </div>
            {pageCount > 1 && (
              <span className="page-number">
                {pageIndex + 1} / {pageCount}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
