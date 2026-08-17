/** Renderer registry: rendererKey -> React component (TM-FR-005).
 *
 *  Every renderer implements the same contract (TM-FR-003):
 *      ({ data, style }: TemplateRendererProps) => JSX
 *
 *  Templates differ by *chrome* — header treatment, heading style, skill
 *  layout — while resume semantics (ordering, empty-section removal, bullets,
 *  page breaks) stay in ResumeDocument so all ten behave consistently.
 *
 *  Visual identity that belongs to the template lives here; anything the user
 *  can edit lives in the style object instead.
 */

import type { ReactElement } from "react";
import { ResumeDocument, type TemplateChrome } from "../ResumeDocument";
import type { TemplateRendererProps } from "../types";

function makeRenderer(chrome: TemplateChrome) {
  return function TemplateRenderer({ data, style }: TemplateRendererProps) {
    return <ResumeDocument data={data} style={style} chrome={chrome} />;
  };
}

export const Template1 = makeRenderer({ headingStyle: "underline", headingTransform: "uppercase" });
export const Template2 = makeRenderer({ headingStyle: "plain", headingTransform: "uppercase" });
export const Template3 = makeRenderer({
  headingStyle: "rule",
  headingTransform: "uppercase",
  headingLetterSpacing: "0.08em",
});
export const Template4 = makeRenderer({ headingStyle: "underline", headingTransform: "none" });
export const Template5 = makeRenderer({ headingStyle: "plain", headingTransform: "none" });
export const Template6 = makeRenderer({ headingStyle: "rule", skillLayout: "inline" });
export const Template7 = makeRenderer({ headingStyle: "underline", headingTransform: "none" });
export const Template8 = makeRenderer({
  headingStyle: "plain",
  headingTransform: "uppercase",
  headingLetterSpacing: "0.12em",
});
export const Template9 = makeRenderer({ headingStyle: "rule", headerAccentBar: true });
export const Template10 = makeRenderer({ headingStyle: "boxed", headingTransform: "uppercase" });

export const RENDERERS: Record<string, (props: TemplateRendererProps) => ReactElement> = {
  "renderer-1": Template1,
  "renderer-2": Template2,
  "renderer-3": Template3,
  "renderer-4": Template4,
  "renderer-5": Template5,
  "renderer-6": Template6,
  "renderer-7": Template7,
  "renderer-8": Template8,
  "renderer-9": Template9,
  "renderer-10": Template10,
};

export const DEFAULT_RENDERER_KEY = "renderer-1";

/** Resolve a renderer, falling back to template-1's for ordinary previews. */
export function getRenderer(rendererKey: string | undefined) {
  return (rendererKey && RENDERERS[rendererKey]) || RENDERERS[DEFAULT_RENDERER_KEY];
}
