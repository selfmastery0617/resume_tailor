/** The jobs table.
 *
 *  A spreadsheet, not a list: cells are edited in place, ranges are selected by
 *  dragging, and Excel copy/paste moves whole blocks in and out. AG Grid
 *  Community has none of that built in — range selection and clipboard are
 *  Enterprise — so both are implemented here against the Community grid.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import {
  ModuleRegistry,
  AllCommunityModule,
  colorSchemeDark,
  themeQuartz,
} from "ag-grid-community";
import type {
  CellValueChangedEvent,
  ColDef,
  GridApi,
  ValueGetterParams,
} from "ag-grid-community";
import {
  cancelJobDescriptionExtraction,
  cancelImport,
  createJob,
  deleteJobRows,
  fetchJobDescriptionExtractionStatus,
  fetchImportStatus,
  fetchJobs,
  startJobDescriptionExtraction,
  startImport,
  updateJob,
  type ImportStatus,
  type JobDescriptionExtractionStatus,
} from "../api/jobs";
import {
  fetchAllTailoredResumes,
  generateTailoredResume,
  openTailoredResumeFolder,
  type TailoredResume,
} from "../api/resumes";
import { extractExperience, fetchAllExperience, type ExperienceResult } from "../api/experience";
import { fetchSettledChatGptSession } from "../api/chatgpt";
import { fetchSettledSessionStatus } from "../api/deepseek";
import type { Job } from "../types/job";
import { UrlCellRenderer } from "../components/UrlCellRenderer";
import { ResumeCellRenderer, type ResumeGridContext } from "../components/ResumeCellRenderer";
import { DescriptionPopupEditor } from "../components/jobs/DescriptionPopupEditor";
import { ImportJobsDialog } from "../components/jobs/ImportJobsDialog";
import { RowDeleteCell, type RowDeleteContext } from "../components/jobs/RowDeleteCell";
import { StatusCellRenderer, type StatusContext } from "../components/jobs/StatusCell";
import { useCellRange } from "../components/jobs/useCellRange";
import { useResolvedTheme } from "../components/ThemeToggle";

ModuleRegistry.registerModules([AllCommunityModule]);

/* AG Grid renders in a shadow DOM and cannot read our CSS variables, so its
   palette is built explicitly and swapped with the app theme — otherwise the
   table stays bright white inside a dark-grey page. */
const gridThemeLight = themeQuartz.withParams({
  backgroundColor: "#ffffff",
  foregroundColor: "#16191d",
  borderColor: "#dfe3e8",
  headerBackgroundColor: "#f1f3f5",
  headerTextColor: "#16191d",
  rowHoverColor: "rgba(59, 125, 221, 0.07)",
  // Warm, not blue: a ticked row is picked for an action, and must not be
  // mistaken for the blue cell-range highlight sitting on top of it.
  selectedRowBackgroundColor: "rgba(229, 72, 77, 0.1)",
  accentColor: "#3b7ddd",
  fontFamily: "inherit",
  fontSize: "13px",
  wrapperBorderRadius: "8px",
});

const gridThemeDark = themeQuartz.withPart(colorSchemeDark).withParams({
  backgroundColor: "#1e2125",
  foregroundColor: "#e8ebee",
  borderColor: "#2f343a",
  headerBackgroundColor: "#1a1d20",
  headerTextColor: "#e8ebee",
  rowHoverColor: "rgba(91, 147, 240, 0.1)",
  selectedRowBackgroundColor: "rgba(242, 114, 106, 0.14)",
  accentColor: "#5b93f0",
  fontFamily: "inherit",
  fontSize: "13px",
  wrapperBorderRadius: "8px",
});

/** Column order is fixed by the spec; the ids double as the selection order. */
const COLUMN_IDS = [
  "date_added",
  "posted",
  "company",
  "title",
  "url",
  "job_url",
  "description",
  "resume",
  "status",
];

/** Cells a person may type into. The rest come from the import or the pipeline. */
const EDITABLE = new Set([
  "date_added",
  "title",
  "company",
  "url",
  "job_url",
  "status",
  "description",
]);

/** Cleared by Delete. Status is excluded: it can never go back to empty. */
const CLEARABLE = ["date_added", "title", "company", "url", "job_url", "description"];

/** Splits a pasted TSV block into rows of cells, understanding Excel's own
 *  quoting: a field that itself contains a tab, a newline, or a quote comes
 *  wrapped in "double quotes" (doubled `""` for a literal quote inside), so
 *  a multi-line description sitting alongside company/title/url in one
 *  paste is still one field -- its embedded newlines must not be read as
 *  row breaks the way an unquoted `\n` is. A naive `split("\n")` /
 *  `split("\t")` cannot tell the difference; this walks the text char by
 *  char, tracking quote state, instead.
 */
