/** Template browsing and preview (US-TM-01, US-TM-02).
 *
 *  Selecting a template only changes the preview — it never touches resume
 *  content, and nothing is written to the server until Save is pressed
 *  (TM-FR-013).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createProfile,
  downloadResumePdf,
  fetchProfiles,
  fetchTemplateSettings,
  fetchTemplates,
  resetTemplateSettings,
  saveTemplateSettings,
} from "../api/templates";
import { ResumePreview } from "../components/ResumePreview";
import { StyleEditor } from "../components/StyleEditor";
import { SAMPLE_RESUME } from "../resume/sampleData";
import type {
  Profile,
  ProfileTemplateSettings,
  ResumeStyle,
  TemplateDefinition,
} from "../resume/types";

const DEFAULT_TEMPLATE_ID = "template-1";

function hasResumeContent(profile: Profile | null): boolean {
  if (!profile) return false;
  const { profile: info, experience, education, skills } = profile.data;
  return Boolean(
    info.fullName || info.summary || experience.length || education.length || skills.length,
  );
}

interface TemplatesPageProps {
  /** True while this tab is visible. Pages stay mounted to preserve unsaved
   *  edits, so they must refresh on activation or they show stale data —
   *  e.g. a profile created on the Profile tab. */
  active?: boolean;
}

