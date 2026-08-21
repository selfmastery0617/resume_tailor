/** Paginated preview using the active template's paper and margin settings.
 *
 *  Shows *every* page, not just the first, and uses exactly the PDF's page
 *  geometry so preview and output stay in parity (RG-FR-015). Legacy and
 *  built-in templates fall back to Letter; structured templates carry their
 *  selected paper size and four margins.
 *
 *  The document itself renders content only; page geometry lives here, and in
 *  the PDF it comes from Playwright's margin box. Both therefore wrap the same
 *  content at the same width.
 *
 *  Pagination works by measuring the flowed content once and showing each
 *  page-height slice through its own window. The transform scales only the
 *  presentation; measurement always uses the true selected paper dimensions.
 *
 *  Natural page boundaries slice the normal document flow after the last
 *  complete text line that fits. A section or entry can therefore use the
 *  space left on one page and continue on the next. Explicit page breaks and
 *  explicitly authored keep-together regions are the only whole-unit cases.
 */

import { useLayoutEffect, useRef, useState } from "react";
import { pageGeometry } from "../resume/pageGeometry";
import { getRenderer } from "../resume/templates";
import type { ResumeData, ResumeStyle, TemplateDefinition } from "../resume/types";

const DPI = 96;
const MAX_PAGES = 20; // guard against a runaway measurement
const EPSILON_PX = 0.5; // sub-pixel layout noise

interface LineRect {
  top: number;
  bottom: number;
}

/** Visible text rectangles in the continuous flow. Natural page slicing may
 *  divide a section or entry, but it must never cut through a line of text. */
function measureLineRects(container: HTMLElement, containerTop: number): LineRect[] {
  const lines: LineRect[] = [];
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  const range = document.createRange();

  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!node.textContent?.trim()) continue;
    range.selectNodeContents(node);
    const computedLineHeight = node.parentElement
      ? Number.parseFloat(window.getComputedStyle(node.parentElement).lineHeight)
      : Number.NaN;
    for (const rect of range.getClientRects()) {
      if (rect.height <= EPSILON_PX) continue;
      const leading = Number.isFinite(computedLineHeight)
        ? Math.max(0, (computedLineHeight - rect.height) / 2)
        : 0;
      lines.push({
        top: rect.top - containerTop - leading,
        bottom: rect.bottom - containerTop + leading,
      });
    }
  }

  return lines;
}

/** Page-start offsets (px, relative to the top of the flowed content),
 *  preserving natural flow while honouring explicit pagination directives. */
