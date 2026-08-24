import { useEffect, useState } from "react";
import { fetchSampleResume } from "../api/templates";
import type { ResumeData } from "../resume/types";

/** The sample resume both Templates and Builder pages preview with (never a
 *  real profile's -- see the note on previewData in TemplatesPage.tsx).
 *  Fetched once per page, like every other page-level resource here; the
 *  setter lets SampleResumeEditor push a save/reset straight into the
 *  already-open preview without a second round trip. */
export function useSampleResume(active: boolean) {
  const [sampleResume, setSampleResume] = useState<ResumeData | null>(null);

  useEffect(() => {
    if (!active) return;
    (async () => {
      try {
        setSampleResume(await fetchSampleResume());
      } catch {
        /* the preview just stays empty until the next successful fetch */
      }
    })();
  }, [active]);

  return { sampleResume, setSampleResume };
}
