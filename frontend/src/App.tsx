import { useCallback, useEffect, useState } from "react";
import { JobsPage } from "./pages/JobsPage";
import { TemplatesPage } from "./pages/TemplatesPage";
import { CoverLetterTemplatesPage } from "./pages/CoverLetterTemplatesPage";
import { SettingsPage } from "./pages/SettingsPage";
import { ProfilePage } from "./pages/ProfilePage";
import { TemplateBuilderPage } from "./pages/TemplateBuilderPage";
import { ThemeToggle } from "./components/ThemeToggle";
import { ProgressConsole } from "./components/ProgressConsole";
import { fetchSettledSessionStatus } from "./api/deepseek";
import { fetchSettledJobrightSession } from "./api/jobright";
import { fetchSettledChatGptSession } from "./api/chatgpt";
import { fetchHealth } from "./api/health";
import { fetchProfiles } from "./api/templates";
import { useActiveProfileSettings } from "./hooks/useActiveProfileSettings";
import "./App.css";

/** The shell: navigation, theme, and the console dock. Each tab owns its own
 *  data — the jobs table moved to JobsPage when it became a spreadsheet —
 *  but provider connection state is shared, because signing in on Settings
 *  has to be visible in the sidebar and on the Jobs banner at once. */
function App() {
  const [showConsole, setShowConsole] = useState(false);
  // Bumped whenever a provider session may have changed (a sign-in or
  // sign-out on Settings). Everything that displays connection state watches
  // this instead of polling on its own schedule, so no view is left showing a
  // stale answer.
  const [sessionVersion, setSessionVersion] = useState(0);
  // null while the first check is in flight — "unknown" is not "disconnected".
  const [deepSeekOk, setDeepSeekOk] = useState<boolean | null>(null);
  const [jobrightOk, setJobrightOk] = useState<boolean | null>(null);
  const [chatGptOk, setChatGptOk] = useState<boolean | null>(null);
  const [activeTab, setActiveTab] = useState<
    "jobs" | "profile" | "templates" | "coverLetterTemplates" | "builder" | "settings"
  >("jobs");
  // The backend is serving code older than the files on disk. Silent until it
  // happens, and it has caused several rounds of "the feature does nothing".
  const [staleBackend, setStaleBackend] = useState(false);

  // The sidebar is always mounted and visible, so unlike every other page it
  // can't just refetch on "this tab became active" -- profileVersion is
  // bumped by ProfilePage whenever the shared active profile actually
  // changes there, so this picks it up live instead of only after switching
  // tabs and back.
  const [profileVersion, setProfileVersion] = useState(0);
  const refreshProfile = useCallback(() => setProfileVersion((v) => v + 1), []);
  const { settings: profileSettings } = useActiveProfileSettings(true, profileVersion);
  const [profiles, setProfiles] = useState<{ id: string; name: string }[]>([]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const list = await fetchProfiles();
        if (alive) setProfiles(list.map((p) => ({ id: p.id, name: p.name })));
      } catch {
        /* the sidebar just shows nothing until the next successful fetch */
      }
    })();
    return () => {
      alive = false;
    };
  }, [profileVersion]);

  // Empty resumeProfile is a real choice meaning "the first profile" -- same
  // fallback used on Templates/Builder pages.
  const activeProfileName = profileSettings?.resumeProfile
    ? (profiles.find((p) => p.id === profileSettings.resumeProfile)?.name ?? profiles[0]?.name)
    : profiles[0]?.name;

  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const health = await fetchHealth();
        if (alive) setStaleBackend(health.stale);
      } catch {
        /* unreachable is a different problem, and every page says so already */
      }
    };
    void check();
    // Slow: this only changes when a file is saved or the server restarts.
    const id = window.setInterval(check, 20000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  const refreshSession = useCallback(() => setSessionVersion((v) => v + 1), []);

  useEffect(() => {
    let alive = true;
    const check = async (
      fetch: () => Promise<{ connected: boolean }>,
      set: (value: boolean) => void,
    ) => {
      try {
        const status = await fetch();
        if (alive) set(status.connected);
      } catch {
        if (alive) set(false);
      }
    };
    // In parallel: DeepSeek's check launches a browser and takes seconds, and
    // queueing Jobright behind it would leave its dot grey for no reason.
    void check(fetchSettledSessionStatus, setDeepSeekOk);
    void check(fetchSettledJobrightSession, setJobrightOk);
    void check(fetchSettledChatGptSession, setChatGptOk);
    return () => {
      alive = false;
    };
  }, [sessionVersion]);

  const NAV: { id: typeof activeTab; label: string; icon: string }[] = [
    { id: "jobs", label: "Jobs", icon: "📋" },
    { id: "profile", label: "Profile", icon: "👤" },
    { id: "templates", label: "Templates", icon: "🎨" },
    { id: "coverLetterTemplates", label: "Cover Letter Templates", icon: "✉️" },
    { id: "builder", label: "Builder", icon: "🧩" },
    { id: "settings", label: "Settings", icon: "⚙️" },
  ];

  /** A read-only status dot per provider — sign-in itself happens from its
   *  card on Settings, so clicking one just takes you there. */
  const providerStatus = (label: string, connected: boolean | null) => (
    <button
      type="button"
      className="console-toggle"
      onClick={() => setActiveTab("settings")}
      title={
        connected === null
          ? `Checking the ${label} session…`
          : connected
            ? `${label} is connected`
            : `${label} is not connected — sign in on Settings`
      }
    >
      <span
        className={`deepseek-dot deepseek-dot--${
          connected === null ? "checking" : connected ? "ok" : "warn"
        }`}
        aria-hidden="true"
      />
      <span>{label}</span>
    </button>
  );

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <h1>JobTailor AI</h1>
        </div>

        <button
          type="button"
          className="sidebar-active-profile"
          onClick={() => setActiveTab("profile")}
          title="Switch or manage profiles"
        >
          <span className="sidebar-active-profile-label">Profile</span>
          <span className="sidebar-active-profile-name">
            {activeProfileName ?? "No profile yet"}
          </span>
        </button>

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
          {providerStatus("DeepSeek", deepSeekOk)}
          {providerStatus("Jobright", jobrightOk)}
          {providerStatus("ChatGPT", chatGptOk)}
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
      {staleBackend && (
        <p className="error stale-banner">
          The backend is running code older than your source files — restart it,
          or anything added since it started will silently do nothing.
        </p>
      )}
      {/* Kept mounted rather than conditionally rendered: unmounting would
          silently discard unsaved style edits when switching tabs. */}
      <div hidden={activeTab !== "profile"}>
        <ProfilePage active={activeTab === "profile"} onProfileChanged={refreshProfile} />
      </div>

      <div hidden={activeTab !== "templates"}>
        <TemplatesPage active={activeTab === "templates"} />
      </div>

      <div hidden={activeTab !== "coverLetterTemplates"}>
        <CoverLetterTemplatesPage active={activeTab === "coverLetterTemplates"} />
      </div>

      <div hidden={activeTab !== "builder"}>
        <TemplateBuilderPage active={activeTab === "builder"} />
      </div>

      <div hidden={activeTab !== "settings"}>
        <SettingsPage onProviderSignedOut={refreshSession} />
      </div>

      <div hidden={activeTab !== "jobs"}>
        <JobsPage sessionVersion={sessionVersion} active={activeTab === "jobs"} />
      </div>
      </main>

      {showConsole && (
        <div className="dock-column">
          <ProgressConsole onClose={() => setShowConsole(false)} />
        </div>
      )}
    </div>
  );
}

export default App;
