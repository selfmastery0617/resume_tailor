import { useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { AgGridReact } from "ag-grid-react";
import {
  ModuleRegistry,
  AllCommunityModule,
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
import { DeepSeekConnect } from "./components/DeepSeekConnect";
import { TemplatesPage } from "./pages/TemplatesPage";
import { DEFAULT_SKILLS_PROMPT } from "./constants/prompts";
import "./App.css";

ModuleRegistry.registerModules([AllCommunityModule]);

/** Turn an extract-skills failure into something actionable.
 *  401 specifically means the exported DeepSeek session has expired. */
function describeExtractError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    if (!err.response) {
      return "Could not reach the backend. Is it running on port 8000?";
    }
    if (err.response.status === 401) {
      return "DeepSeek session expired. Re-run scripts/capture_deepseek_session.py to refresh it.";
    }
    const detail = (err.response.data as { detail?: string } | undefined)?.detail;
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
  const [prompt, setPrompt] = useState(DEFAULT_SKILLS_PROMPT);
  // job id -> epoch ms the extraction started, so each row can show elapsed time.
  const [extractingSince, setExtractingSince] = useState<Map<string, number>>(new Map());
  const gridApiRef = useRef<GridApi<Job> | null>(null);
  const [deepSeekConnected, setDeepSeekConnected] = useState(false);
  const [activeTab, setActiveTab] = useState<"jobs" | "templates">("jobs");

  // AG Grid does not re-render cells just because `context` changed, so the
  // Skills column has to be refreshed explicitly for the loading indicator to
  // mount and unmount.
  useEffect(() => {
    gridApiRef.current?.refreshCells({ columns: ["skills"], force: true });
  }, [extractingSince, deepSeekConnected]);

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

  return (
    <div className="app">
      <h1>JobTailor AI</h1>

      <nav className="main-nav" aria-label="Sections">
        {(["jobs", "templates"] as const).map((tab) => (
          <button
            key={tab}
            type="button"
            className={`nav-tab${activeTab === tab ? " nav-tab--active" : ""}`}
            aria-current={activeTab === tab ? "page" : undefined}
            onClick={() => setActiveTab(tab)}
          >
            {tab === "jobs" ? "Jobs" : "Templates"}
          </button>
        ))}
      </nav>

      {/* Kept mounted rather than conditionally rendered: unmounting would
          silently discard unsaved style edits when switching tabs. */}
      <div hidden={activeTab !== "templates"}>
        <TemplatesPage />
      </div>

      {/* The original Jobs view, unchanged — just scoped to its tab. */}
      <div hidden={activeTab !== "jobs"}>
      <button className="import-button" onClick={handleImportJobs} disabled={loading}>
        {loading && <span className="spinner" aria-hidden="true" />}
        {loading ? "Importing..." : "Import Jobs"}
      </button>
      {error && <p className="error">{error}</p>}
      {/* setDeepSeekConnected is a stable setState ref — passing an inline
          arrow here would re-trigger the child's session effect every render. */}
      <DeepSeekConnect onConnectedChange={setDeepSeekConnected} />
      <div className="prompt-section">
        <label htmlFor="skills-prompt">Skill Extraction Prompt</label>
        <textarea
          id="skills-prompt"
          className="prompt-textarea"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          rows={4}
        />
      </div>
      <div className="grid-container">
        <AgGridReact<Job>
          rowData={jobs}
          columnDefs={columnDefs}
          theme={themeQuartz}
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
    </div>
  );
}

export default App;
