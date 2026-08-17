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
import { ProviderConnect } from "../components/ProviderConnect";

export function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const [folderCheck, setFolderCheck] = useState<FolderCheck | null>(null);
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
    })();
  }, []);

  const dirty =
    settings !== null && draft !== null && JSON.stringify(settings) !== JSON.stringify(draft);

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
            label="DeepSeek"
            description="Used for skill extraction and, optionally, resume tailoring."
            fetchSession={fetchSessionStatus}
            startLogin={startLogin}
            fetchLoginStatus={fetchLoginStatus}
          />
          <ProviderConnect
            label="ChatGPT"
            description="Alternative model for generating tailored resumes and cover letters."
            fetchSession={fetchChatGptSession}
            startLogin={startChatGptLogin}
            fetchLoginStatus={fetchChatGptLoginStatus}
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
          Generated resumes and cover letters are saved here, in a
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
      </section>

      <section className="settings-section">
        <h2>Prompts</h2>
        <div className="prompt-section">
          <label htmlFor="settings-skills-prompt">Skill extraction prompt</label>
          <textarea
            id="settings-skills-prompt"
            className="prompt-textarea"
            rows={6}
            value={draft.skillsPrompt}
            onChange={(event) => update("skillsPrompt", event.target.value)}
          />
        </div>
        <div className="prompt-section">
          <label htmlFor="settings-tailoring-prompt">Resume tailoring prompt</label>
          <textarea
            id="settings-tailoring-prompt"
            className="prompt-textarea"
            rows={10}
            value={draft.tailoringPrompt}
            onChange={(event) => update("tailoringPrompt", event.target.value)}
          />
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
