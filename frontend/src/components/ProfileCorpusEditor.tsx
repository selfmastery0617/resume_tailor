/** One profile's career corpus.
 *
 *  Each profile owns its own database.json — the companies, products, projects
 *  and challenges that extraction ranks against. It lives here rather than on
 *  Settings because it belongs to a resume identity, not to the account.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchDatabaseExample,
  fetchExperienceDatabase,
  saveExperienceDatabase,
  type DatabaseInfo,
} from "../api/experience";
import { fetchSettings, saveSettings } from "../api/settings";

interface ProfileCorpusEditorProps {
  profileId: string | null;
  profileName: string;
}

export function ProfileCorpusEditor({ profileId, profileName }: ProfileCorpusEditorProps) {
  const [info, setInfo] = useState<DatabaseInfo | null>(null);
  const [text, setText] = useState("");
  const [firstCompany, setFirstCompany] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    if (!profileId) return;
    setError(null);
    setNotice(null);
    try {
      const loaded = await fetchExperienceDatabase(profileId);
      setInfo(loaded);
      setText(loaded.text);
      if (!loaded.valid && loaded.detail) setError(loaded.detail);
    } catch {
      setError("Could not load this profile's database.json.");
    }
    try {
      setFirstCompany((await fetchSettings()).firstCompany);
    } catch {
      /* the dropdown just starts empty */
    }
  }, [profileId]);

  // Switching profile must swap the document, not leave the previous one on
  // screen where it could be saved onto the wrong profile.
  useEffect(() => {
    setInfo(null);
    setText("");
    void load();
  }, [load]);

  const dirty = info !== null && text !== info.text;

  const handleSave = async () => {
    if (!profileId) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const { companies } = await saveExperienceDatabase(text, profileId);
      setInfo((prev) =>
        prev ? { ...prev, companies, text, exists: true, valid: true, detail: null } : prev,
      );
      setNotice(`Saved. ${companies.length} companies available to this profile.`);
      // A saved edit can remove the selected company; clearing it here beats
      // failing at extraction time with a company that no longer exists.
      if (firstCompany && !companies.includes(firstCompany)) {
        await saveSettings({ firstCompany: "" });
        setFirstCompany("");
        setNotice(`Saved. "${firstCompany}" no longer exists, so First Company was cleared.`);
      }
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: { message?: string } } } })
        .response?.data?.detail?.message;
      setError(detail ?? "Could not save database.json.");
    } finally {
      setSaving(false);
    }
  };

  const handleUpload = async (file: File) => {
    setText(await file.text());
    setNotice(`Loaded ${file.name}. Review it, then save.`);
  };

  const handleExample = async () => {
    setText(await fetchDatabaseExample());
    setNotice("Example loaded. Replace it with your own history, then save.");
  };

  const handleFirstCompany = async (value: string) => {
    setFirstCompany(value);
    setError(null);
    try {
      await saveSettings({ firstCompany: value });
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: { message?: string } } } })
        .response?.data?.detail?.message;
      setError(detail ?? "Could not save the first company.");
    }
  };

  if (!profileId) return null;

  const companies = info?.companies ?? [];

  return (
    <section className="settings-section">
      <h2>Experience database</h2>
      <p className="notice">
        The career history <strong>{profileName}</strong> draws on: Company →
        Product → Projects → Challenges. Each profile has its own, so editing
        this one leaves your other profiles alone.
      </p>

      {info && !info.exists && (
        <p className="notice exp-warn">
          This profile has no database.json yet — extraction will refuse to run.
          Upload one, or start from the example.
        </p>
      )}

      <div className="style-row" style={{ maxWidth: 520 }}>
        <label htmlFor="first-company" className="style-label">
          First Company (Job 1)
        </label>
        <div className="style-control">
          <select
            id="first-company"
            value={firstCompany}
            onChange={(event) => void handleFirstCompany(event.target.value)}
            disabled={!companies.length}
          >
            <option value="">— none selected —</option>
            {companies.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
      </div>
      {info?.exists && !firstCompany && (
        <p className="notice exp-warn">
          No first company selected — extraction will refuse to run.
        </p>
      )}

      <div className="prompt-section">
        <label htmlFor="database-json">database.json</label>
        <textarea
          id="database-json"
          className="prompt-textarea db-editor"
          rows={16}
          spellCheck={false}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setNotice(null);
          }}
          placeholder="Paste this profile's career history as JSON, or upload a file."
        />
      </div>

      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}

      <div className="corpus-actions">
        <input
          ref={fileInput}
          type="file"
          accept="application/json,.json"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void handleUpload(file);
            // Reset, so choosing the same file twice fires again.
            event.target.value = "";
          }}
        />
        <button type="button" onClick={() => fileInput.current?.click()}>
          Upload database.json
        </button>
        <button type="button" onClick={() => void handleExample()}>
          Load example
        </button>
        <span className="corpus-path" title={info?.path}>
          {info?.exists ? info.path : "not saved yet"}
        </span>
        {dirty && <span className="unsaved-badge">Unsaved changes</span>}
        <button type="button" className="primary" onClick={handleSave} disabled={saving || !dirty}>
          {saving ? "Saving…" : "Save database.json"}
        </button>
      </div>
    </section>
  );
}
