/** Settings: AI connections and the output folder.
 *
 *  Settings persist in SQLite, so unlike the old in-memory prompt they survive
 *  a reload and a server restart. Prompts themselves live on the Profile tab
 *  now -- each profile has its own (see ProfilePage.tsx) -- and there's no
 *  profile picker here either; Profile page owns switching the active one.
 */

import { useEffect, useState } from "react";
import { fetchSettledSessionStatus, signOutDeepSeek } from "../api/deepseek";
import {
  fetchSettings,
  saveSettings,
  selectFolder,
  type AppSettings,
  type FolderCheck,
  type GenerationModel,
} from "../api/settings";
import {
  fetchSettledJobrightSession,
  signOutJobright,
} from "../api/jobright";
import { fetchSettledChatGptSession, signOutChatGpt } from "../api/chatgpt";
import { ProviderConnect } from "../components/ProviderConnect";

interface SettingsPageProps {
  /** Told after a sign-in or sign-out here, so the sidebar dots and the Jobs
   *  banner re-check too — each card already tracks its own status. */
  onProviderSignedOut: () => void;
}

export function SettingsPage({ onProviderSignedOut }: SettingsPageProps) {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const [folderCheck, setFolderCheck] = useState<FolderCheck | null>(null);
  const [saving, setSaving] = useState(false);
  const [selectingFolder, setSelectingFolder] = useState(false);
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
    })();
  }, []);

  const dirty =
    settings !== null && draft !== null && JSON.stringify(settings) !== JSON.stringify(draft);

  // Guard against losing unsaved edits on reload.
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

  const handleSelectFolder = async () => {
    if (!draft) return;
    setSelectingFolder(true);
    setError(null);
    try {
      const selection = await selectFolder(draft.outputFolder);
      if (selection.cancelled) {
        setNotice("Folder selection cancelled.");
        return;
      }
      setFolderCheck(selection);
      if (selection.valid && selection.resolved) {
        update("outputFolder", selection.resolved);
        setNotice("Folder selected and verified. Save settings to keep this change.");
      }
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: { message?: string } } } }).response?.data?.detail
          ?.message;
      setFolderCheck({ valid: false, detail: detail ?? "Could not open the folder picker." });
    } finally {
      setSelectingFolder(false);
    }
  };

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
        <h2>Connections</h2>
        <p className="notice">
          Sign in through your browser — no API keys, and nothing to copy out
          of devtools. Each button opens a tab (in one shared window, if more
          than one is open at once) — sign in there, then come back. Sessions
          expire periodically; reconnect here when they do.
        </p>
        <div className="provider-grid">
          <ProviderConnect
            key="deepseek"
            provider="deepseek"
            label="DeepSeek"
            description="Used for skill extraction and, optionally, resume tailoring."
            fetchSession={fetchSettledSessionStatus}
            signOut={signOutDeepSeek}
            onSignedIn={onProviderSignedOut}
            onSignedOut={onProviderSignedOut}
          />
          <ProviderConnect
            key="jobright"
            provider="jobright"
            label="Jobright"
            description="The job feed that Import Jobs pulls from."
            fetchSession={fetchSettledJobrightSession}
            signOut={signOutJobright}
            onSignedIn={onProviderSignedOut}
            onSignedOut={onProviderSignedOut}
          />
          <ProviderConnect
            key="chatgpt"
            provider="chatgpt"
            label="ChatGPT"
            description="Alternative model for generating tailored resumes and cover letters."
            fetchSession={fetchSettledChatGptSession}
            signOut={signOutChatGpt}
            onSignedIn={onProviderSignedOut}
            onSignedOut={onProviderSignedOut}
          />
        </div>

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
        <h2>Output folder</h2>
        <p className="notice">
          Generated resumes are saved here, in a
          <code> [Profile Name]/[mm-dd-yy]_[Company]_[Job Title]</code> folder
          per job — one top-level folder per profile.
        </p>
        <div className="folder-row">
          <input
            id="output-folder"
            type="text"
            className="folder-input"
            placeholder="No folder selected"
            value={draft.outputFolder}
            readOnly
            aria-label="Output folder path"
            title={draft.outputFolder || "No output folder selected"}
          />
          <button type="button" onClick={handleSelectFolder} disabled={selectingFolder}>
            {selectingFolder ? "Opening…" : "Select folder…"}
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
        <p className="notice">
          Which profile a resume uses — and that profile's own prompts — are
          set on the <strong>Profile</strong> tab.
        </p>
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
