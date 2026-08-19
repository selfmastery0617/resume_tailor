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
  createJob,
  deleteJobRows,
  fetchJobs,
  importJobs,
  updateJob,
} from "../api/jobs";
import {
  fetchAllTailoredResumes,
  generateTailoredResume,
  type TailoredResume,
} from "../api/resumes";
import { extractExperience, fetchAllExperience, type ExperienceResult } from "../api/experience";
import { fetchSessionStatus } from "../api/deepseek";
import type { Job } from "../types/job";
import { InfoModal } from "../components/InfoModal";
import { UrlCellRenderer } from "../components/UrlCellRenderer";
import { ResumeCellRenderer, type ResumeGridContext } from "../components/ResumeCellRenderer";
import { DescriptionActionCell } from "../components/jobs/DescriptionActionCell";
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
  selectedRowBackgroundColor: "rgba(59, 125, 221, 0.12)",
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
  selectedRowBackgroundColor: "rgba(91, 147, 240, 0.16)",
  accentColor: "#5b93f0",
  fontFamily: "inherit",
  fontSize: "13px",
  wrapperBorderRadius: "8px",
});

/** Column order is fixed by the spec; the ids double as the selection order. */
const COLUMN_IDS = [
  "id",
  "date_added",
  "title",
  "company",
  "url",
  "location",
  "description",
  "resume",
  "status",
];

/** Cells a person may type into. The rest come from the import or the pipeline. */
const EDITABLE = new Set(["date_added", "title", "company", "url", "location", "status"]);

/** Cleared by Delete. Status is excluded: it can never go back to empty. */
const CLEARABLE = ["date_added", "title", "company", "url", "location"];


