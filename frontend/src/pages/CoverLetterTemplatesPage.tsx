/** Cover letter template browsing and preview -- the cover letter analogue
 *  of TemplatesPage.tsx, deliberately much smaller: a cover letter has one
 *  fixed structure (greeting, paragraphs, closing, signature), so there is
 *  no layout/renderer to pick, only page size, font, spacing, and margins
 *  (see CoverLetterStyle, app/schemas/cover_letter_style.py).
 *
 *  Selecting a template only changes the preview -- nothing is written to
 *  the server until Save is pressed, same rule as resume Templates.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchCoverLetterTemplateSettings,
  fetchCoverLetterTemplates,
  resetCoverLetterTemplateSettings,
  saveCoverLetterTemplateSettings,
} from "../api/coverLetters";
import { fetchProfiles } from "../api/templates";
import { useActiveProfileSettings } from "../hooks/useActiveProfileSettings";
import { CoverLetterRenderer } from "../resume/CoverLetterRenderer";
import type {
  CoverLetterData,
  CoverLetterStyle,
  CoverLetterTemplateDefinition,
  ProfileCoverLetterTemplateSettings,
} from "../resume/coverLetterTypes";
import { APPROVED_FONTS } from "../resume/fonts";
import { PAPER_OPTIONS } from "../resume/pageGeometry";
import type { Profile } from "../resume/types";

const DEFAULT_TEMPLATE_ID = "coverletter-1";

const SAMPLE_COVER_LETTER: CoverLetterData = {
  jobTitle: "Senior Data Engineer",
  companyName: "Acme Corp",
  candidateName: "Jane Doe",
  phone: "(555) 123-4567",
  email: "jane.doe@gmail.com",
  linkedin: "linkedin.com/in/janedoe",
  greeting: "Dear Hiring Manager,",
  paragraphs: [
    "I am writing to express my interest in the Senior Data Engineer position at Acme Corp. Over the past eight years, I have built and operated large-scale data pipelines across healthcare and fintech environments.",
    "Most recently, I led the migration of a legacy claims platform onto a modern lakehouse architecture, cutting pipeline runtime by 40% while improving data quality and auditability across every downstream system.",
    "Earlier in my career, I designed streaming ingestion systems that gave clinical operations teams real-time visibility into patient throughput, and I have mentored junior engineers on reliable, testable pipeline design.",
    "I would welcome the opportunity to discuss how my background in scalable data infrastructure could contribute to Acme Corp's engineering goals.",
  ],
  closing: "Sincerely,",
};

interface CoverLetterTemplatesPageProps {
  active?: boolean;
}

const STYLE_FIELDS: { key: keyof CoverLetterStyle; label: string }[] = [
  { key: "fontFamily", label: "Font" },
  { key: "fontSize", label: "Font size (pt)" },
  { key: "lineHeight", label: "Line spacing" },
  { key: "paragraphSpacingIn", label: "Paragraph spacing (in)" },
  { key: "marginTopIn", label: "Top margin (in)" },
  { key: "marginBottomIn", label: "Bottom margin (in)" },
  { key: "marginLeftIn", label: "Left margin (in)" },
  { key: "marginRightIn", label: "Right margin (in)" },
];

export function CoverLetterTemplatesPage({ active = true }: CoverLetterTemplatesPageProps) {
  const [templates, setTemplates] = useState<CoverLetterTemplateDefinition[]>([]);
  const [systemDefaultStyle, setSystemDefaultStyle] = useState<CoverLetterStyle | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const { settings: appSettings } = useActiveProfileSettings(active);
  const activeProfileId = appSettings?.resumeProfile || profiles[0]?.id || null;
  const [settings, setSettings] = useState<ProfileCoverLetterTemplateSettings | null>(null);

  const [selectedTemplateId, setSelectedTemplateId] = useState(DEFAULT_TEMPLATE_ID);
  const [draftOverrides, setDraftOverrides] = useState<Partial<CoverLetterStyle>>({});

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const activeProfile = profiles.find((p) => p.id === activeProfileId) ?? null;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [catalog, profileList] = await Promise.all([
          fetchCoverLetterTemplates(),
          fetchProfiles(),
        ]);
        if (cancelled) return;
        setTemplates(catalog.templates);
        setSystemDefaultStyle(catalog.systemDefaultStyle);
        setProfiles(profileList);
      } catch {
        if (!cancelled) setError("Could not load cover letter templates. Is the backend running?");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!active) return;
    (async () => {
      try {
        setProfiles(await fetchProfiles());
      } catch {
        /* leave the existing list in place on a transient failure */
      }
    })();
  }, [active]);

  const loadSettings = useCallback(async (profileId: string) => {
    try {
      const saved = await fetchCoverLetterTemplateSettings(profileId);
      setSettings(saved);
      setSelectedTemplateId(saved.templateId);
      setDraftOverrides(saved.styleOverrides ?? {});
    } catch {
      setError("Could not load this profile's cover letter template settings.");
    }
  }, []);

  useEffect(() => {
    if (activeProfileId) void loadSettings(activeProfileId);
  }, [activeProfileId, loadSettings]);

  const selectedTemplate = useMemo(
    () => templates.find((t) => t.id === selectedTemplateId) ?? null,
    [templates, selectedTemplateId],
  );

  // Same precedence the server uses: system defaults -> template defaults ->
  // profile overrides. Rebuilt from the currently previewed template, so
  // switching templates shows that template's own defaults.
  const effectiveStyle = useMemo<CoverLetterStyle | null>(() => {
    if (!systemDefaultStyle || !selectedTemplate) return null;
    return {
      ...systemDefaultStyle,
      ...selectedTemplate.defaultStyle,
      ...draftOverrides,
    } as CoverLetterStyle;
  }, [systemDefaultStyle, selectedTemplate, draftOverrides]);

  const dirty =
    settings !== null &&
    (settings.templateId !== selectedTemplateId ||
      JSON.stringify(settings.styleOverrides ?? {}) !== JSON.stringify(draftOverrides));

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const handleStyleChange = (field: keyof CoverLetterStyle, value: string | number) => {
    setDraftOverrides((prev) => ({ ...prev, [field]: value }));
    setNotice(null);
  };

  const handleSave = async () => {
    if (!activeProfileId || !settings) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await saveCoverLetterTemplateSettings(
        activeProfileId,
        selectedTemplateId,
        draftOverrides,
      );
      setSettings(saved);
      setDraftOverrides(saved.styleOverrides ?? {});
      setNotice("Cover letter template and style saved to this profile.");
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
      const reset = await resetCoverLetterTemplateSettings(activeProfileId);
      setSettings(reset);
      setSelectedTemplateId(reset.templateId);
      setDraftOverrides(reset.styleOverrides ?? {});
      setNotice("Cover letter template and style reset to defaults.");
    } catch {
      setError("Could not reset the template.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <p>Loading cover letter templates…</p>;

  return (
    <div className="templates-page">
      <div className="templates-toolbar">
        {activeProfile && (
          <span className="templates-active-profile">
            Showing <strong>{activeProfile.name}</strong>
          </span>
        )}
        <div className="templates-actions">
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
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      {!activeProfileId && (
        <p className="notice">
          Create a profile on the <strong>Profile</strong> tab to save cover letter style changes.
        </p>
      )}

      <div className="templates-layout">
        <ul className="template-list" aria-label="Available cover letter templates">
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
            <div className="cover-letter-page-shell">
              <CoverLetterRenderer data={SAMPLE_COVER_LETTER} style={effectiveStyle} />
            </div>
          )}
        </div>

        <aside className="style-pane" aria-label="Cover letter style editor">
          <h2 className="style-pane-title">Style</h2>
          {effectiveStyle && (
            <div className="cover-letter-style-fields">
              <label className="style-field">
                <span>Page size</span>
                <select
                  value={effectiveStyle.pageSize}
                  onChange={(e) => handleStyleChange("pageSize", e.target.value)}
                >
                  {PAPER_OPTIONS.map((paper) => (
                    <option key={paper.id} value={paper.id}>
                      {paper.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="style-field">
                <span>Font</span>
                <select
                  value={effectiveStyle.fontFamily}
                  onChange={(e) => handleStyleChange("fontFamily", e.target.value)}
                >
                  {APPROVED_FONTS.map((font) => (
                    <option key={font} value={font}>
                      {font}
                    </option>
                  ))}
                </select>
              </label>
              {STYLE_FIELDS.filter((f) => f.key !== "fontFamily").map(({ key, label }) => (
                <label className="style-field" key={key}>
                  <span>{label}</span>
                  <input
                    type="number"
                    step="0.05"
                    value={effectiveStyle[key] as number}
                    onChange={(e) => handleStyleChange(key, Number(e.target.value))}
                  />
                </label>
              ))}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