export function TemplatesPage({ active = true }: TemplatesPageProps) {
  const [templates, setTemplates] = useState<TemplateDefinition[]>([]);
  const [systemDefaultStyle, setSystemDefaultStyle] = useState<ResumeStyle | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [activeProfileId, setActiveProfileId] = useState<string | null>(null);
  const [settings, setSettings] = useState<ProfileTemplateSettings | null>(null);

  // Selection and style edits are local until saved, so browsing and tweaking
  // never write to the profile (TM-FR-013).
  const [selectedTemplateId, setSelectedTemplateId] = useState(DEFAULT_TEMPLATE_ID);
  const [draftOverrides, setDraftOverrides] = useState<Partial<ResumeStyle>>({});
  const [useSample, setUseSample] = useState(false);
  const [showStyleEditor, setShowStyleEditor] = useState(true);
  const [showTemplateList, setShowTemplateList] = useState(true);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const activeProfile = profiles.find((p) => p.id === activeProfileId) ?? null;

  // ---- initial load -----------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [catalog, profileList] = await Promise.all([fetchTemplates(), fetchProfiles()]);
        if (cancelled) return;
        setTemplates(catalog.templates);
        setSystemDefaultStyle(catalog.systemDefaultStyle);
        setProfiles(profileList);
        setActiveProfileId(profileList[0]?.id ?? null);
        // No profile yet -> sample mode is the only thing we can show.
        if (profileList.length === 0) setUseSample(true);
      } catch {
        if (!cancelled) setError("Could not load templates. Is the backend running on port 8000?");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Re-read profiles whenever this tab is shown, so content entered on the
  // Profile tab appears here without a page reload.
  useEffect(() => {
    if (!active) return;
    (async () => {
      try {
        const list = await fetchProfiles();
        setProfiles(list);
        setActiveProfileId((current) =>
          current && list.some((p) => p.id === current) ? current : (list[0]?.id ?? null),
        );
      } catch {
        /* leave the existing list in place on a transient failure */
      }
    })();
  }, [active]);

  // ---- load the active profile's saved template -------------------------
  const loadSettings = useCallback(async (profileId: string) => {
    try {
      const saved = await fetchTemplateSettings(profileId);
      setSettings(saved);
      setSelectedTemplateId(saved.templateId);
      setDraftOverrides(saved.styleOverrides ?? {});
    } catch {
      setError("Could not load this profile's template settings.");
    }
  }, []);

  useEffect(() => {
    if (activeProfileId) void loadSettings(activeProfileId);
  }, [activeProfileId, loadSettings]);

  const selectedTemplate = useMemo(
    () => templates.find((t) => t.id === selectedTemplateId) ?? null,
    [templates, selectedTemplateId],
  );

  // Same precedence the server uses (§4.6):
  //   system defaults -> template defaults -> profile overrides
  // Rebuilt from the *currently previewed* template, so switching templates
  // shows that template's defaults rather than the saved one's merged style.
  // Works with no profile at all, which is what sample mode needs.
  const effectiveStyle = useMemo<ResumeStyle | null>(() => {
    if (!systemDefaultStyle || !selectedTemplate) return null;
    return {
      ...systemDefaultStyle,
      ...(selectedTemplate.defaultStyle as Partial<ResumeStyle>),
      ...draftOverrides,
    } as ResumeStyle;
  }, [systemDefaultStyle, selectedTemplate, draftOverrides]);

  const showingSample = useSample || !hasResumeContent(activeProfile);
  const previewData = showingSample ? SAMPLE_RESUME : (activeProfile?.data ?? SAMPLE_RESUME);

  const dirty =
    settings !== null &&
    (settings.templateId !== selectedTemplateId ||
      JSON.stringify(settings.styleOverrides ?? {}) !== JSON.stringify(draftOverrides));

  // TM-FR-014: don't let a reload silently discard unsaved style work.
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // ---- style editing ----------------------------------------------------
  const handleStyleChange = (field: keyof ResumeStyle, value: unknown) => {
    setDraftOverrides((prev) => ({ ...prev, [field]: value }));
    setNotice(null);
  };

  /** Removing the key restores inheritance rather than pinning the current
   *  default into the profile (§4.5). */
  const handleResetField = (field: keyof ResumeStyle) => {
    setDraftOverrides((prev) => {
      const next = { ...prev };
      delete next[field];
      return next;
    });
  };

  const handleResetGroup = (fields: (keyof ResumeStyle)[]) => {
    setDraftOverrides((prev) => {
      const next = { ...prev };
      for (const field of fields) delete next[field];
      return next;
    });
  };

  // ---- actions ----------------------------------------------------------
  const handleSave = async () => {
    if (!activeProfileId || !settings) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await saveTemplateSettings(
        activeProfileId,
        selectedTemplateId,
        draftOverrides,
      );
      setSettings(saved);
      setDraftOverrides(saved.styleOverrides ?? {});
      setNotice("Template and style saved to this profile.");
    } catch {
      setError("Could not save. Check that the style values are valid.");
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    if (!settings) return;
    setSelectedTemplateId(settings.templateId);
    setDraftOverrides(settings.styleOverrides ?? {});
    setNotice(null);
  };

  const handleResetAll = async () => {
    if (!activeProfileId) return;
    setSaving(true);
    try {
      const reset = await resetTemplateSettings(activeProfileId);
      setSettings(reset);
      setSelectedTemplateId(reset.templateId);
      setDraftOverrides(reset.styleOverrides ?? {});
      setNotice("Template and style reset to defaults.");
    } catch {
      setError("Could not reset the template.");
    } finally {
      setSaving(false);
    }
  };

  const handleDownloadPdf = async () => {
    if (!activeProfileId) return;
    setGenerating(true);
    setError(null);
    setNotice("Generating PDF…");
    try {
      // Draft overrides are sent as one-time generation overrides, so the PDF
      // matches what's on screen even before Save (RG-FR-001 / 7.6).
      await downloadResumePdf(activeProfileId, selectedTemplateId, draftOverrides);
      setNotice("PDF downloaded.");
    } catch {
      setError("PDF generation failed. Check the backend logs and try again.");
      setNotice(null);
    } finally {
      setGenerating(false);
    }
  };

  const handleCreateProfile = async () => {
    const name = window.prompt("Profile name", "My Resume");
    if (!name) return;
    try {
      const created = await createProfile(name);
      setProfiles((prev) => [...prev, created]);
      setActiveProfileId(created.id);
      setUseSample(false);
    } catch {
      setError("Could not create the profile.");
    }
  };

  if (loading) return <p>Loading templates…</p>;

  return (
    <div className="templates-page">
      <div className="templates-toolbar">
        <label htmlFor="profile-select">Profile</label>
        <select
          id="profile-select"
          value={activeProfileId ?? ""}
          onChange={(event) => setActiveProfileId(event.target.value || null)}
          disabled={profiles.length === 0}
        >
          {profiles.length === 0 && <option value="">No profiles yet</option>}
          {profiles.map((profile) => (
            <option key={profile.id} value={profile.id}>
              {profile.name}
            </option>
          ))}
        </select>
        <button type="button" onClick={handleCreateProfile}>
          New profile
        </button>

        <label className="sample-toggle">
          <input
            type="checkbox"
            checked={showingSample}
            disabled={!hasResumeContent(activeProfile)}
            onChange={(event) => setUseSample(event.target.checked)}
          />
          Use sample data
        </label>

        <div className="templates-actions">
          {/* Both panels collapse so the preview can use the full width. */}
          <button
            type="button"
            className="panel-toggle"
            aria-pressed={showTemplateList}
            onClick={() => setShowTemplateList((v) => !v)}
          >
            {showTemplateList ? "◀ Templates" : "▶ Templates"}
          </button>
          <button
            type="button"
            className="panel-toggle"
            aria-pressed={showStyleEditor}
            onClick={() => setShowStyleEditor((v) => !v)}
          >
            {showStyleEditor ? "Style ▶" : "Style ◀"}
          </button>
          {dirty && <span className="unsaved-badge">Unsaved changes</span>}
          <button type="button" onClick={handleCancel} disabled={!dirty || saving}>
            Cancel
          </button>
          <button type="button" onClick={handleResetAll} disabled={!activeProfileId || saving}>
            Reset all
          </button>
          <button type="button" onClick={handleSave} disabled={!activeProfileId || !dirty || saving}>
            {saving ? "Saving…" : "Save"}
          </button>
          {/* The PDF always renders the real profile, never the sample. Without
              this guard an empty profile silently produced a blank PDF while
              the preview showed sample data. */}
          <button
            type="button"
            className="pdf-button"
            onClick={handleDownloadPdf}
            disabled={!activeProfileId || generating || !hasResumeContent(activeProfile)}
            title={
              hasResumeContent(activeProfile)
                ? "Generate a PDF from this profile"
                : "Add resume content on the Profile tab first — the PDF uses your real profile, not the sample."
            }
          >
            {generating && <span className="spinner" aria-hidden="true" />}
            {generating ? "Generating…" : "Download PDF"}
          </button>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      {!hasResumeContent(activeProfile) && (
        <p className="notice">
          This profile has no resume content yet, so the preview shows sample data.
          Add your details on the <strong>Profile</strong> tab to enable PDF download.
        </p>
      )}

      <div
        className={
          "templates-layout" +
          (showTemplateList ? "" : " templates-layout--no-list") +
          (showStyleEditor ? "" : " templates-layout--no-style")
        }
      >
        <ul className="template-list" aria-label="Available templates" hidden={!showTemplateList}>
          {templates.map((template) => {
            const isSelected = template.id === selectedTemplateId;
            return (
              <li key={template.id}>
                <button
                  type="button"
                  className={`template-card${isSelected ? " template-card--selected" : ""}`}
                  aria-pressed={isSelected}
                  onClick={() => setSelectedTemplateId(template.id)}
                >
                  {/* Selection is not communicated by colour alone (9.4). */}
                  <span className="template-card-name">
                    {isSelected ? "✓ " : ""}
                    {template.name}
                  </span>
                  <span className="template-card-desc">{template.description}</span>
                </button>
              </li>
            );
          })}
        </ul>

        <div className="template-preview-pane">
          {effectiveStyle && (
            <ResumePreview
              data={previewData}
              style={effectiveStyle}
              template={selectedTemplate}
              isSample={showingSample}
            />
          )}
        </div>

        <aside className="style-pane" aria-label="Style editor" hidden={!showStyleEditor}>
          <h2 className="style-pane-title">Style</h2>
          {!activeProfileId && (
            <p className="notice">Create a profile to save style changes.</p>
          )}
          {effectiveStyle && (
            <StyleEditor
              effective={effectiveStyle}
              overrides={draftOverrides}
              supportedFields={selectedTemplate?.supportedStyleFields ?? []}
              onChange={handleStyleChange}
              onResetField={handleResetField}
              onResetGroup={handleResetGroup}
            />
          )}
        </aside>
      </div>
    </div>
  );
}
