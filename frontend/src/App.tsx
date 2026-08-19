import { useState } from "react";
import { JobsPage } from "./pages/JobsPage";
import { TemplatesPage } from "./pages/TemplatesPage";
import { SettingsPage } from "./pages/SettingsPage";
import { ProfilePage } from "./pages/ProfilePage";
import { TemplateBuilderPage } from "./pages/TemplateBuilderPage";
import { ThemeToggle } from "./components/ThemeToggle";
import { ProgressConsole } from "./components/ProgressConsole";
import "./App.css";

/** The shell: navigation, theme, and the progress console. Each tab owns its
 *  own data — the jobs table moved to JobsPage when it became a spreadsheet. */
function App() {
  const [showConsole, setShowConsole] = useState(false);
  const [activeTab, setActiveTab] = useState<
    "jobs" | "profile" | "templates" | "builder" | "settings"
  >("jobs");


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

      <div hidden={activeTab !== "jobs"}>
        <JobsPage />
      </div>
      </main>

      {showConsole && <ProgressConsole onClose={() => setShowConsole(false)} />}
    </div>
  );
}

export default App;