function parseTsvMatrix(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;
  let i = 0;
  while (i < text.length) {
    const char = text[i];
    if (inQuotes) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 2;
        } else {
          inQuotes = false;
          i += 1;
        }
      } else {
        field += char;
        i += 1;
      }
      continue;
    }
    if (char === '"' && field === "") {
      inQuotes = true;
      i += 1;
    } else if (char === "\t") {
      row.push(field);
      field = "";
      i += 1;
    } else if (char === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
      i += 1;
    } else {
      field += char;
      i += 1;
    }
  }
  row.push(field);
  rows.push(row);
  return rows;
}

/** The write side of parseTsvMatrix's quoting: wraps a field in double
 *  quotes (doubling any quote inside it) when it contains a tab, a newline,
 *  or a quote of its own -- otherwise a multi-line description copied
 *  alongside other columns would come back out as several unquoted lines,
 *  ambiguous with real row breaks the next time it's parsed (by this page,
 *  Excel, or anything else reading TSV).
 */
function quoteTsvField(value: string): string {
  return /[\t\n"]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

interface JobsPageProps {
  /** Changes when a provider's session may have, so the connection banners
   *  re-check instead of standing on the answers from the initial mount. */
  sessionVersion: number;
  /** True while this tab is visible. Pages stay mounted to preserve unsaved
   *  edits, so they must refresh on activation or they show stale data --
   *  e.g. the jobs list after switching the active profile on the Profile
   *  tab (jobs are scoped to whichever profile is active). */
  active?: boolean;
}

export function JobsPage({ sessionVersion, active = true }: JobsPageProps) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [experienceResults, setExperienceResults] = useState<Record<string, ExperienceResult>>({});
  const [resumeResults, setResumeResults] = useState<Record<string, TailoredResume>>({});
  const [experienceExtracting, setExperienceExtracting] = useState<Map<string, number>>(new Map());
  const [resumeGenerating, setResumeGenerating] = useState<Map<string, number>>(new Map());
  const [importOpen, setImportOpen] = useState(false);
  const [importStatus, setImportStatus] = useState<ImportStatus | null>(null);
  const [jdExtractionStatus, setJdExtractionStatus] =
    useState<JobDescriptionExtractionStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pageSize, setPageSize] = useState(20);
  const [chatGptConnected, setChatGptConnected] = useState(true);
  const [deepSeekConnected, setDeepSeekConnected] = useState(true);
  const [deletingRows, setDeletingRows] = useState<Set<string>>(new Set());
  // Ticked checkboxes, kept here so the toolbar can act on them. AG Grid holds
  // the authoritative state; this mirrors it for rendering.
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  const gridApiRef = useRef<GridApi<Job> | null>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // The table shows exactly what is stored. There is no placeholder row: an
  // empty row that renders pipeline controls reads as broken data, and "Add
  // row" says what it does. Paste past the last row still creates rows.
  const rows = jobs;
  const jdExtractionRunning = jdExtractionStatus?.state === "running";
  const eligibleSelectedCount = useMemo(() => {
    const selected = new Set(selectedIds);
    return jobs.filter(
      (job) => selected.has(job.id) && !job.locked && Boolean(job.job_url?.trim()),
    ).length;
  }, [jobs, selectedIds]);

  const range = useCellRange(wrapperRef, {
    columnIds: COLUMN_IDS,
    // A drag that starts on a button is that button being pressed.
    // A drag starting on a control is that control being used, not a selection.
    isInteractive: (target) =>
      Boolean(target.closest("button, a, select, input, .row-delete-cell")),
  });

  const describeError = (err: unknown, fallback: string) =>
    (err as { response?: { data?: { detail?: { message?: string } } } }).response?.data?.detail
      ?.message ?? fallback;

  const reload = useCallback(async () => {
    try {
      setJobs(await fetchJobs());
    } catch {
      setError("Could not load jobs. Is the backend running?");
    }
  }, []);

  // Re-runs whenever this tab (re)activates, not just on mount: jobs are
  // scoped to the active profile, and switching that on the Profile tab
  // while Jobs stays mounted-but-hidden would otherwise leave this page
  // showing the previous profile's stale list.
  useEffect(() => {
    if (!active) return;
    void reload();
    void (async () => {
      try {
        setExperienceResults(await fetchAllExperience());
      } catch {
        /* badges are optional */
      }
      try {
        setResumeResults(await fetchAllTailoredResumes());
      } catch {
        /* same */
      }
      try {
        // An import outlives the page: reloading mid-run should pick the
        // progress back up rather than look as though nothing is happening.
        const status = await fetchImportStatus();
        if (status.state === "running") setImportStatus(status);
      } catch {
        /* the toolbar just shows "Import Jobs" */
      }
      try {
        // Description extraction also belongs to the backend process, so a
        // page reload reconnects to the active batch instead of orphaning it.
        const status = await fetchJobDescriptionExtractionStatus();
        if (status.state === "running") setJdExtractionStatus(status);
      } catch {
        /* Extract JD remains available; starting it will surface API errors. */
      }
    })();
  }, [active, reload]);

  // Separate from the mount effect so signing in from the dock clears the
  // banner without refetching every job and badge as well.
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const status = await fetchSettledChatGptSession();
        if (alive) setChatGptConnected(status.connected);
      } catch {
        if (alive) setChatGptConnected(false);
      }
      try {
        const status = await fetchSettledSessionStatus();
        if (alive) setDeepSeekConnected(status.connected);
      } catch {
        if (alive) setDeepSeekConnected(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [sessionVersion]);

  useEffect(() => {
    gridApiRef.current?.refreshCells({ force: true });
  }, [experienceExtracting, experienceResults, resumeGenerating, resumeResults]);

  // -- editing ---------------------------------------------------------------

  const applyEdit = useCallback(
    async (job: Job, field: string, value: string) => {
      setError(null);
      try {
        const updated = await updateJob(job.id, { [field]: value });
        setJobs((prev) => prev.map((j) => (j.id === job.id ? updated : j)));
        return updated;
      } catch (err) {
        setError(describeError(err, "Could not save that edit."));
        // Put the grid back to what the server actually holds.
        void reload();
        return null;
      }
    },
    [reload],
  );

  const onCellValueChanged = useCallback(
    (event: CellValueChangedEvent<Job>) => {
      const field = event.colDef.colId ?? event.colDef.field;
      if (!field || !EDITABLE.has(field)) return;
      if (event.oldValue === event.newValue) return;
      void applyEdit(event.data, field, String(event.newValue ?? ""));
    },
    [applyEdit],
  );

  // -- clipboard -------------------------------------------------------------

  const cellText = useCallback((job: Job, colId: string): string => {
    switch (colId) {
      case "description":
        return job.description ?? "";
      case "resume":
        return resumeResults[job.id]?.fileName ?? "";
      default:
        return String((job as unknown as Record<string, unknown>)[colId] ?? "");
    }
  }, [resumeResults]);

  const copySelection = useCallback(async () => {
    if (!range.range) return;
    // A lone cell round-trips as raw text (matching the singleCell shortcut
    // in pasteIntoSelection, and Excel's own behavior of only quoting once
    // there's more than one field to disambiguate); anything wider needs
    // quoting so an embedded newline or tab in one field can't be mistaken
    // for a row or column break when it's parsed again.
    const isSingleCell = range.range.top === range.range.bottom && range.range.columns.length === 1;
    const lines: string[] = [];
    for (let r = range.range.top; r <= range.range.bottom; r += 1) {
      const job = rows[r];
      if (!job) continue;
      lines.push(
        range.range.columns
          .map((colId) => {
            const value = cellText(job, colId);
            return isSingleCell ? value : quoteTsvField(value);
          })
          .join("\t"),
      );
    }
    const text = lines.join("\n");
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard needs a secure context; fall back so copy still works on http.
      const area = document.createElement("textarea");
      area.value = text;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    setNotice(`Copied ${lines.length} row${lines.length === 1 ? "" : "s"}.`);
  }, [range.range, rows, cellText]);

  const pasteIntoSelection = useCallback(
    async (text: string) => {
      const anchor = range.anchor;
      if (!anchor) return;
      const normalized = text.replace(/\r\n?/g, "\n").replace(/\n$/, "");

      // A single selected description cell is virtually always a paragraph
      // of prose, not a copied spreadsheet block -- its line breaks belong
      // in the text, not read as row delimiters the way the matrix paste
      // below treats them (each \n starting a new job row). The absence of
      // any tab still lets a genuine multi-column block anchored here fall
      // through to that behavior instead.
      const singleCell =
        !!range.range &&
        range.range.top === range.range.bottom &&
        range.range.columns.length === 1 &&
        range.range.columns[0] === anchor.colId;
      if (singleCell && anchor.colId === "description" && !normalized.includes("\t")) {
        const job = rows[anchor.rowIndex];
        if (!job) return;
        setError(null);
        await applyEdit(job, "description", normalized);
        setNotice("Pasted.");
        return;
      }

      const matrix = parseTsvMatrix(normalized);
      if (!matrix.length) return;

      const startCol = COLUMN_IDS.indexOf(anchor.colId);
      const targets = COLUMN_IDS.slice(startCol).filter((c) => EDITABLE.has(c));
      if (!targets.length) {
        setError("Paste landed on read-only columns.");
        return;
      }

      setNotice(`Pasting ${matrix.length} row${matrix.length === 1 ? "" : "s"}…`);
      setError(null);
      let created = 0;
      let updated = 0;

      // Sequential on purpose: each row may create a job, and the server has to
      // settle one before the next decides whether it is creating or updating.
      for (let i = 0; i < matrix.length; i += 1) {
        const rowIndex = anchor.rowIndex + i;
        const patch: Record<string, string> = {};
        COLUMN_IDS.slice(startCol).forEach((colId, offset) => {
          const cell = matrix[i][offset];
          if (cell !== undefined && EDITABLE.has(colId) && colId !== "status") {
            patch[colId] = cell.trim();
          }
        });
        if (!Object.keys(patch).length) continue;

        const existing = rows[rowIndex];
        try {
          if (!existing) {
            await createJob(patch);
            created += 1;
          } else {
            await updateJob(existing.id, patch);
            updated += 1;
          }
        } catch (err) {
          setError(describeError(err, `Row ${i + 1} of the paste failed.`));
          break;
        }
      }

      await reload();
      setNotice(
        `Pasted ${matrix.length} row${matrix.length === 1 ? "" : "s"} — ` +
          `${created} created, ${updated} updated.`,
      );
    },
    [range.anchor, range.range, rows, reload, applyEdit],
  );

  const clearSelection = useCallback(async () => {
    if (!range.range) return;
    const clearable = range.range.columns.filter((c) => CLEARABLE.includes(c));
    if (!clearable.length) {
      setError("Nothing in that selection can be cleared.");
      return;
    }
    setError(null);
    let touched = 0;
    for (let r = range.range.top; r <= range.range.bottom; r += 1) {
      const job = rows[r];
      if (!job) continue;
      const patch = Object.fromEntries(clearable.map((c) => [c, ""]));
      try {
        await updateJob(job.id, patch);
        touched += 1;
      } catch (err) {
        setError(describeError(err, "Could not clear those cells."));
        break;
      }
    }
    await reload();
    setNotice(`Cleared ${clearable.length * touched} cell${clearable.length * touched === 1 ? "" : "s"}.`);
  }, [range.range, rows, reload]);

  /** The one place rows are removed, shared by the toolbar, the row button
   *  and Ctrl+Delete. Forgets everything derived from them too, so the badges
   *  do not outlive the rows they belong to. */
  const removeRows = useCallback(
    async (ids: string[], prompt: string, describe?: (count: number) => string) => {
      if (!ids.length || !window.confirm(prompt)) return;
      setDeletingRows((prev) => new Set([...prev, ...ids]));
      setError(null);
      try {
        const result = await deleteJobRows(ids);
        const gone = new Set(ids);
        const forget = <T,>(prev: Record<string, T>) =>
          Object.fromEntries(Object.entries(prev).filter(([id]) => !gone.has(id)));
        setExperienceResults(forget);
        setResumeResults(forget);
        gridApiRef.current?.deselectAll();
        range.clear();
        await reload();
        setNotice(
          describe?.(result.count) ??
            `Deleted ${result.count} row${result.count === 1 ? "" : "s"}.`,
        );
      } catch (err) {
        setError(describeError(err, "Could not delete those rows."));
      } finally {
        setDeletingRows((prev) => {
          const next = new Set(prev);
          ids.forEach((id) => next.delete(id));
          return next;
        });
      }
    },
    [range, reload],
  );

  const deleteCheckedRows = useCallback(() => {
    const count = selectedIds.length;
    return removeRows(
      selectedIds,
      `Delete ${count} selected row${count === 1 ? "" : "s"}?\n\n` +
        "This also removes their extracted experience and resume records. Any " +
        "PDFs already saved to your output folder stay on disk.",
    );
  }, [selectedIds, removeRows]);

  /** Ctrl+Delete. Ticked boxes win over the cell range: checking them is a
   *  deliberate choice, whereas a range is often left over from a copy. */
  const deleteRowsFromKeyboard = useCallback(() => {
    if (selectedIds.length) return deleteCheckedRows();
    if (!range.range) return;
    const ids: string[] = [];
    for (let r = range.range.top; r <= range.range.bottom; r += 1) {
      const job = rows[r];
      if (job) ids.push(job.id);
    }
    return removeRows(
      ids,
      `Delete ${ids.length} row${ids.length === 1 ? "" : "s"}? This cannot be undone.`,
    );
  }, [selectedIds, deleteCheckedRows, range.range, rows, removeRows]);

  const deleteRow = useCallback(
    (job: Job) => {
      const label = job.title || job.company || "this row";
      return removeRows(
        [job.id],
        `Delete "${label}"?\n\n` +
          "This also removes its extracted experience and resume record. Any " +
          "PDF already saved to your output folder stays on disk.",
        () => `Deleted "${label}".`,
      );
    },
    [removeRows],
  );

  // Keyboard lives on the wrapper so it only fires while the table has focus.
  const onKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      const editing = Boolean(gridApiRef.current?.getEditingCells()?.length);
      if (editing) return;

      const meta = event.ctrlKey || event.metaKey;
      if (meta && event.key.toLowerCase() === "c") {
        event.preventDefault();
        void copySelection();
      } else if (meta && event.key.toLowerCase() === "v") {
        event.preventDefault();
        void navigator.clipboard
          .readText()
          .then((text) => pasteIntoSelection(text))
          .catch(() => setError("Could not read the clipboard. Paste needs permission."));
      } else if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        // Ctrl+Delete removes rows; Delete alone only empties their cells.
        if (meta) void deleteRowsFromKeyboard();
        else void clearSelection();
      } else if (event.key === "Escape") {
        range.clear();
      }
    },
    [copySelection, pasteIntoSelection, clearSelection, deleteRowsFromKeyboard, range],
  );

  // -- pipeline --------------------------------------------------------------

  // Returns whether the job ended up with a saved PDF, so a bulk run can tell
  // which of several jobs failed without throwing through an unawaited
  // button click (the single-row caller ignores the return value; a `void`
  // callback type accepts a function that happens to return one).
  const handleGenerateResume = useCallback(
    async (job: Job): Promise<boolean> => {
      setError(null);
      if (!experienceResults[job.id]) {
        setExperienceExtracting((prev) => new Map(prev).set(job.id, Date.now()));
        try {
          const result = await extractExperience({
            jobId: job.id,
            jobDescription: job.description ?? "",
            jobTitle: job.title,
          });
          setExperienceResults((prev) => ({ ...prev, [job.id]: result }));
        } catch (err) {
          setError(describeError(err, "Could not extract experience."));
          return false;
        } finally {
          setExperienceExtracting((prev) => {
            const next = new Map(prev);
            next.delete(job.id);
            return next;
          });
        }
      }

      setResumeGenerating((prev) => new Map(prev).set(job.id, Date.now()));
      try {
        const saved = await generateTailoredResume({
          jobId: job.id,
          company: job.company,
          jobTitle: job.title,
        });
        setResumeResults((prev) => ({ ...prev, [job.id]: saved }));
        // Generating one flips the row to Ready server-side.
        await reload();
        return true;
      } catch (err) {
        setError(describeError(err, "Could not generate the resume."));
        return false;
      } finally {
        setResumeGenerating((prev) => {
          const next = new Map(prev);
          next.delete(job.id);
          return next;
        });
      }
    },
    [experienceResults, reload],
  );

  const handleOpenFolder = useCallback(async (job: Job) => {
    setError(null);
    try {
      await openTailoredResumeFolder(job.id);
    } catch (err) {
      setError(describeError(err, "Could not open the folder."));
    }
  }, []);

  const [bulkGenerating, setBulkGenerating] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<{ done: number; total: number } | null>(null);
  const resumePipelineRunning =
    bulkGenerating || experienceExtracting.size > 0 || resumeGenerating.size > 0;

  // Jobs cannot extract/generate concurrently — the DeepSeek/ChatGPT browser
  // session is one shared profile with a single lock, so a second job's
  // request would just queue silently behind the first anyway. Running them
  // one at a time here, instead of firing them all at once, keeps the UI's
  // per-row "Extracting…"/"Generating…" state honest about what is actually
  // in flight right now.
  const generateSelectedResumes = useCallback(async () => {
    const ids = new Set(selectedIds);
    const targets = jobs.filter((job) => ids.has(job.id));
    if (!targets.length || bulkGenerating) return;

    setBulkGenerating(true);
    setError(null);
    setNotice(null);
    setBulkProgress({ done: 0, total: targets.length });

    const failed: string[] = [];
    for (const job of targets) {
      const ok = await handleGenerateResume(job);
      if (!ok) failed.push(job.title || job.company || job.id);
      setBulkProgress((prev) => (prev ? { ...prev, done: prev.done + 1 } : prev));
    }

    setBulkGenerating(false);
    setBulkProgress(null);
    const succeeded = targets.length - failed.length;
    if (failed.length) {
      setError(
        `Generated ${succeeded}/${targets.length} resume${targets.length === 1 ? "" : "s"}. ` +
          `Failed: ${failed.join(", ")}`,
      );
    } else {
      setNotice(`Generated ${succeeded} resume${succeeded === 1 ? "" : "s"}.`);
    }
  }, [selectedIds, jobs, bulkGenerating, handleGenerateResume]);

  const addRow = useCallback(async () => {
    setError(null);
    try {
      const created = await createJob({});
      setJobs((prev) => [...prev, created]);
      setNotice("Row added — it is dated today until you change it.");
    } catch (err) {
      setError(describeError(err, "Could not add a row."));
    }
  }, []);

  const changeStatus = useCallback(
    async (job: Job, status: string) => {
      if (!status) return;
      setError(null);
      try {
        const updated = await updateJob(job.id, { status });
        setJobs((prev) => prev.map((j) => (j.id === job.id ? updated : j)));
      } catch (err) {
        setError(describeError(err, "Could not change the status."));
        void reload();
      }
    },
    [reload],
  );

  // Poll while a run is in flight: refresh the status for the counter, and the
  // rows so the table fills as jobs are found rather than all at the end.
  useEffect(() => {
    if (importStatus?.state !== "running") return;
    let cancelled = false;
    const id = window.setInterval(async () => {
      try {
        const next = await fetchImportStatus();
        if (cancelled) return;
        setImportStatus(next);
        await reload();
        if (next.state !== "running") {
          setNotice(
            next.state === "cancelled"
              ? `Import cancelled — kept ${next.matched} job${next.matched === 1 ? "" : "s"}.`
              : next.state === "failed"
                ? null
                : `Imported ${next.matched} job${next.matched === 1 ? "" : "s"} from ${next.scanned} scanned.`,
          );
          if (next.state === "failed") setError(next.error);
        }
      } catch {
        /* a missed poll is harmless; the next one catches up */
      }
    }, 900);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [importStatus?.state, reload]);

  const handleStartImport = useCallback(
    async (options: { roles: string[]; limit: number; excludeCompanies: string[] }) => {
      setError(null);
      setNotice(null);
      try {
        setImportStatus(await startImport(options));
      } catch (err) {
        setError(describeError(err, "Could not start the import."));
      }
    },
    [],
  );

  const handleCancelImport = useCallback(async () => {
    try {
      setImportStatus(await cancelImport());
    } catch (err) {
      setError(describeError(err, "Could not cancel the import."));
    }
  }, []);

  // The backend owns this batch and its one DeepSeek conversation. Polling
  // makes completed descriptions appear one row at a time and also lets a
  // refreshed page reconnect to a run that is still active.
  useEffect(() => {
    if (jdExtractionStatus?.state !== "running") return;
    let cancelled = false;
    const id = window.setInterval(async () => {
      try {
        const next = await fetchJobDescriptionExtractionStatus();
        if (cancelled) return;
        setJdExtractionStatus(next);
        await reload();
        if (next.state === "running") return;

        if (next.state === "failed") {
          setError(next.error || "Job-description extraction failed.");
          return;
        }

        const summary = `${next.succeeded}/${next.total} job description${
          next.total === 1 ? "" : "s"
        } extracted`;
        setNotice(next.state === "cancelled" ? `Stopped — ${summary}.` : `${summary}.`);
        if (next.failed > 0) {
          const details = next.failures.slice(0, 3).join("; ");
          setError(
            `${next.failed} row${next.failed === 1 ? "" : "s"} failed` +
              (details ? `: ${details}` : "."),
          );
        }
      } catch {
        /* a missed poll is harmless; the next one catches up */
      }
    }, 900);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [jdExtractionStatus?.state, reload]);

  const handleStartJdExtraction = useCallback(async () => {
    if (resumePipelineRunning) {
      setError("Wait for the current resume extraction or generation to finish.");
      return;
    }
    if (!eligibleSelectedCount) {
      setError("Select at least one unlocked row with a non-empty Job URL.");
      return;
    }
    setError(null);
    setNotice(null);
    try {
      setJdExtractionStatus(await startJobDescriptionExtraction(selectedIds));
    } catch (err) {
      setError(describeError(err, "Could not start job-description extraction."));
    }
  }, [eligibleSelectedCount, resumePipelineRunning, selectedIds]);

  const handleCancelJdExtraction = useCallback(async () => {
    try {
      setJdExtractionStatus(await cancelJobDescriptionExtraction());
    } catch (err) {
      setError(describeError(err, "Could not stop job-description extraction."));
    }
  }, []);

  // -- columns ---------------------------------------------------------------

  const columnDefs = useMemo<ColDef<Job>[]>(() => {
    const selectable = (colId: string) => ({
      cellClass: (params: { data?: Job; node: { rowIndex: number | null } }) =>
        range.inRange(params.node.rowIndex, colId) ? "cell-selected" : "",
    });

    return [
      {
        colId: "no",
        headerName: "No",
        width: 56,
        editable: false,
        sortable: false,
        filter: false,
        resizable: false,
        // Row position, not stored data — excluded from COLUMN_IDS the same
        // way rowDelete is, so it takes no part in range selection or copy.
        valueGetter: (p: ValueGetterParams<Job>) =>
          p.node?.rowIndex != null ? p.node.rowIndex + 1 : "",
      },
      {
        colId: "date_added",
        field: "date_added",
        headerName: "Date",
        width: 118,
        editable: true,
        ...selectable("date_added"),
      },
      {
        colId: "posted",
        headerName: "Posted",
        width: 100,
        editable: false,
        // Read-only, unlike Date: this is Jobright's own posting time, not
        // the user's own tracking date, so it is never something to type into.
        valueGetter: (p: ValueGetterParams<Job>) => p.data?.publish_time ?? "",
        valueFormatter: (p) => (p.value ? new Date(p.value).toLocaleDateString() : ""),
        ...selectable("posted"),
      },
      {
        colId: "company",
        field: "company",
        headerName: "Company",
        flex: 1,
        minWidth: 130,
        editable: true,
        ...selectable("company"),
      },
      {
        colId: "title",
        field: "title",
        headerName: "Title",
        flex: 2,
        minWidth: 180,
        editable: true,
        ...selectable("title"),
      },
      {
        colId: "url",
        field: "url",
        headerName: "URL",
        flex: 1,
        minWidth: 150,
        editable: true,
        cellRenderer: UrlCellRenderer,
        ...selectable("url"),
      },
      {
        colId: "job_url",
        field: "job_url",
        headerName: "Job URL",
        flex: 1,
        minWidth: 170,
        editable: true,
        cellRenderer: UrlCellRenderer,
        ...selectable("job_url"),
      },
      {
        colId: "description",
        field: "description",
        headerName: "Description",
        flex: 1,
        minWidth: 160,
        editable: true,
        // Too long for the grid's default one-line editor -- any way of
        // starting an edit (double-click, typing over a selected cell, F2)
        // opens the tooltip-style popup instead (DescriptionPopupEditor).
        cellEditor: DescriptionPopupEditor,
        cellEditorPopup: true,
        cellEditorPopupPosition: "under",
        ...selectable("description"),
      },
      {
        colId: "resume",
        headerName: "Resume",
        width: 200,
        editable: false,
        sortable: false,
        cellRenderer: ResumeCellRenderer,
        ...selectable("resume"),
      },
      {
        colId: "status",
        field: "status",
        headerName: "Status",
        width: 130,
        sortable: false,
        // The renderer is the control, so the cell is never "edited" by AG Grid.
        editable: false,
        cellRenderer: StatusCellRenderer,
        ...selectable("status"),
      },
      {
        colId: "rowDelete",
        headerName: "",
        width: 56,
        editable: false,
        sortable: false,
        filter: false,
        resizable: false,
        // Deliberately outside COLUMN_IDS: an action button is not data, so it
        // takes no part in range selection, copy or clear.
        cellRenderer: RowDeleteCell,
        cellClass: "row-delete-cell",
      },
    ];
  }, [range]);

  const gridContext: ResumeGridContext & RowDeleteContext & StatusContext = {
    experienceExtracting,
    experienceResults,
    resumeGenerating,
    resumeResults,
    bulkRunning: resumePipelineRunning || jdExtractionRunning,
    onGenerateResume: handleGenerateResume,
    onOpenFolder: handleOpenFolder,
    deletingRows,
    onDeleteRow: deleteRow,
    onChangeStatus: changeStatus,
  };

  return (
    <div className="jobs-page">
      <div className="jobs-toolbar">
        <button className="import-button" onClick={() => setImportOpen(true)}>
          {importStatus?.state === "running" && <span className="spinner" aria-hidden="true" />}
          {importStatus?.state === "running"
            ? `Importing ${importStatus.matched}/${importStatus.limit}…`
            : "Import Jobs"}
        </button>
        <button type="button" onClick={() => void addRow()}>
          + Add row
        </button>
        {jdExtractionRunning ? (
          <button
            type="button"
            className="danger"
            onClick={() => void handleCancelJdExtraction()}
            disabled={jdExtractionStatus.cancelRequested}
          >
            <span className="spinner" aria-hidden="true" />
            Stop Extracting
            <span aria-label="job-description extraction progress">
              {` ${jdExtractionStatus.done}/${jdExtractionStatus.total}`}
            </span>
          </button>
        ) : (
          selectedIds.length > 0 && (
            <button
              type="button"
              onClick={() => void handleStartJdExtraction()}
              disabled={resumePipelineRunning || eligibleSelectedCount === 0}
              title={
                eligibleSelectedCount === 0
                  ? "Selected rows need a non-empty Job URL and must not be applied."
                  : `Extract descriptions for ${eligibleSelectedCount} eligible row${
                      eligibleSelectedCount === 1 ? "" : "s"
                    } in one DeepSeek session.`
              }
            >
              Extract JD
            </button>
          )
        )}
        {selectedIds.length > 0 && (
          <button
            type="button"
            onClick={() => void generateSelectedResumes()}
            disabled={bulkGenerating || jdExtractionRunning}
          >
            {bulkGenerating && <span className="spinner" aria-hidden="true" />}
            {bulkGenerating
              ? `Generating ${bulkProgress?.done ?? 0}/${bulkProgress?.total ?? selectedIds.length}…`
              : `Extract Resume for ${selectedIds.length} selected`}
          </button>
        )}
        {selectedIds.length > 0 && (
          <button
            type="button"
            className="danger"
            onClick={() => void deleteCheckedRows()}
            disabled={bulkGenerating || jdExtractionRunning}
          >
            Delete {selectedIds.length} selected
          </button>
        )}
        <span className="jobs-hint">
          Tick rows to extract or delete in bulk · Drag to select cells · Ctrl+C / Ctrl+V ·
          Delete clears cells · Ctrl+Delete removes rows
        </span>
        <label className="page-size">
          Rows
          <select
            value={pageSize}
            onChange={(event) => {
              const next = Number(event.target.value);
              setPageSize(next);
              gridApiRef.current?.setGridOption("paginationPageSize", next);
            }}
          >
            {[20, 50, 100].map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
      </div>

      {!chatGptConnected && (
        <p className="notice">
          ChatGPT is not connected, so generating a resume will fall back to
          composing bullets from your database.json. Connect it on the{" "}
          <strong>Settings</strong> tab.
        </p>
      )}
      {!deepSeekConnected && (
        <p className="notice">
          DeepSeek is not connected. Extract JD requires a connected session;
          connect it on the{" "}
          <strong>Settings</strong> tab.
        </p>
      )}
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}

      <div
        className="jobs-grid"
        ref={wrapperRef}
        tabIndex={0}
        onKeyDown={onKeyDown}
        role="grid"
        aria-label="Jobs"
      >
        <AgGridReact<Job>
          rowData={rows}
          columnDefs={columnDefs}
          theme={useResolvedTheme() === "dark" ? gridThemeDark : gridThemeLight}
          context={gridContext}
          getRowId={(params) => params.data.id}
          onCellValueChanged={onCellValueChanged}
          onSelectionChanged={(event) =>
            setSelectedIds(event.api.getSelectedRows().map((job) => job.id))
          }
          onGridReady={(event) => {
            gridApiRef.current = event.api;
            range.setApi(event.api);
          }}
          pagination
          paginationPageSize={pageSize}
          suppressPaginationPanel={false}
          stopEditingWhenCellsLoseFocus
          singleClickEdit={false}
          // Checkboxes only: clicking a cell must start a range selection, not
          // tick the row, so the two selections stay independent of each other.
          rowSelection={{
            mode: "multiRow",
            checkboxes: true,
            headerCheckbox: true,
            enableClickSelection: false,
            // The header checkbox covers the page you can see. "All" would tick
            // rows scrolled out of sight, which is a poor deal for a delete.
            selectAll: "currentPage",
          }}
          suppressCellFocus={false}
        />
      </div>

      <ImportJobsDialog
        open={importOpen}
        status={importStatus}
        error={error}
        onStart={handleStartImport}
        onCancel={handleCancelImport}
        onClose={() => setImportOpen(false)}
      />
    </div>
  );
}
