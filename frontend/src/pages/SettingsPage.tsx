/** Settings: AI connections, prompts, and the output folder.
 *
 *  Settings persist in SQLite, so unlike the old in-memory prompt they survive
 *  a reload and a server restart.
 */

import { useCallback, useEffect, useState } from "react";
import { fetchLoginStatus, fetchSessionStatus, startLogin } from "../api/deepseek";
import {
  checkFolder,
  fetchChatGptLoginStatus,
  fetchChatGptSession,
  fetchSettings,
  saveSettings,
  startChatGptLogin,
  type AppSettings,
  type FolderCheck,
  type GenerationModel,
} from "../api/settings";
import {
  fetchExperienceDatabase,
  saveExperienceDatabase,
  type DatabaseInfo,
} from "../api/experience";
import { fetchProfiles } from "../api/templates";
import type { Profile } from "../resume/types";
import { DeepSeekLoginPanel } from "../components/DeepSeekLoginPanel";
import { ProviderConnect } from "../components/ProviderConnect";

/** Mirrors TAILORING_PLACEHOLDERS in backend settings_service.py. */
const TAILORING_PLACEHOLDERS = [
  "count",
  "company",
  "product",
  "job_description",
  "achievements",
] as const;

/** Mirrors SUMMARY_PLACEHOLDERS in backend settings_service.py. */
const SUMMARY_PLACEHOLDERS = [
  "sentences",
  "job_title",
  "job_description",
  "companies",
  "bullets",
] as const;

function PlaceholderList({ tokens }: { tokens: readonly string[] }) {
  return (
    <>
      {tokens.map((token, index) => (
        <span key={token}>
          {index > 0 && ", "}
          <code>{`{${token}}`}</code>
        </span>
      ))}
    </>
  );
}