function computePageOffsets(container: HTMLElement, pageHeightPx: number): number[] {
  const totalHeightPx = container.getBoundingClientRect().height;
  const containerTop = container.getBoundingClientRect().top;
  const lineRects = measureLineRects(container, containerTop);

  const keepTogetherRects = Array.from(
    container.querySelectorAll('[data-keep-together="true"]'),
  ).map((element) => {
    const rect = element.getBoundingClientRect();
    return { top: rect.top - containerTop, bottom: rect.bottom - containerTop };
  });

  const forceTops = Array.from(container.querySelectorAll('[data-break-before="page"]')).map(
    (el) => el.getBoundingClientRect().top - containerTop,
  );

  const offsets = [0];
  let pageStart = 0;

  while (pageStart < totalHeightPx - EPSILON_PX && offsets.length < MAX_PAGES) {
    let nextBreak = pageStart + pageHeightPx;
    let isForced = false;

    // A forced break inside the current page wins over the natural boundary.
    for (const top of forceTops) {
      if (top > pageStart + EPSILON_PX && top < nextBreak) {
        nextBreak = top;
        isForced = true;
      }
    }

    // Layout authors may explicitly preserve a compact region. This is an
    // opt-in exception; ordinary sections, entries, and columns all split.
    let keptTogether = false;
    if (!isForced) {
      let containingRegionTop = Number.POSITIVE_INFINITY;
      for (const rect of keepTogetherRects) {
        const regionHeight = rect.bottom - rect.top;
        if (
          nextBreak > rect.top + EPSILON_PX &&
          nextBreak < rect.bottom - EPSILON_PX &&
          rect.top > pageStart + EPSILON_PX &&
          regionHeight <= pageHeightPx
        ) {
          containingRegionTop = Math.min(containingRegionTop, rect.top);
        }
      }
      if (Number.isFinite(containingRegionTop)) {
        nextBreak = containingRegionTop;
        keptTogether = true;
      }
    }

    // Chromium print fragments at line boundaries. If the natural pixel edge
    // crosses visible text, move only that line (not its whole block) forward.
    if (!isForced && !keptTogether) {
      let containingLineTop = Number.POSITIVE_INFINITY;
      for (const line of lineRects) {
        if (
          nextBreak > line.top + EPSILON_PX &&
          nextBreak < line.bottom - EPSILON_PX &&
          line.top > pageStart + EPSILON_PX
        ) {
          containingLineTop = Math.min(containingLineTop, line.top);
        }
      }
      if (Number.isFinite(containingLineTop)) nextBreak = containingLineTop;
    }

    if (nextBreak <= pageStart + EPSILON_PX || nextBreak >= totalHeightPx - EPSILON_PX) break;

    offsets.push(nextBreak);
    pageStart = nextBreak;
  }

  return offsets;
}

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
  const geometry = pageGeometry(activeLayout);
  const Renderer = getRenderer(template?.rendererKey);
  const measureRef = useRef<HTMLDivElement>(null);
  const [pageOffsets, setPageOffsets] = useState<number[]>([0]);

  // Re-measure whenever anything that affects layout changes. A ResizeObserver
  // also catches late reflows such as webfonts finishing loading.
  useLayoutEffect(() => {
    const node = measureRef.current;
    if (!node) return;

    const recount = () => {
      const offsets = computePageOffsets(node, geometry.contentHeightIn * DPI);
      setPageOffsets((prev) =>
        prev.length === offsets.length &&
        prev.every((value, index) => Math.abs(value - offsets[index]) <= EPSILON_PX)
          ? prev
          : offsets,
      );
    };

    recount();
    const observer = new ResizeObserver(recount);
    observer.observe(node);
    let cancelled = false;
    void document.fonts?.ready.then(() => {
      if (!cancelled) recount();
    });
    return () => {
      cancelled = true;
      observer.disconnect();
    };
  }, [data, style, template, activeLayout, geometry.contentHeightIn]);

  const pages = pageOffsets.map((_, index) => index);
  const pageCount = pages.length;

  return (
    <div className="resume-preview">
      {isSample && (
        <div className="sample-badge" role="status">
          Sample data
        </div>
      )}

      {/* Off-screen measurement copy at exact content width. */}
      <div className="resume-measure" aria-hidden="true">
        <div ref={measureRef} style={{ width: `${geometry.contentWidthIn}in` }}>
          <Renderer data={data} style={style} layout={activeLayout} />
        </div>
      </div>

      <div className="resume-pages">
        {pages.map((pageIndex) => {
          // Natural slices use the full page up to the last complete line. An
          // explicit forced/keep-together break can make one end earlier.
          const sliceHeightPx =
            pageIndex < pageOffsets.length - 1
              ? pageOffsets[pageIndex + 1] - pageOffsets[pageIndex]
              : undefined;

          return (
            <div
              key={pageIndex}
              className="resume-page-shell"
              style={{
                width: `${geometry.widthIn * scale}in`,
                height: `${geometry.heightIn * scale}in`,
              }}
            >
              <div
                className="resume-page"
                style={{
                  width: `${geometry.widthIn}in`,
                  height: `${geometry.heightIn}in`,
                  paddingTop: `${geometry.marginTopIn}in`,
                  paddingBottom: `${geometry.marginBottomIn}in`,
                  paddingLeft: `${geometry.marginLeftIn}in`,
                  paddingRight: `${geometry.marginRightIn}in`,
                  transform: `scale(${scale})`,
                  transformOrigin: "top left",
                }}
              >
                <div
                  className="resume-page-window"
                  style={{
                    width: `${geometry.contentWidthIn}in`,
                    height: `${geometry.contentHeightIn}in`,
                  }}
                >
                  <div
                    style={{
                      height: sliceHeightPx !== undefined ? `${sliceHeightPx}px` : undefined,
                      overflow: sliceHeightPx !== undefined ? "hidden" : undefined,
                    }}
                  >
                    <div style={{ transform: `translateY(-${pageOffsets[pageIndex]}px)` }}>
                      <Renderer data={data} style={style} layout={activeLayout} />
                    </div>
                  </div>
                </div>
              </div>
              {pageCount > 1 && (
                <span className="page-number">
                  {pageIndex + 1} / {pageCount}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
