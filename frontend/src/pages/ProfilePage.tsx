/** Resume profile editor.
 *
 *  This is where resume *content* is entered. Template selection and styling
 *  live on the Templates tab and never modify what's here (RG-FR-012).
 */

import { useEffect, useState } from "react";
import {
  createProfile,
  deleteProfile,
  fetchProfileDeletionImpact,
  fetchProfiles,
  updateProfile,
  type ProfileDeletionImpact,
} from "../api/templates";
import { fetchSettings, type AppSettings } from "../api/settings";
import { useActiveProfileSettings } from "../hooks/useActiveProfileSettings";
import { DeleteProfileDialog } from "../components/DeleteProfileDialog";
import { ProfileCorpusEditor } from "../components/ProfileCorpusEditor";
import { PROMPT_DEFS, type PromptKey } from "../resume/promptDefs";
import type {
  Education,
  Profile,
  ProfileInfo,
  ResumeData,
  Skill,
} from "../resume/types";

const PROMPT_KEYS_LIST: PromptKey[] = PROMPT_DEFS.map((def) => def.key);

const EMPTY_DATA: ResumeData = {
  profile: {
    fullName: "", professionalTitle: "", email: "", phone: "", street: "",
    city: "", state: "", postal: "", birthday: "", linkedin: "", website: "",
    summary: "",
  },
  experience: [],
  education: [],
  skills: [],
};

const newId = (prefix: string) =>
  `${prefix}-${Math.random().toString(36).slice(2, 10)}`;

const PERSONAL_FIELDS: { key: keyof ProfileInfo; label: string; placeholder?: string }[] = [
  { key: "fullName", label: "Full name", placeholder: "Alex Chen" },
  { key: "professionalTitle", label: "Professional title", placeholder: "Senior Backend Engineer" },
  { key: "email", label: "Email", placeholder: "alex@example.com" },
  { key: "phone", label: "Phone", placeholder: "(555) 010-4477" },
  { key: "street", label: "Street", placeholder: "128 Harbor Street" },
  { key: "city", label: "City", placeholder: "Austin" },
  { key: "state", label: "State", placeholder: "TX" },
  { key: "postal", label: "Postal code", placeholder: "78701" },
  { key: "birthday", label: "Birthday", placeholder: "1990-05-01" },
  { key: "linkedin", label: "LinkedIn", placeholder: "linkedin.com/in/alexchen" },
  { key: "website", label: "Website", placeholder: "alexchen.dev" },
];

interface ProfilePageProps {
  /** True while this tab is visible; see the note in TemplatesPage. */
  active?: boolean;
  /** Told after the shared active profile changes here (switched, created,
   *  or promoted after a delete), so the always-visible sidebar can update
   *  too -- it can't rely on "refetch when this tab becomes active" the way
   *  every other page does, since it's never inactive. */
  onProfileChanged?: () => void;
}