export function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [experienceResults, setExperienceResults] = useState<Record<string, ExperienceResult>>({});
  const [resumeResults, setResumeResults] = useState<Record<string, TailoredResume>>({});
  const [experienceExtracting, setExperienceExtracting] = useState<Map<string, number>>(new Map());
  const [resumeGenerating, setResumeGenerating] = useState<Map<string, number>>(new Map());
  const [descriptionModalJob, setDescriptionModalJob] = useState<Job | null>(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pageSize, setPageSize] = useState(20);
  const [deepSeekConnected, setDeepSeekConnected] = useState(true);
  const [deletingRows, setDeletingRows] = useState<Set<string>>(new Set());

  const gridApiRef = useRef<GridApi<Job> | null>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // The table shows exactly what is stored. There is no placeholder row: an
  // empty row that renders pipeline controls reads as broken data, and "Add
  // row" says what it does. Paste past the last row still creates rows.
  const rows = jobs;

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

  useEffect(() => {
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
        setDeepSeekConnected((await fetchSessionStatus()).connected);
      } catch {
        setDeepSeekConnected(false);
      }
    })();
  }, [reload]);

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
      case "id":
        return job.id;
      case "description":
        return job.description ? "yes" : "";
      case "resume":
        return resumeResults[job.id]?.fileName ?? "";
      default:
        return String((job as unknown as Record<string, unknown>)[colId] ?? "");
    }
  }, [resumeResults]);

  const copySelection = useCallback(async () => {
    if (!range.range) return;
    const lines: string[] = [];
    for (let r = range.range.top; r <= range.range.bottom; r += 1) {
      const job = rows[r];
      if (!job) continue;
      lines.push(range.range.columns.map((colId) => cellText(job, colId)).join("\t"));
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
      const matrix = text
        .replace(/\r\n?/g, "\n")
        .replace(/\n$/, "")
        .split("\n")
        .map((line) => line.split("\t"));
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
    [range.anchor, rows, reload],
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

  const deleteSelectedRows = useCallback(async () => {
    if (!range.range) return;
    const ids: string[] = [];
    for (let r = range.range.top; r <= range.range.bottom; r += 1) {
      const job = rows[r];
      if (job) ids.push(job.id);
    }
    if (!ids.length) return;
    if (!window.confirm(`Delete ${ids.length} row${ids.length === 1 ? "" : "s"}? This cannot be undone.`)) {
      return;
    }
    try {
      const result = await deleteJobRows(ids);
      range.clear();
      await reload();
      setNotice(`Deleted ${result.count} row${result.count === 1 ? "" : "s"}.`);
    } catch (err) {
      setError(describeError(err, "Could not delete those rows."));
    }
  }, [range, rows, reload]);

  const deleteRow = useCallback(
    async (job: Job) => {
      const label = job.title || job.company || "this row";
      if (!window.confirm(`Delete "${label}"?

This also removes its extracted experience and resume record. Any PDF already saved to your output folder stays on disk.`)) {
        return;
      }
      setDeletingRows((prev) => new Set(prev).add(job.id));
      setError(null);
      try {
        await deleteJobRows([job.id]);
        setExperienceResults((prev) => {
          const next = { ...prev };
          delete next[job.id];
          return next;
        });
        setResumeResults((prev) => {
          const next = { ...prev };
          delete next[job.id];
          return next;
        });
        range.clear();
        await reload();
        setNotice(`Deleted "${label}".`);
      } catch (err) {
        setError(describeError(err, "Could not delete that row."));
      } finally {
        setDeletingRows((prev) => {
          const next = new Set(prev);
          next.delete(job.id);
          return next;
        });
      }
    },
    [range, reload],
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
        if (meta) void deleteSelectedRows();
        else void clearSelection();
      } else if (event.key === "Escape") {
        range.clear();
      }
    },
    [copySelection, pasteIntoSelection, clearSelection, deleteSelectedRows, range],
  );

  // -- pipeline --------------------------------------------------------------

  const handleGenerateResume = useCallback(
    async (job: Job) => {
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
          return;
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
      } catch (err) {
        setError(describeError(err, "Could not generate the resume."));
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

  const handleImport = async () => {
    setImporting(true);
    setError(null);
    try {
      setJobs(await importJobs());
    } catch {
      setError("Failed to import jobs. Check the backend and JOBRIGHT_COOKIE.");
    } finally {
      setImporting(false);
    }
  };

  // -- columns ---------------------------------------------------------------

  const columnDefs = useMemo<ColDef<Job>[]>(() => {
    const selectable = (colId: string) => ({
      cellClass: (params: { data?: Job; node: { rowIndex: number | null } }) =>
        range.inRange(params.node.rowIndex, colId) ? "cell-selected" : "",
    });

    return [
      {
        colId: "id",
        headerName: "ID",
        width: 96,
        editable: false,
        valueGetter: (p: ValueGetterParams<Job>) =>
          p.data?.id?.slice(0, 8) ?? "",
        ...selectable("id"),
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
        colId: "title",
        field: "title",
        headerName: "Title",
        flex: 2,
        minWidth: 180,
        editable: true,
        ...selectable("title"),
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
        colId: "location",
        field: "location",
        headerName: "Location",
        flex: 1,
        minWidth: 120,
        editable: true,
        ...selectable("location"),
      },
      {
        colId: "description",
        headerName: "Description",
        width: 160,
        editable: false,
        sortable: false,
        cellRenderer: DescriptionActionCell,
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

  const gridContext: ResumeGridContext &
    RowDeleteContext &
    StatusContext & {
      onViewDescription: (job: Job) => void;
      onGenerateDescription: (job: Job) => void;
    } = {
    experienceExtracting,
    experienceResults,
    resumeGenerating,
    resumeResults,
    onGenerateResume: handleGenerateResume,
    onViewDescription: setDescriptionModalJob,
    deletingRows,
    onDeleteRow: deleteRow,
    onChangeStatus: changeStatus,
    onGenerateDescription: () =>
      setNotice("Generate Description isn't wired up yet — its behaviour is still to be decided."),
  };

  return (
    <div className="jobs-page">
      <div className="jobs-toolbar">
        <button className="import-button" onClick={handleImport} disabled={importing}>
          {importing && <span className="spinner" aria-hidden="true" />}
          {importing ? "Importing…" : "Import Jobs"}
        </button>
        <button type="button" onClick={() => void addRow()}>
          + Add row
        </button>
        <span className="jobs-hint">
          Drag to select · Ctrl+C / Ctrl+V · Delete clears cells · 🗑 or Ctrl+Delete removes rows
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

      {!deepSeekConnected && (
        <p className="notice">
          DeepSeek is not connected, so generating a resume will fall back to
          composing bullets from your database.json. Connect it on the{" "}
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
          onGridReady={(event) => {
            gridApiRef.current = event.api;
            range.setApi(event.api);
          }}
          pagination
          paginationPageSize={pageSize}
          suppressPaginationPanel={false}
          stopEditingWhenCellsLoseFocus
          singleClickEdit={false}
          // The custom range selection owns highlighting; AG Grid's own row
          // selection would fight it.
          rowSelection={undefined}
          suppressCellFocus={false}
        />
      </div>

      <InfoModal
        job={descriptionModalJob}
        bodyText={descriptionModalJob?.description}
        onClose={() => setDescriptionModalJob(null)}
      />
    </div>
  );
}
