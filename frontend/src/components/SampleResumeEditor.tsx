/** Edits the sample resume shown in Templates/Builder pages' preview.
 *
 *  Mirrors the personal-info/education/skills editing already on Profile
 *  page, plus Summary and Experience -- both dropped from Profile page since
 *  DeepSeek generates them per job now, but the sample resume needs them:
 *  it exists to exercise every section a template can have, not to
 *  represent one real candidate.
 */

import { useEffect, useState } from "react";
import { saveSampleResume, resetSampleResume } from "../api/templates";
import type { Education, Experience, ProfileInfo, ResumeData, Skill } from "../resume/types";

const newId = (prefix: string) => `${prefix}-${Math.random().toString(36).slice(2, 10)}`;

const PERSONAL_FIELDS: { key: keyof ProfileInfo; label: string }[] = [
  { key: "fullName", label: "Full name" },
  { key: "professionalTitle", label: "Professional title" },
  { key: "email", label: "Email" },
  { key: "phone", label: "Phone" },
  { key: "street", label: "Street" },
  { key: "city", label: "City" },
  { key: "state", label: "State" },
  { key: "postal", label: "Postal code" },
  { key: "birthday", label: "Birthday" },
  { key: "linkedin", label: "LinkedIn" },
  { key: "website", label: "Website" },
];

interface SampleResumeEditorProps {
  open: boolean;
  initialData: ResumeData | null;
  onClose: () => void;
  /** Told after a successful save or reset, so the page's own preview
   *  updates without a second fetch. */
  onSaved: (data: ResumeData) => void;
}

