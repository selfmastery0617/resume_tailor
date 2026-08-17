import { useEffect, useState } from "react";

// DeepSeek replies typically land around here; used only to reassure the user
// that a long wait is expected rather than a hang.
const TYPICAL_SECONDS = 40;

interface ExtractingIndicatorProps {
  startedAt: number;
}

/** Ticking "Extracting… 12s" badge.
 *
 *  A DeepSeek round-trip runs ~40s, so a static label reads as frozen. This
 *  owns its own interval, so it re-renders itself without refreshing the grid.
 */
export function ExtractingIndicator({ startedAt }: ExtractingIndicatorProps) {
  const [elapsed, setElapsed] = useState(() => Math.floor((Date.now() - startedAt) / 1000));

  useEffect(() => {
    setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [startedAt]);

  const overdue = elapsed > TYPICAL_SECONDS * 2;

  return (
    <span
      className="skills-cell-loading"
      title={
        overdue
          ? "Taking longer than usual — it will time out on its own if DeepSeek never answers."
          : `Asking DeepSeek — this usually takes about ${TYPICAL_SECONDS}s.`
      }
    >
      <span className="spinner" aria-hidden="true" />
      <span>Extracting… {elapsed}s</span>
    </span>
  );
}
