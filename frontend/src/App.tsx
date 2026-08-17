import { useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { AgGridReact } from "ag-grid-react";
import {
  ModuleRegistry,
  AllCommunityModule,
  colorSchemeDark,
  themeQuartz,
  type ColDef,
  type GridApi,
} from "ag-grid-community";
import { extractSkills, importJobs } from "./api/jobs";
import type { Job } from "./types/job";
import { DescriptionCellRenderer } from "./components/DescriptionCellRenderer";
import { InfoModal } from "./components/InfoModal";
import { UrlCellRenderer } from "./components/UrlCellRenderer";
import { SkillsCellRenderer, type SkillsGridContext } from "./components/SkillsCellRenderer";
import { fetchSessionStatus } from "./api/deepseek";
import { fetchSettings } from "./api/settings";
import { TemplatesPage } from "./pages/TemplatesPage";
import { SettingsPage } from "./pages/SettingsPage";
import { ProfilePage } from "./pages/ProfilePage";
import { ThemeToggle, useResolvedTheme } from "./components/ThemeToggle";
import { DEFAULT_SKILLS_PROMPT } from "./constants/prompts";
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

/** Turn an extract-skills failure into something actionable. */
function describeExtractError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    if (!err.response) {
      return "Could not reach the backend. Is it running on port 8000?";
    }
    const detail = (err.response.data as { detail?: string } | undefined)?.detail;
    if (err.response.status === 401) {
      return detail ?? "DeepSeek is not authenticated. Reconnect it from Settings.";
    }
    if (detail) return detail;
  }
  return "Failed to extract skills. Check the backend logs for details.";
}

function App() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [descriptionModalJob, setDescriptionModalJob] = useState<Job | null>(null);
  const [skillsModalJob, setSkillsModalJob] = useState<Job | null>(null);
  // The prompt now lives in Settings (persisted); Jobs just reads it.
  const [prompt, setPrompt] = useState(DEFAULT_SKILLS_PROMPT);
  // job id -> epoch ms the extraction started, so each row can show elapsed time.
  const [extractingSince, setExtractingSince] = useState<Map<string, number>>(new Map());
  const gridApiRef = useRef<GridApi<Job> | null>(null);
  const [deepSeekConnected, setDeepSeekConnected] = useState(false);
  const [activeTab, setActiveTab] = useState<
    "jobs" | "profile" | "templates" | "settings"
  >("jobs");
  const resolvedTheme = useResolvedTheme();

  // AG Grid does not re-render cells just because `context` changed, so the
  // Skills column has to be refreshed explicitly for the loading indicator to
  // mount and unmount.
  useEffect(() => {
    gridApiRef.current?.refreshCells({ columns: ["skills"], force: true });
  }, [extractingSince, deepSeekConnected]);

  // Pull the prompt and connection state from Settings each time this tab is
  // shown, so changes made there take effect without a page reload.
  useEffect(() => {
    if (activeTab !== "jobs") return;
    let cancelled = false;
    (async () => {
      const [settingsResult, sessionResult] = await Promise.allSettled([
        fetchSettings(),
        fetchSessionStatus(),
      ]);
      if (cancelled) return;
      if (settingsResult.status === "fulfilled" && settingsResult.value.skillsPrompt) {
        setPrompt(settingsResult.value.skillsPrompt);
      }
      setDeepSeekConnected(
        sessionResult.status === "fulfilled" ? sessionResult.value.connected : false,
      );
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
        headerName: "Skills",
        field: "skills",
        width: 220,
        sortable: false,
        filter: false,
        cellRenderer: SkillsCellRenderer,
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

  const handleExtractSkills = async (job: Job) => {
    setExtractingSince((prev) => new Map(prev).set(job.id, Date.now()));
    setError(null);
    try {
      const skills = await extractSkills(job.description ?? "", prompt);
      setJobs((prev) => prev.map((j) => (j.id === job.id ? { ...j, skills } : j)));
    } catch (err) {
      setError(describeExtractError(err));
    } finally {
      setExtractingSince((prev) => {
        const next = new Map(prev);
        next.delete(job.id);
        return next;
      });
    }
  };

  const gridContext: SkillsGridContext = {
    extractingSince,
    connected: deepSeekConnected,
    onExtractSkills: handleExtractSkills,
    onViewSkills: setSkillsModalJob,
  };

  const NAV: { id: typeof activeTab; label: string; icon: string }[] = [
    { id: "jobs", label: "Jobs", icon: "📋" },
    { id: "profile", label: "Profile", icon: "👤" },
    { id: "templates", label: "Templates", icon: "🎨" },
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
      <InfoModal
        job={skillsModalJob}
        bodyText={skillsModalJob?.skills}
        onClose={() => setSkillsModalJob(null)}
      />
      </div>
      </main>
    </div>
  );
}

export default App;