export function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const [folderCheck, setFolderCheck] = useState<FolderCheck | null>(null);
  const [dbInfo, setDbInfo] = useState<DatabaseInfo | null>(null);
  const [dbText, setDbText] = useState("");
  const [dbError, setDbError] = useState<string | null>(null);
  const [dbNotice, setDbNotice] = useState<string | null>(null);
  const [dbSaving, setDbSaving] = useState(false);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [showDeepSeekLogin, setShowDeepSeekLogin] = useState(false);
  // Bumped after a successful sign-in to make the provider cards re-check.
  const [providerRefresh, setProviderRefresh] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const loaded = await fetchSettings();
        setSettings(loaded);
        setDraft(loaded);
      } catch {
        setError("Could not load settings. Is the backend running on port 8000?");
      }
      try {
        const info = await fetchExperienceDatabase();
        setDbInfo(info);
        setDbText(info.text);
        if (!info.valid && info.detail) setDbError(info.detail);
      } catch {
        setDbError("Could not load database.json.");
      }
      try {
        setProfiles(await fetchProfiles());
      } catch {
        /* the dropdown falls back to "No profiles yet" */
      }
    })();
  }, []);

  const handleSaveDatabase = async () => {
    setDbSaving(true);
    setDbError(null);
    setDbNotice(null);
    try {
      const { companies } = await saveExperienceDatabase(dbText);
      // Dropdown updates immediately from the save response.
      setDbInfo((prev) => (prev ? { ...prev, companies, valid: true, text: dbText } : prev));
      setDbNotice(`Saved. ${companies.length} companies available.`);
      // A saved edit can remove the selected company; clear it rather than
      // leaving a selection that would fail at extraction time.
      if (draft && draft.firstCompany && !companies.includes(draft.firstCompany)) {
        update("firstCompany", "");
        setDbNotice(
          `Saved. "${draft.firstCompany}" no longer exists, so First Company was cleared.`,
        );
      }
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: { message?: string } } } })
        .response?.data?.detail?.message;
      setDbError(detail ?? "Could not save database.json.");
    } finally {
      setDbSaving(false);
    }
  };

  const dirty =
    settings !== null && draft !== null && JSON.stringify(settings) !== JSON.stringify(draft);

  // Dropping a placeholder silently strips context from the prompt, so flag it
  // rather than letting the model receive a half-built instruction.
  const missingPlaceholders = TAILORING_PLACEHOLDERS.filter(
    (token) => !(draft?.tailoringPrompt ?? "").includes(`{${token}}`),
  );
  const missingSummaryPlaceholders = SUMMARY_PLACEHOLDERS.filter(
    (token) => !(draft?.summaryPrompt ?? "").includes(`{${token}}`),
  );

  // Mirrors build_tailored_pdf_filename() so the file name is visible before
  // anything is generated. An empty selection means "first profile".
  const resumeProfileName =
    (profiles.find((p) => p.id === draft?.resumeProfile) ?? profiles[0])?.name ?? "Profile";
  const savedFileExample = `${resumeProfileName}_resume.pdf`;

  // Guard against losing unsaved prompt edits on reload.
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const update = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => {
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev));
    setNotice(null);
  };

  const handleCheckFolder = useCallback(async () => {
    if (!draft) return;
    try {
      setFolderCheck(await checkFolder(draft.outputFolder));
    } catch {
      setFolderCheck({ valid: false, detail: "Could not verify the folder." });
    }
  }, [draft]);

  const handleSave = async () => {
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await saveSettings(draft);
      setSettings(saved);
      setDraft(saved);
      setNotice("Settings saved.");
    } catch (err) {
      // The backend explains exactly which value was rejected.
      const detail =
        (err as { response?: { data?: { detail?: { message?: string } } } }).response?.data?.detail
          ?.message;
      setError(detail ?? "Could not save settings.");
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setDraft(settings);
    setFolderCheck(null);
    setNotice(null);
  };

  if (!draft) return <p>Loading settings…</p>;

  return (
    <div className="settings-page">
      <section className="settings-section">
        <h2>AI connections</h2>
        <p className="notice">
          Sign in through your browser — no API keys needed. Sessions expire
          periodically; reconnect here when they do.
        </p>
        <div className="provider-grid">
          <ProviderConnect
            key={`deepseek-${providerRefresh}`}
            label="DeepSeek"
            description="Used for skill extraction and, optionally, resume tailoring."
            fetchSession={fetchSessionStatus}
            startLogin={startLogin}
            fetchLoginStatus={fetchLoginStatus}
            // Sign in inside the page instead of opening a separate window.
            onConnectClick={() => setShowDeepSeekLogin(true)}
          />
          <ProviderConnect
            label="ChatGPT"
            description="Alternative model for generating tailored resumes and cover letters."
            fetchSession={fetchChatGptSession}
            startLogin={startChatGptLogin}
            fetchLoginStatus={fetchChatGptLoginStatus}
          />
        </div>

        {showDeepSeekLogin && (
          <DeepSeekLoginPanel
            onSignedIn={() => {
              // Remount the card so it re-verifies and turns green.
              setProviderRefresh((n) => n + 1);
            }}
            onClose={() => {
              setShowDeepSeekLogin(false);
              setProviderRefresh((n) => n + 1);
            }}
          />
        )}

        <div className="style-row" style={{ maxWidth: 420 }}>
          <label htmlFor="generation-model" className="style-label">
            Model used for generation
          </label>
          <div className="style-control">
            <select
              id="generation-model"
              value={draft.generationModel}
              onChange={(event) => update("generationModel", event.target.value as GenerationModel)}
            >
              <option value="deepseek">DeepSeek</option>
              <option value="chatgpt">ChatGPT</option>
            </select>
          </div>
        </div>
      </section>

      <section className="settings-section">
        <h2>Experience database</h2>
        <p className="notice">
          Source of truth for experience extraction: Company → Product → Projects →
          Challenges. Stored at <code>{dbInfo?.path ?? "backend/data/database.json"}</code>.
        </p>

        <div className="style-row" style={{ maxWidth: 520 }}>
          <label htmlFor="first-company" className="style-label">
            First Company (Job 1)
          </label>
          <div className="style-control">
            <select
              id="first-company"
              value={draft.firstCompany}
              onChange={(event) => update("firstCompany", event.target.value)}
              disabled={!dbInfo?.companies.length}
            >
              <option value="">— none selected —</option>
              {(dbInfo?.companies ?? []).map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>
        </div>
        {!draft.firstCompany && (
          <p className="notice exp-warn">
            No first company selected — experience extraction will refuse to run.
          </p>
        )}
        {/* A stored company can go stale when database.json is edited outside
            the app; surface it here instead of failing at extraction time. */}
        {draft.firstCompany &&
          dbInfo?.companies.length &&
          !dbInfo.companies.includes(draft.firstCompany) && (
            <p className="error">
              “{draft.firstCompany}” is no longer in database.json. Pick another
              company — extraction will fail until you do.
            </p>
          )}

        <div className="prompt-section">
          <label htmlFor="database-json">database.json</label>
          <textarea
            id="database-json"
            className="prompt-textarea db-editor"
            rows={16}
            spellCheck={false}
            value={dbText}
            onChange={(event) => {
              setDbText(event.target.value);
              setDbNotice(null);
            }}
          />
        </div>
        {dbError && <p className="error">{dbError}</p>}
        {dbNotice && <p className="notice">{dbNotice}</p>}
        <button type="button" onClick={handleSaveDatabase} disabled={dbSaving}>
          {dbSaving ? "Saving…" : "Save database.json"}
        </button>
      </section>

      <section className="settings-section">
        <h2>Output folder</h2>
        <p className="notice">
          Generated resumes are saved here, in a
          <code> [mm-dd-yy]_[Company]_[Job Title]</code> folder per job.
        </p>
        <div className="folder-row">
          <input
            id="output-folder"
            type="text"
            className="folder-input"
            placeholder="D:\JobTailor\Applications"
            value={draft.outputFolder}
            onChange={(event) => update("outputFolder", event.target.value)}
            aria-label="Output folder path"
          />
          <button type="button" onClick={handleCheckFolder}>
            Verify
          </button>
        </div>
        {folderCheck && (
          <p className={folderCheck.valid ? "notice" : "error"}>{folderCheck.detail}</p>
        )}
        {!draft.outputFolder && (
          <p className="notice exp-warn">
            No output folder set — the Resume column will refuse to generate.
          </p>
        )}

        <div className="style-row" style={{ maxWidth: 520 }}>
          <label htmlFor="resume-profile" className="style-label">
            Resume profile
          </label>
          <div className="style-control">
            <select
              id="resume-profile"
              value={draft.resumeProfile}
              onChange={(event) => update("resumeProfile", event.target.value)}
              disabled={!profiles.length}
            >
              {/* Empty is a real choice, not a placeholder: the backend falls
                  back to the first profile so a single-profile setup needs no
                  decision here. */}
              <option value="">
                {profiles.length ? `First profile (${profiles[0].name})` : "No profiles yet"}
              </option>
              {profiles.map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {profile.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <p className="notice">
          Supplies the name, contact details, education, skills and template for
          tailored resumes. Saved as <code>{savedFileExample}</code>.
        </p>
      </section>

      <section className="settings-section">
        <h2>Prompts</h2>
        <p className="notice">
          All four prompts for one job run as turns in a{" "}
          <strong>single DeepSeek chat</strong>, so each one still has the
          earlier answers in context.
        </p>
        <div className="prompt-section">
          <label htmlFor="settings-skills-prompt">1. Skill extraction prompt</label>
          <p className="notice">
            Pulls the required skills and the job mission out of the
            description. Results appear in the console.
          </p>
          <textarea
            id="settings-skills-prompt"
            className="prompt-textarea"
            rows={6}
            value={draft.skillsPrompt}
            onChange={(event) => update("skillsPrompt", event.target.value)}
          />
        </div>

        <div className="prompt-section">
          <label htmlFor="settings-tailoring-prompt">2. Bullet tailoring prompt</label>
          <p className="notice">
            Turns the selected challenges into resume bullets — run twice, once
            per role. These placeholders are substituted before sending:{" "}
            <PlaceholderList tokens={TAILORING_PLACEHOLDERS} />. Any other braces
            are left as written.
          </p>
          <textarea
            id="settings-tailoring-prompt"
            className="prompt-textarea"
            rows={12}
            value={draft.tailoringPrompt}
            onChange={(event) => update("tailoringPrompt", event.target.value)}
          />
          {missingPlaceholders.length > 0 && (
            <p className="notice exp-warn">
              Missing {missingPlaceholders.map((t) => `{${t}}`).join(", ")} — the
              model won't receive that context.
            </p>
          )}
        </div>

        <div className="prompt-section">
          <label htmlFor="settings-summary-prompt">3. Summary extraction prompt</label>
          <p className="notice">
            Runs last, once both sets of bullets exist, and writes the summary
            that goes at the top of the generated resume. Placeholders:{" "}
            <PlaceholderList tokens={SUMMARY_PLACEHOLDERS} />.
          </p>
          <textarea
            id="settings-summary-prompt"
            className="prompt-textarea"
            rows={12}
            value={draft.summaryPrompt}
            onChange={(event) => update("summaryPrompt", event.target.value)}
          />
          {missingSummaryPlaceholders.length > 0 && (
            <p className="notice exp-warn">
              Missing {missingSummaryPlaceholders.map((t) => `{${t}}`).join(", ")}{" "}
              — the model won't receive that context.
            </p>
          )}
        </div>
      </section>

      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}

      <div className="settings-actions">
        {dirty && <span className="unsaved-badge">Unsaved changes</span>}
        <button type="button" onClick={handleCancel} disabled={!dirty || saving}>
          Cancel
        </button>
        <button type="button" onClick={handleSave} disabled={!dirty || saving}>
          {saving ? "Saving…" : "Save settings"}
        </button>
      </div>
    </div>
  );
}
