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
import { importJobs } from "./api/jobs";
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
    gridApiRef.current?.refreshCells({ columns: ["resume"], force: true });
  }, [experienceExtracting, experienceResults, resumeGenerating, resumeResults]);

  // Restore badges for jobs extracted or generated in an earlier session.
  useEffect(() => {
    if (activeTab !== "jobs") return;
    (async () => {
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
    ],
    [],
  );

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

  const gridContext: ResumeGridContext = {
    experienceExtracting,
    experienceResults,
    resumeGenerating,
    resumeResults,
    onGenerateResume: handleGenerateResume,
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