export function ProfilePage({ active = true, onProfileChanged }: ProfilePageProps) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [draft, setDraft] = useState<ResumeData>(EMPTY_DATA);
  const [saved, setSaved] = useState<ResumeData>(EMPTY_DATA);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<ProfileDeletionImpact | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // This profile's own prompts -- one shared active-profile switch across
  // the whole app, driven by the `resumeProfile` setting Jobs/the tailoring
  // pipeline already read (see useActiveProfileSettings).
  const { switchProfile, patchSettings } = useActiveProfileSettings(active);
  const [promptDraft, setPromptDraft] = useState<AppSettings | null>(null);
  const [promptSaved, setPromptSaved] = useState<AppSettings | null>(null);
  const [selectedPromptKey, setSelectedPromptKey] = useState<PromptKey>("skillsPrompt");
  const [promptSaving, setPromptSaving] = useState(false);
  const [promptError, setPromptError] = useState<string | null>(null);
  const [promptNotice, setPromptNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!active) return;
    (async () => {
      try {
        // Fetched together, and settings read directly here rather than via
        // the hook's own (separately-timed) state: the two requests resolve
        // independently, and seeding activeId from whichever one happened to
        // land first would risk picking the wrong initial profile, with
        // nothing to correct it afterward (activeId is only ever seeded once
        // — see the guard below).
        const [list, initialSettings] = await Promise.all([
          fetchProfiles(),
          fetchSettings().catch(() => null),
        ]);
        setProfiles(list);
        if (initialSettings) {
          setPromptDraft(initialSettings);
          setPromptSaved(initialSettings);
        }
        // Only seed the editor when nothing is open yet — refreshing must never
        // clobber edits in progress. Prefer the shared active profile
        // (resumeProfile) if it still resolves to a real profile, else fall
        // back to the first one — the same fallback the backend itself uses.
        setActiveId((current) => {
          if (current) return current;
          const preferred = initialSettings?.resumeProfile
            ? list.find((p) => p.id === initialSettings.resumeProfile)
            : undefined;
          const initial = preferred ?? list[0];
          if (initial) {
            setDraft(initial.data);
            setSaved(initial.data);
            return initial.id;
          }
          return null;
        });
      } catch {
        setError("Could not load profiles. Is the backend running on port 8000?");
      }
    })();
  }, [active]);

  const selectProfile = async (id: string) => {
    const found = profiles.find((p) => p.id === id);
    if (!found) return;
    setActiveId(id);
    setDraft(found.data);
    setSaved(found.data);
    setNotice(null);
    setPromptError(null);
    setPromptNotice(null);
    try {
      const updated = await switchProfile(id);
      setPromptDraft(updated);
      setPromptSaved(updated);
      onProfileChanged?.();
    } catch {
      setError("Could not switch the active profile.");
    }
  };

  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const setPersonal = (key: keyof ProfileInfo, value: string) =>
    setDraft((prev) => ({ ...prev, profile: { ...prev.profile, [key]: value } }));

  const handleSave = async () => {
    if (!activeId) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await updateProfile(activeId, { data: draft });
      setProfiles((prev) => prev.map((p) => (p.id === activeId ? updated : p)));
      setSaved(updated.data);
      setDraft(updated.data);
      setNotice("Profile saved.");
    } catch {
      setError("Could not save the profile.");
    } finally {
      setSaving(false);
    }
  };

  const handleCreate = async () => {
    const name = window.prompt("Profile name", "My Resume");
    if (!name) return;
    try {
      const created = await createProfile(name);
      setProfiles((prev) => [...prev, created]);
      setActiveId(created.id);
      setDraft(created.data);
      setSaved(created.data);
      // A newly created profile becomes the shared active one too, so Jobs
      // and Templates immediately follow it rather than still pointing at
      // whatever was active before.
      const updated = await switchProfile(created.id);
      setPromptDraft(updated);
      setPromptSaved(updated);
      onProfileChanged?.();
    } catch {
      setError("Could not create the profile.");
    }
  };

  // -- this profile's prompts ----------------------------------------------
  // A separate save flow from "Save profile" above: that one saves resume
  // content (ResumeData) via updateProfile(); this one saves prompt settings
  // (AppSettings) via patchSettings() -- different backend resources,
  // deliberately not conflated into one button/dirty-check.

  const promptDirty =
    promptDraft !== null &&
    promptSaved !== null &&
    JSON.stringify(promptDraft) !== JSON.stringify(promptSaved);

  const selectedPromptDef =
    PROMPT_DEFS.find((def) => def.key === selectedPromptKey) ?? PROMPT_DEFS[0];
  const missingSelectedPlaceholders = (selectedPromptDef.placeholders ?? []).filter(
    (token) => !(promptDraft?.[selectedPromptDef.key] ?? "").includes(`{${token}}`),
  );

  const updatePrompt = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => {
    setPromptDraft((prev) => (prev ? { ...prev, [key]: value } : prev));
    setPromptNotice(null);
  };

  const handleSavePrompts = async () => {
    if (!promptDraft) return;
    setPromptSaving(true);
    setPromptError(null);
    try {
      const patch = {
        ...Object.fromEntries(PROMPT_KEYS_LIST.map((key) => [key, promptDraft[key]])),
        industryWeight: promptDraft.industryWeight,
      } as Partial<AppSettings>;
      const updated = await patchSettings(patch);
      setPromptDraft(updated);
      setPromptSaved(updated);
      setPromptNotice("Saved.");
    } catch {
      setPromptError("Could not save prompts.");
    } finally {
      setPromptSaving(false);
    }
  };

  const handleCancelPrompts = () => {
    setPromptDraft(promptSaved);
    setPromptNotice(null);
  };

  // -- repeatable sections ------------------------------------------------
  // Experience is no longer hand-entered here: extraction (DeepSeek) writes
  // it per job, replacing whatever's here at PDF-generation time -- see
  // build_tailored_data() in tailored_resume_service.py.

  const addEducation = () =>
    setDraft((prev) => ({
      ...prev,
      education: [
        ...prev.education,
        { id: newId("edu"), university: "", degree: "", startYear: "", endYear: "", location: "" },
      ],
    }));

  const updateEducation = (id: string, patch: Partial<Education>) =>
    setDraft((prev) => ({
      ...prev,
      education: prev.education.map((e) => (e.id === id ? { ...e, ...patch } : e)),
    }));

  const removeEducation = (id: string) =>
    setDraft((prev) => ({ ...prev, education: prev.education.filter((e) => e.id !== id) }));

  const addSkill = () =>
    setDraft((prev) => ({
      ...prev,
      skills: [...prev.skills, { id: newId("sk"), name: "", category: "" }],
    }));

  const updateSkill = (id: string, patch: Partial<Skill>) =>
    setDraft((prev) => ({
      ...prev,
      skills: prev.skills.map((s) => (s.id === id ? { ...s, ...patch } : s)),
    }));

  const removeSkill = (id: string) =>
    setDraft((prev) => ({ ...prev, skills: prev.skills.filter((s) => s.id !== id) }));

  const describeError = (err: unknown, fallback: string) =>
    (err as { response?: { data?: { detail?: { message?: string } } } }).response?.data?.detail
      ?.message ?? fallback;

  /** Ask the backend what would be lost before showing the confirmation.
   *  A profile owns its jobs, so this is rarely just "remove a name". */
  const handleAskDelete = async () => {
    if (!activeId) return;
    setDeleteError(null);
    setNotice(null);
    try {
      setPendingDelete(await fetchProfileDeletionImpact(activeId));
    } catch (err) {
      setError(describeError(err, "Could not check what deleting this profile would remove."));
    }
  };

  const handleConfirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      const result = await deleteProfile(pendingDelete.profileId);
      const remaining = profiles.filter((p) => p.id !== result.profileId);
      setProfiles(remaining);
      setPendingDelete(null);
      // Move to whichever profile the backend promoted, else the first left.
      const next = remaining.find((p) => p.id === result.promoted) ?? remaining[0] ?? null;
      if (next) {
        void selectProfile(next.id);
      } else {
        setActiveId(null);
        setDraft(EMPTY_DATA);
        setSaved(EMPTY_DATA);
      }
      const alsoRemoved = [
        result.jobs && `${result.jobs} job${result.jobs === 1 ? "" : "s"}`,
        result.bullets && `${result.bullets} bullets`,
        result.documents && `${result.documents} resume record${result.documents === 1 ? "" : "s"}`,
      ].filter(Boolean);
      setNotice(
        `Deleted “${result.name}”` +
          (alsoRemoved.length ? `, along with ${alsoRemoved.join(", ")}.` : ".") +
          (result.promoted && next ? ` “${next.name}” is now the default.` : ""),
      );
    } catch (err) {
      setDeleteError(describeError(err, "Could not delete the profile."));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="profile-page">
      <div className="templates-toolbar">
        <label htmlFor="profile-editor-select">Profile</label>
        <select
          id="profile-editor-select"
          value={activeId ?? ""}
          onChange={(event) => void selectProfile(event.target.value)}
          disabled={profiles.length === 0}
        >
          {profiles.length === 0 && <option value="">No profiles yet</option>}
          {profiles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <button type="button" onClick={handleCreate}>
          New profile
        </button>
        <button
          type="button"
          className="danger-quiet"
          onClick={handleAskDelete}
          disabled={!activeId || deleting}
          title="Delete this profile and everything belonging to it"
        >
          Delete profile
        </button>
        <div className="templates-actions">
          {dirty && <span className="unsaved-badge">Unsaved changes</span>}
          <button type="button" onClick={() => setDraft(saved)} disabled={!dirty || saving}>
            Cancel
          </button>
          <button type="button" onClick={handleSave} disabled={!activeId || !dirty || saving}>
            {saving ? "Saving…" : "Save profile"}
          </button>
        </div>
      </div>

      <DeleteProfileDialog
        impact={pendingDelete}
        busy={deleting}
        error={deleteError}
        onConfirm={handleConfirmDelete}
        onCancel={() => {
          setPendingDelete(null);
          setDeleteError(null);
        }}
      />

      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      {!activeId && <p className="notice">Create a profile to start entering resume content.</p>}

      {activeId && (
        <>
          <section className="settings-section">
            <h2>Personal information</h2>
            <div className="field-grid">
              {PERSONAL_FIELDS.map((field) => (
                <div key={field.key} className="field">
                  <label htmlFor={`pi-${field.key}`}>{field.label}</label>
                  <input
                    id={`pi-${field.key}`}
                    type="text"
                    placeholder={field.placeholder}
                    value={draft.profile[field.key]}
                    onChange={(event) => setPersonal(field.key, event.target.value)}
                  />
                </div>
              ))}
            </div>
          </section>

          <section className="settings-section">
            <h2>
              Education <button type="button" onClick={addEducation}>+ Add</button>
            </h2>
            {draft.education.length === 0 && <p className="notice">No education entries yet.</p>}
            {draft.education.map((entry) => (
              <div key={entry.id} className="entry-card">
                <div className="field-grid">
                  <div className="field">
                    <label htmlFor={`edu-uni-${entry.id}`}>University</label>
                    <input
                      id={`edu-uni-${entry.id}`}
                      value={entry.university}
                      onChange={(e) => updateEducation(entry.id, { university: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`edu-deg-${entry.id}`}>Degree</label>
                    <input
                      id={`edu-deg-${entry.id}`}
                      value={entry.degree}
                      onChange={(e) => updateEducation(entry.id, { degree: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`edu-start-${entry.id}`}>Start year</label>
                    <input
                      id={`edu-start-${entry.id}`}
                      placeholder="2013"
                      value={entry.startYear}
                      onChange={(e) => updateEducation(entry.id, { startYear: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`edu-end-${entry.id}`}>End year</label>
                    <input
                      id={`edu-end-${entry.id}`}
                      placeholder="2017"
                      value={entry.endYear}
                      onChange={(e) => updateEducation(entry.id, { endYear: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`edu-loc-${entry.id}`}>Location</label>
                    <input
                      id={`edu-loc-${entry.id}`}
                      value={entry.location}
                      onChange={(e) => updateEducation(entry.id, { location: e.target.value })}
                    />
                  </div>
                </div>
                <button type="button" className="remove-button" onClick={() => removeEducation(entry.id)}>
                  Remove
                </button>
              </div>
            ))}
          </section>

          <section className="settings-section">
            <h2>
              Skills <button type="button" onClick={addSkill}>+ Add</button>
            </h2>
            {draft.skills.length === 0 && <p className="notice">No skills yet.</p>}
            {draft.skills.map((skill) => (
              <div key={skill.id} className="skill-row">
                <input
                  aria-label="Skill name"
                  placeholder="Python"
                  value={skill.name}
                  onChange={(e) => updateSkill(skill.id, { name: e.target.value })}
                />
                <input
                  aria-label="Skill category"
                  placeholder="Languages (optional)"
                  value={skill.category}
                  onChange={(e) => updateSkill(skill.id, { category: e.target.value })}
                />
                <button type="button" className="remove-button" onClick={() => removeSkill(skill.id)}>
                  Remove
                </button>
              </div>
            ))}
          </section>

          <section className="settings-section">
            <h2>Prompts &amp; search tuning</h2>
            <p className="notice">
              This profile's own prompts — customizing one here only affects
              resumes tailored under <strong>{profiles.find((p) => p.id === activeId)?.name}</strong>,
              not your other profiles. The first six run as turns in a{" "}
              <strong>single DeepSeek chat</strong> for one job, ending with
              the skill set once the bullets, summary, and title all exist.
              The seventh and eighth run once more, as two messages in the
              same fresh <strong>ChatGPT chat</strong>: first revising the
              bullets, company summaries, and overall summary DeepSeek just
              wrote, then marking the main keywords in that revised text. The
              last is separate — it builds this profile's career database
              rather than tailoring a resume.
            </p>

            {promptError && <p className="error">{promptError}</p>}
            {promptNotice && <p className="notice">{promptNotice}</p>}

            {promptDraft && (
              <div className="prompt-section">
                <label className="weight-slider" htmlFor="profile-industry-weight">
                  Industry weight in search: {Math.round(Number(promptDraft.industryWeight) * 100)}%
                  <input
                    id="profile-industry-weight"
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={promptDraft.industryWeight}
                    onChange={(event) => updatePrompt("industryWeight", event.target.value)}
                  />
                </label>
                <p className="notice">
                  How much a challenge's industry similarity to this job
                  counts toward which experience gets picked for Job 1 and
                  Job 2 — 0% ignores industry entirely; 100% lets it dominate
                  over the actual skills/challenge-text match.
                </p>

                <label htmlFor="profile-prompt-select">Prompt to edit</label>
                <select
                  id="profile-prompt-select"
                  className="prompt-select"
                  value={selectedPromptDef.key}
                  onChange={(event) => setSelectedPromptKey(event.target.value as PromptKey)}
                >
                  {PROMPT_DEFS.map((def) => (
                    <option key={def.key} value={def.key}>
                      {def.label}
                    </option>
                  ))}
                </select>

                <p className="notice">{selectedPromptDef.description}</p>

                <textarea
                  id="profile-prompt-textarea"
                  className="prompt-textarea"
                  rows={selectedPromptDef.rows}
                  value={promptDraft[selectedPromptDef.key]}
                  onChange={(event) => updatePrompt(selectedPromptDef.key, event.target.value)}
                />
                {missingSelectedPlaceholders.length > 0 && (
                  <p className="notice exp-warn">
                    Missing {missingSelectedPlaceholders.map((t) => `{${t}}`).join(", ")}{" "}
                    — the model won't receive that context.
                  </p>
                )}

                <div className="settings-actions">
                  {promptDirty && <span className="unsaved-badge">Unsaved changes</span>}
                  <button
                    type="button"
                    onClick={handleCancelPrompts}
                    disabled={!promptDirty || promptSaving}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleSavePrompts()}
                    disabled={!promptDirty || promptSaving}
                  >
                    {promptSaving ? "Saving…" : "Save"}
                  </button>
                </div>
              </div>
            )}
          </section>

          <ProfileCorpusEditor
            profileId={activeId}
            profileName={profiles.find((p) => p.id === activeId)?.name ?? ""}
          />
        </>
      )}
    </div>
  );
}