export function SampleResumeEditor({ open, initialData, onClose, onSaved }: SampleResumeEditorProps) {
  const [draft, setDraft] = useState<ResumeData | null>(null);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Re-seed from whatever the page currently has each time the modal opens,
  // not on every parent re-render -- edits here are local until Save.
  useEffect(() => {
    if (open) {
      setDraft(initialData ? structuredClone(initialData) : null);
      setError(null);
    }
  }, [open, initialData]);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open || !draft) return null;

  const setPersonal = (key: keyof ProfileInfo, value: string) =>
    setDraft((prev) => (prev ? { ...prev, profile: { ...prev.profile, [key]: value } } : prev));

  const addExperience = () =>
    setDraft((prev) =>
      prev
        ? {
            ...prev,
            experience: [
              ...prev.experience,
              {
                id: newId("exp"), company: "", title: "", location: "",
                startDate: "", endDate: "", current: false, companySummary: "", description: "",
              },
            ],
          }
        : prev,
    );

  const updateExperience = (id: string, patch: Partial<Experience>) =>
    setDraft((prev) =>
      prev
        ? { ...prev, experience: prev.experience.map((e) => (e.id === id ? { ...e, ...patch } : e)) }
        : prev,
    );

  const removeExperience = (id: string) =>
    setDraft((prev) => (prev ? { ...prev, experience: prev.experience.filter((e) => e.id !== id) } : prev));

  const addEducation = () =>
    setDraft((prev) =>
      prev
        ? {
            ...prev,
            education: [
              ...prev.education,
              { id: newId("edu"), university: "", degree: "", startYear: "", endYear: "", location: "" },
            ],
          }
        : prev,
    );

  const updateEducation = (id: string, patch: Partial<Education>) =>
    setDraft((prev) =>
      prev
        ? { ...prev, education: prev.education.map((e) => (e.id === id ? { ...e, ...patch } : e)) }
        : prev,
    );

  const removeEducation = (id: string) =>
    setDraft((prev) => (prev ? { ...prev, education: prev.education.filter((e) => e.id !== id) } : prev));

  const addSkill = () =>
    setDraft((prev) =>
      prev ? { ...prev, skills: [...prev.skills, { id: newId("sk"), name: "", category: "" }] } : prev,
    );

  const updateSkill = (id: string, patch: Partial<Skill>) =>
    setDraft((prev) =>
      prev ? { ...prev, skills: prev.skills.map((s) => (s.id === id ? { ...s, ...patch } : s)) } : prev,
    );

  const removeSkill = (id: string) =>
    setDraft((prev) => (prev ? { ...prev, skills: prev.skills.filter((s) => s.id !== id) } : prev));

  const handleSave = async () => {
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      const result = await saveSampleResume(draft);
      onSaved(result);
      onClose();
    } catch {
      setError("Could not save the sample resume.");
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    if (!window.confirm("Reset the sample resume to the built-in default? This discards your customization."))
      return;
    setResetting(true);
    setError(null);
    try {
      const result = await resetSampleResume();
      setDraft(structuredClone(result));
      onSaved(result);
    } catch {
      setError("Could not reset the sample resume.");
    } finally {
      setResetting(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-content sample-resume-modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2>Edit sample data</h2>
            <p className="modal-subtitle">
              Shown in the Templates and Builder previews — never a real profile's.
            </p>
          </div>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
            &times;
          </button>
        </div>

        <div className="modal-body">
          {error && <p className="error">{error}</p>}

          <section className="settings-section">
            <h2>Personal information</h2>
            <div className="field-grid">
              {PERSONAL_FIELDS.map((field) => (
                <div key={field.key} className="field">
                  <label htmlFor={`sr-${field.key}`}>{field.label}</label>
                  <input
                    id={`sr-${field.key}`}
                    type="text"
                    value={draft.profile[field.key]}
                    onChange={(event) => setPersonal(field.key, event.target.value)}
                  />
                </div>
              ))}
            </div>
            <div className="prompt-section">
              <label htmlFor="sr-summary">Summary</label>
              <textarea
                id="sr-summary"
                className="prompt-textarea"
                rows={4}
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
                    <label htmlFor={`sr-exp-title-${entry.id}`}>Job title</label>
                    <input
                      id={`sr-exp-title-${entry.id}`}
                      value={entry.title}
                      onChange={(e) => updateExperience(entry.id, { title: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`sr-exp-company-${entry.id}`}>Company</label>
                    <input
                      id={`sr-exp-company-${entry.id}`}
                      value={entry.company}
                      onChange={(e) => updateExperience(entry.id, { company: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`sr-exp-loc-${entry.id}`}>Location</label>
                    <input
                      id={`sr-exp-loc-${entry.id}`}
                      value={entry.location}
                      onChange={(e) => updateExperience(entry.id, { location: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`sr-exp-start-${entry.id}`}>Start</label>
                    <input
                      id={`sr-exp-start-${entry.id}`}
                      placeholder="Mar 2021"
                      value={entry.startDate}
                      onChange={(e) => updateExperience(entry.id, { startDate: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`sr-exp-end-${entry.id}`}>End</label>
                    <input
                      id={`sr-exp-end-${entry.id}`}
                      placeholder="Feb 2024"
                      disabled={entry.current}
                      value={entry.endDate}
                      onChange={(e) => updateExperience(entry.id, { endDate: e.target.value })}
                    />
                  </div>
                  <div className="field field--inline">
                    <label htmlFor={`sr-exp-current-${entry.id}`}>Current role</label>
                    <input
                      id={`sr-exp-current-${entry.id}`}
                      type="checkbox"
                      checked={entry.current}
                      onChange={(e) => updateExperience(entry.id, { current: e.target.checked })}
                    />
                  </div>
                </div>
                <div className="prompt-section">
                  <label htmlFor={`sr-exp-company-summary-${entry.id}`}>Company summary</label>
                  <textarea
                    id={`sr-exp-company-summary-${entry.id}`}
                    className="prompt-textarea"
                    rows={2}
                    value={entry.companySummary}
                    onChange={(e) => updateExperience(entry.id, { companySummary: e.target.value })}
                  />
                </div>
                <div className="prompt-section">
                  <label htmlFor={`sr-exp-desc-${entry.id}`}>Description — one bullet per line</label>
                  <textarea
                    id={`sr-exp-desc-${entry.id}`}
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
                    <label htmlFor={`sr-edu-uni-${entry.id}`}>University</label>
                    <input
                      id={`sr-edu-uni-${entry.id}`}
                      value={entry.university}
                      onChange={(e) => updateEducation(entry.id, { university: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`sr-edu-deg-${entry.id}`}>Degree</label>
                    <input
                      id={`sr-edu-deg-${entry.id}`}
                      value={entry.degree}
                      onChange={(e) => updateEducation(entry.id, { degree: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`sr-edu-start-${entry.id}`}>Start year</label>
                    <input
                      id={`sr-edu-start-${entry.id}`}
                      placeholder="2013"
                      value={entry.startYear}
                      onChange={(e) => updateEducation(entry.id, { startYear: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`sr-edu-end-${entry.id}`}>End year</label>
                    <input
                      id={`sr-edu-end-${entry.id}`}
                      placeholder="2017"
                      value={entry.endYear}
                      onChange={(e) => updateEducation(entry.id, { endYear: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`sr-edu-loc-${entry.id}`}>Location</label>
                    <input
                      id={`sr-edu-loc-${entry.id}`}
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
        </div>

        <div className="settings-actions">
          <button
            type="button"
            className="danger-quiet"
            onClick={() => void handleReset()}
            disabled={saving || resetting}
          >
            {resetting ? "Resetting…" : "Reset to default"}
          </button>
          <button type="button" onClick={onClose} disabled={saving || resetting}>
            Cancel
          </button>
          <button
            type="button"
            className="primary"
            onClick={() => void handleSave()}
            disabled={saving || resetting}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
