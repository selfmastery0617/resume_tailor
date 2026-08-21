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
import { DeleteProfileDialog } from "../components/DeleteProfileDialog";
import { ProfileCorpusEditor } from "../components/ProfileCorpusEditor";
import type {
  Education,
  Experience,
  Profile,
  ProfileInfo,
  ResumeData,
  Skill,
} from "../resume/types";

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

/** True once there's enough content for a resume to be worth rendering. */
export function profileHasContent(data: ResumeData | undefined): boolean {
  if (!data) return false;
  return Boolean(
    data.profile.fullName.trim() ||
      data.profile.summary.trim() ||
      data.experience.length ||
      data.education.length ||
      data.skills.length,
  );
}

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
}

export function ProfilePage({ active = true }: ProfilePageProps) {
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

  useEffect(() => {
    if (!active) return;
    (async () => {
      try {
        const list = await fetchProfiles();
        setProfiles(list);
        // Only seed the editor when nothing is open yet — refreshing must never
        // clobber edits in progress.
        setActiveId((current) => {
          if (current) return current;
          if (list.length) {
            setDraft(list[0].data);
            setSaved(list[0].data);
            return list[0].id;
          }
          return null;
        });
      } catch {
        setError("Could not load profiles. Is the backend running on port 8000?");
      }
    })();
  }, [active]);

  const selectProfile = (id: string) => {
    const found = profiles.find((p) => p.id === id);
    if (!found) return;
    setActiveId(id);
    setDraft(found.data);
    setSaved(found.data);
    setNotice(null);
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
    } catch {
      setError("Could not create the profile.");
    }
  };

  // -- repeatable sections ------------------------------------------------

  const addExperience = () =>
    setDraft((prev) => ({
      ...prev,
      experience: [
        ...prev.experience,
        {
          id: newId("exp"), company: "", title: "", location: "",
          startDate: "", endDate: "", current: false, companySummary: "", description: "",
        },
      ],
    }));

  const updateExperience = (id: string, patch: Partial<Experience>) =>
    setDraft((prev) => ({
      ...prev,
      experience: prev.experience.map((e) => (e.id === id ? { ...e, ...patch } : e)),
    }));

  const removeExperience = (id: string) =>
    setDraft((prev) => ({ ...prev, experience: prev.experience.filter((e) => e.id !== id) }));

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
        selectProfile(next.id);
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
          onChange={(event) => selectProfile(event.target.value)}
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
            <div className="prompt-section">
              <label htmlFor="pi-summary">Summary</label>
              <textarea
                id="pi-summary"
                className="prompt-textarea"
                rows={4}
                placeholder="Backend engineer with 8 years building distributed services…"
                value={draft.profile.summary}
                onChange={(event) => setPersonal("summary", event.target.value)}
              />
            </div>
          </section>

          <section className="settings-section">
            <h2>
              Experience <button type="button" onClick={addExperience}>+ Add</button>
            </h2>
            {draft.experience.length === 0 && <p className="notice">No experience entries yet.</p>}
            {draft.experience.map((entry) => (
              <div key={entry.id} className="entry-card">
                <div className="field-grid">
                  <div className="field">
                    <label htmlFor={`exp-title-${entry.id}`}>Job title</label>
                    <input
                      id={`exp-title-${entry.id}`}
                      value={entry.title}
                      onChange={(e) => updateExperience(entry.id, { title: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`exp-company-${entry.id}`}>Company</label>
                    <input
                      id={`exp-company-${entry.id}`}
                      value={entry.company}
                      onChange={(e) => updateExperience(entry.id, { company: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`exp-loc-${entry.id}`}>Location</label>
                    <input
                      id={`exp-loc-${entry.id}`}
                      value={entry.location}
                      onChange={(e) => updateExperience(entry.id, { location: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`exp-start-${entry.id}`}>Start</label>
                    <input
                      id={`exp-start-${entry.id}`}
                      placeholder="Mar 2021"
                      value={entry.startDate}
                      onChange={(e) => updateExperience(entry.id, { startDate: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`exp-end-${entry.id}`}>End</label>
                    <input
                      id={`exp-end-${entry.id}`}
                      placeholder="Feb 2024"
                      disabled={entry.current}
                      value={entry.endDate}
                      onChange={(e) => updateExperience(entry.id, { endDate: e.target.value })}
                    />
                  </div>
                  <div className="field field--inline">
                    <label htmlFor={`exp-current-${entry.id}`}>Current role</label>
                    <input
                      id={`exp-current-${entry.id}`}
                      type="checkbox"
                      checked={entry.current}
                      onChange={(e) => updateExperience(entry.id, { current: e.target.checked })}
                    />
                  </div>
                </div>
                <div className="prompt-section">
                  <label htmlFor={`exp-company-summary-${entry.id}`}>Company summary</label>
                  <textarea
                    id={`exp-company-summary-${entry.id}`}
                    className="prompt-textarea"
                    rows={3}
                    placeholder="Briefly describe the company, product, or organization."
                    value={entry.companySummary}
                    onChange={(e) =>
                      updateExperience(entry.id, { companySummary: e.target.value })
                    }
                  />
                </div>
                <div className="prompt-section">
                  <label htmlFor={`exp-desc-${entry.id}`}>
                    Description — one bullet per line
                  </label>
                  <textarea
                    id={`exp-desc-${entry.id}`}
                    className="prompt-textarea"
                    rows={4}
                    value={entry.description}
                    onChange={(e) => updateExperience(entry.id, { description: e.target.value })}
                  />
                </div>
                <button type="button" className="remove-button" onClick={() => removeExperience(entry.id)}>
                  Remove
                </button>
              </div>
            ))}
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
          <ProfileCorpusEditor
            profileId={activeId}
            profileName={profiles.find((p) => p.id === activeId)?.name ?? ""}
          />
        </>
      )}
    </div>
  );
}
