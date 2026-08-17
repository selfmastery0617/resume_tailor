/** Scaled US-Letter preview.
 *
 *  9.5: the preview may scale visually, but its internal page dimensions must
 *  stay US Letter — so the document renders at true 8.5in and is scaled with a
 *  CSS transform rather than by shrinking its layout. That keeps preview and
 *  PDF in parity (RG-FR-015).
 */

import { PAGE } from "../resume/ResumeDocument";
import { getRenderer } from "../resume/templates";
import type { ResumeData, ResumeStyle, TemplateDefinition } from "../resume/types";

interface ResumePreviewProps {
  data: ResumeData;
  style: ResumeStyle;
  template: TemplateDefinition | null;
  /** 1 = actual size. */
  scale?: number;
  isSample?: boolean;
}

export function ResumePreview({ data, style, template, scale = 0.8, isSample }: ResumePreviewProps) {
  const Renderer = getRenderer(template?.rendererKey);

  return (
    <div className="resume-preview">
      {isSample && (
        <div className="sample-badge" role="status">
          Sample data
        </div>
      )}
      <div
        className="resume-preview-viewport"
        style={{
          width: `${PAGE.widthIn * scale}in`,
          // Reserve the scaled height so surrounding layout doesn't collapse.
          height: `${PAGE.heightIn * scale}in`,
        }}
      >
        <div
          style={{
            transform: `scale(${scale})`,
            transformOrigin: "top left",
            width: `${PAGE.widthIn}in`,
          }}
        >
          <Renderer data={data} style={style} />
        </div>
      </div>
    </div>
  );
}
