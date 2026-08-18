import { useEffect, useMemo, useRef, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import {
  ModuleRegistry,
  AllCommunityModule,
  colorSchemeDark,
  themeQuartz,
  type ColDef,
  type GridApi,
} from "ag-grid-community";
import { deleteJob, fetchJobs, importJobs, markJobApplied } from "./api/jobs";
import type { Job } from "./types/job";
import { DescriptionCellRenderer } from "./components/DescriptionCellRenderer";
import { InfoModal } from "./components/InfoModal";
import { UrlCellRenderer } from "./components/UrlCellRenderer";
import { fetchSessionStatus } from "./api/deepseek";
import {
  extractExperience,
  fetchAllExperience,
  type ExperienceResult,
} from "./api/experience";
import {
  fetchAllTailoredResumes,
  generateTailoredResume,
  type TailoredResume,
} from "./api/resumes";
import {
  ResumeCellRenderer,
  type ResumeGridContext,
} from "./components/ResumeCellRenderer";
import {
  JobActionsCellRenderer,
  type JobActionsGridContext,
} from "./components/JobActionsCellRenderer";
import { TemplatesPage } from "./pages/TemplatesPage";
import { SettingsPage } from "./pages/SettingsPage";
import { ProfilePage } from "./pages/ProfilePage";
import { TemplateBuilderPage } from "./pages/TemplateBuilderPage";
import { ThemeToggle, useResolvedTheme } from "./components/ThemeToggle";
import { ProgressConsole } from "./components/ProgressConsole";
import "./App.css";

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

function App() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [descriptionModalJob, setDescriptionModalJob] = useState<Job | null>(null);
  const gridApiRef = useRef<GridApi<Job> | null>(null);
  const [experienceExtracting, setExperienceExtracting] = useState<Map<string, number>>(new Map());
  const [experienceResults, setExperienceResults] = useState<Record<string, ExperienceResult>>({});
  const [resumeGenerating, setResumeGenerating] = useState<Map<string, number>>(new Map());
  const [resumeResults, setResumeResults] = useState<Record<string, TailoredResume>>({});
  const [jobActionBusy, setJobActionBusy] = useState<Map<string, "applying" | "deleting">>(
    new Map(),
  );
  const [notice, setNotice] = useState<string | null>(null);
  const [showConsole, setShowConsole] = useState(false);
  const [deepSeekConnected, setDeepSeekConnected] = useState(false);
  const [activeTab, setActiveTab] = useState<
    "jobs" | "profile" | "templates" | "builder" | "settings"
  >("jobs");
  const resolvedTheme = useResolvedTheme();

  // AG Grid does not re-render cells just because `context` changed, so the
  // Skills column has to be refreshed explicitly for the loading indicator to
  // mount and unmount.
  useEffect(() => {
    gridApiRef.current?.refreshCells({ columns: ["resume", "actions"], force: true });
  }, [experienceExtracting, experienceResults, resumeGenerating, resumeResults, jobActionBusy]);

  // Jobs are stored server-side now, so the table fills itself without needing
  // an import — along with the badges for anything extracted or generated.
  useEffect(() => {
    if (activeTab !== "jobs") return;
    (async () => {
      try {
        setJobs(await fetchJobs());
      } catch {
        /* an unreachable backend shows as the import error instead */
      }
      try {
        setExperienceResults(await fetchAllExperience());
      } catch {
        /* leave badges absent if the store is unreachable */
      }
      try {
        setResumeResults(await fetchAllTailoredResumes());
      } catch {
        /* same: a missing store only costs the badge */
      }
    })();
  }, [activeTab]);

  // Prompts live in Settings and are read server-side during extraction; this
  // only needs the connection state to gate the Extract button.
  useEffect(() => {
    if (activeTab !== "jobs") return;
    let cancelled = false;
    (async () => {
      try {
        const session = await fetchSessionStatus();
        if (!cancelled) setDeepSeekConnected(session.connected);
      } catch {
        if (!cancelled) setDeepSeekConnected(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeTab]);

  const columnDefs = useMemo<ColDef<Job>[]>(
    () => [
      { field: "id", headerName: "ID", width: 90 },
      { field: "title", headerName: "Title", flex: 1 },
      { field: "company", headerName: "Company", flex: 1 },
      { field: "location", headerName: "Location", flex: 1 },
      { field: "url", headerName: "URL", flex: 1, cellRenderer: UrlCellRenderer },
      {
        headerName: "Description",
        field: "description",
        width: 130,
        sortable: false,
        filter: false,
        cellRenderer: DescriptionCellRenderer,
        cellRendererParams: { onView: setDescriptionModalJob },
      },
      {
        headerName: "Resume",
        colId: "resume",
        width: 230,
        sortable: false,
        filter: false,
        cellRenderer: ResumeCellRenderer,
      },
      {
        headerName: "Actions",
        colId: "actions",
        // Fits "✅ Applied 12/31/2026" plus the delete button without clipping.
        width: 215,
        sortable: false,
        filter: false,
        cellRenderer: JobActionsCellRenderer,
      },
    ],
    [],
  );

  // An applied job is a record of what was sent, so the whole row is greyed to
  // say so at a glance rather than only its buttons.
  const getRowClass = (params: { data?: Job }) =>
    params.data?.applied ? "job-row--applied" : undefined;

  const handleImportJobs = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await importJobs();
      setJobs(data);
    } catch {
      setError(
        "Failed to import jobs from Jobright. Check that the backend is running and JOBRIGHT_COOKIE is valid.",
      );
    } finally {
      setLoading(false);
    }
  };

  const describeError = (err: unknown, fallback: string) =>
    // The backend names the exact fix (no output folder, no profile, no
    // extraction), so prefer its message over a generic failure.
    (err as { response?: { data?: { detail?: { message?: string } } } }).response?.data?.detail
      ?.message ?? fallback;

  /** Step 1 of the Resume button: extract, unless this job already has one. */
  const ensureExperience = async (job: Job) => {
    if (experienceResults[job.id]) return true;

    setExperienceExtracting((prev) => new Map(prev).set(job.id, Date.now()));
    try {
      const result = await extractExperience({
        jobId: job.id,
        jobDescription: job.description ?? "",
        jobTitle: job.title,
        // Skills are derived server-side as step 1 of the pipeline and reported
        // in the console, so nothing is passed from the table.
      });
      setExperienceResults((prev) => ({ ...prev, [job.id]: result }));
      return true;
    } catch (err) {
      setError(describeError(err, "Could not extract experience. Check the backend logs."));
      return false;
    } finally {
      setExperienceExtracting((prev) => {
        const next = new Map(prev);
        next.delete(job.id);
        return next;
      });
    }
  };

  const handleGenerateResume = async (job: Job) => {
    setError(null);
    // The bullets and the summary are only shown in the console now, so open it
    // rather than running a minute of work behind a collapsed panel.
    setShowConsole(true);

    if (!(await ensureExperience(job))) return;

    setResumeGenerating((prev) => new Map(prev).set(job.id, Date.now()));
    try {
      const saved = await generateTailoredResume({
        jobId: job.id,
        company: job.company,
        jobTitle: job.title,
      });
      setResumeResults((prev) => ({ ...prev, [job.id]: saved }));
    } catch (err) {
      setError(describeError(err, "Could not generate the resume PDF. Check the backend logs."));
    } finally {
      setResumeGenerating((prev) => {
        const next = new Map(prev);
        next.delete(job.id);
        return next;
      });
    }
  };

  const setBusy = (jobId: string, action: "applying" | "deleting" | null) =>
    setJobActionBusy((prev) => {
      const next = new Map(prev);
      if (action) next.set(jobId, action);
      else next.delete(jobId);
      return next;
    });

  const handleMarkApplied = async (job: Job) => {
    // Confirmed because it is one-way: the row freezes and the bullets behind a
    // submitted application can no longer be rewritten. A mis-click should not
    // cost that.
    const ok = window.confirm(
      `Mark "${job.title}" at ${job.company} as applied?\n\n` +
        "This locks the row — its experience and resume can no longer be regenerated.",
    );
    if (!ok) return;

    setBusy(job.id, "applying");
    setError(null);
    setNotice(null);
    try {
      const updated = await markJobApplied(job.id);
      setJobs((prev) => prev.map((j) => (j.id === job.id ? updated : j)));
      setNotice(`Marked "${updated.title}" as applied.`);
    } catch (err) {
      setError(describeError(err, "Could not mark the job as applied."));
    } finally {
      setBusy(job.id, null);
    }
  };

  const handleDeleteJob = async (job: Job) => {
    const hasResume = Boolean(resumeResults[job.id]);
    const ok = window.confirm(
      `Delete "${job.title}" at ${job.company}?\n\n` +
        "This removes the job, its extracted experience and its resume record." +
        (hasResume ? "\n\nThe PDF already saved to your output folder is kept." : ""),
    );
    if (!ok) return;

    setBusy(job.id, "deleting");
    setError(null);
    setNotice(null);
    try {
      const result = await deleteJob(job.id);
      setJobs((prev) => prev.filter((j) => j.id !== job.id));
      // Drop the derived state too, or a re-import of the same listing would
      // show a badge for an extraction that no longer exists.
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
      setNotice(
        result.orphanedFile
          ? `Deleted "${result.title}". Its PDF is still at ${result.orphanedFile}`
          : `Deleted "${result.title}".`,
      );
    } catch (err) {
      setError(describeError(err, "Could not delete the job."));
    } finally {
      setBusy(job.id, null);
    }
  };

  const gridContext: ResumeGridContext & JobActionsGridContext = {
    experienceExtracting,
    experienceResults,
    resumeGenerating,
    resumeResults,
    onGenerateResume: handleGenerateResume,
    jobActionBusy,
    onMarkApplied: handleMarkApplied,
    onDeleteJob: handleDeleteJob,
  };

  const NAV: { id: typeof activeTab; label: string; icon: string }[] = [
    { id: "jobs", label: "Jobs", icon: "📋" },
    { id: "profile", label: "Profile", icon: "👤" },
    { id: "templates", label: "Templates", icon: "🎨" },
    { id: "builder", label: "Builder", icon: "🧩" },
    { id: "settings", label: "Settings", icon: "⚙️" },
  ];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <h1>JobTailor AI</h1>
        </div>

        <nav className="sidebar-nav" aria-label="Sections">
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-item${activeTab === item.id ? " nav-item--active" : ""}`}
              aria-current={activeTab === item.id ? "page" : undefined}
              onClick={() => setActiveTab(item.id)}
            >
              <span className="nav-icon" aria-hidden="true">
                {item.icon}
              </span>
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <button
            type="button"
            className={`console-toggle${showConsole ? " console-toggle--on" : ""}`}
            onClick={() => setShowConsole((v) => !v)}
            aria-pressed={showConsole}
          >
            <span aria-hidden="true">🖥️</span>
            <span>Console</span>
          </button>
          <ThemeToggle />
        </div>
      </aside>

      <main className="app-main">
      {/* Kept mounted rather than conditionally rendered: unmounting would
          silently discard unsaved style edits when switching tabs. */}
      <div hidden={activeTab !== "profile"}>
        <ProfilePage active={activeTab === "profile"} />
      </div>

      <div hidden={activeTab !== "templates"}>
        <TemplatesPage active={activeTab === "templates"} />
      </div>

      <div hidden={activeTab !== "builder"}>
        <TemplateBuilderPage active={activeTab === "builder"} />
      </div>

      <div hidden={activeTab !== "settings"}>
        <SettingsPage />
      </div>

      {/* The original Jobs view, unchanged — just scoped to its tab. */}
      <div hidden={activeTab !== "jobs"}>
      <button className="import-button" onClick={handleImportJobs} disabled={loading}>
        {loading && <span className="spinner" aria-hidden="true" />}
        {loading ? "Importing..." : "Import Jobs"}
      </button>
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      {/* The connection panel and prompt editor moved to Settings; this page
          reads both, and only surfaces a pointer when something is missing. */}
      {!deepSeekConnected && (
        <p className="notice">
          DeepSeek is not connected, so skill extraction is disabled. Connect it
          on the <strong>Settings</strong> tab.
        </p>
      )}
      <div className="grid-container">
        <AgGridReact<Job>
          rowData={jobs}
          columnDefs={columnDefs}
          theme={resolvedTheme === "dark" ? gridThemeDark : gridThemeLight}
          context={gridContext}
          getRowId={(params) => params.data.id}
          getRowClass={getRowClass}
          onGridReady={(event) => {
            gridApiRef.current = event.api;
          }}
        />
      </div>
      <InfoModal
        job={descriptionModalJob}
        bodyText={descriptionModalJob?.description}
        onClose={() => setDescriptionModalJob(null)}
      />
      </div>
      </main>

      {showConsole && <ProgressConsole onClose={() => setShowConsole(false)} />}
    </div>
  );
}

export default App;
