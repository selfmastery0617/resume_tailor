/** Constrained, flow-based template builder.
 *
 * A v2 template always owns the same semantic resume blocks. Users arrange
 * those blocks in page columns, then arrange each block's allowed sections in
 * rows and columns. There are no arbitrary coordinates, so variable-length
 * content can still paginate naturally.
 */

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import {
  createTemplate,
  deleteTemplate,
  fetchDefaultLayout,
  updateTemplate,
} from "../api/builder";
import { fetchTemplates } from "../api/templates";
import { useSampleResume } from "../hooks/useSampleResume";
import { ResumePreview } from "../components/ResumePreview";
import { SampleResumeEditor } from "../components/SampleResumeEditor";
import { APPROVED_FONTS } from "../resume/fonts";
import type {
  Flow,
  FlowColumn,
  FlowItem,
  LayoutDivider,
  SemanticBlock,
  TemplateLayout,
  TemplateLayoutV1,
  TemplateLayoutV2,
} from "../resume/layoutTypes";
import {
  BLOCK_LABELS,
  SECTION_LABELS,
  addFlowRow,
  addSummary,
  blocksInColumn,
  flowFor,
  hasSection,
  isCompactEntryColumn,
  isTemplateLayoutV2,
  mergeSectionIntoPreviousColumn,
  moveBlock,
  moveBlockToColumn,
  moveSection,
  moveSectionBy,
  moveSectionToNewRow,
  removeFlowRow,
  removeSummary,
  sectionColorField,
  setBlockDivider,
  setBlockLabel,
  setDividerDefaultCharacter,
  setFlowColumnDivider,
  setFlowColumnAlign,
  setFlowColumnMode,
  setFlowItemDivider,
  setFlowItemColor,
  setFlowItemHidden,
  setFlowRowColumnCount,
  setFlowRowDivider,
  setFlowRowSplit,
  setItemDivider,
  setOptionalLocation,
  setPageMargin,
  setPaperSize,
  setPageColumnDivider,
  setRegionColumnCount,
  setRegionDivider,
  setRegionSplit,
  splitSectionToNewColumn,
  upgradeLegacyLayout,
  type FlowScope,
} from "../resume/layoutOps";
import { PAPER_OPTIONS, pageGeometry } from "../resume/pageGeometry";
import type { ResumeStyle, TemplateDefinition } from "../resume/types";

interface TemplateBuilderPageProps {
  active?: boolean;
}

export function TemplateBuilderPage({ active = true }: TemplateBuilderPageProps) {
  const [templates, setTemplates] = useState<TemplateDefinition[]>([]);
  const [systemStyle, setSystemStyle] = useState<ResumeStyle | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<TemplateLayout | null>(null);
  const [saved, setSaved] = useState<TemplateLayout | null>(null);
  const [draftStyle, setDraftStyle] = useState<Partial<ResumeStyle>>({});
  const [savedStyle, setSavedStyle] = useState<Partial<ResumeStyle>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const { sampleResume, setSampleResume } = useSampleResume(active);
  const [editingSample, setEditingSample] = useState(false);
  const selectedIdRef = useRef<string | null>(null);
  const saveSequence = useRef(0);

  const userTemplates = templates.filter((template) => template.source === "user");
  const selected = templates.find((template) => template.id === selectedId) ?? null;
  const dirty =
    (draft !== null && JSON.stringify(draft) !== JSON.stringify(saved)) ||
    JSON.stringify(draftStyle) !== JSON.stringify(savedStyle);

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  const reload = useCallback(async () => {
    try {
      const catalog = await fetchTemplates();
      setTemplates(catalog.templates);
      setSystemStyle(catalog.systemDefaultStyle);
      return catalog.templates;
    } catch {
      setError("Could not load templates. Is the backend running?");
      return [];
    }
  }, []);

  useEffect(() => {
    if (active) void reload();
  }, [active, reload]);

  const open = useCallback((template: TemplateDefinition | null) => {
    const layout = (template?.layout as TemplateLayout | undefined) ?? null;
    setSelectedId(template?.id ?? null);
    selectedIdRef.current = template?.id ?? null;
    setDraft(layout ? structuredClone(layout) : null);
    setSaved(layout ? structuredClone(layout) : null);
    const templateStyle = structuredClone(template?.defaultStyle ?? {});
    setDraftStyle(templateStyle);
    setSavedStyle(structuredClone(templateStyle));
    setNotice(null);
    setError(null);
  }, []);

  const requestOpen = (template: TemplateDefinition | null) => {
    if (dirty && !window.confirm("Discard unsaved template changes?")) return;
    open(template);
  };

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // Always sample data, deliberately -- see the matching note in
  // TemplatesPage.tsx. A real profile is often sparse and would make a
  // layout under construction look broken when it isn't. Null only while
  // useSampleResume's fetch is in flight -- both render blocks below that
  // use it are already gated on other conditions, so this just adds one
  // more rather than needing a page-wide loading gate.
  const previewData = sampleResume;
  const effectiveStyle = useMemo<ResumeStyle | null>(() => {
    if (!systemStyle) return null;
    return { ...systemStyle, ...draftStyle } as ResumeStyle;
  }, [systemStyle, draftStyle]);

  const describeError = (caught: unknown, fallback: string) =>
    (caught as { response?: { data?: { detail?: { message?: string } } } }).response?.data
      ?.detail?.message ?? fallback;

  const handleCreate = async (duplicateOf?: string) => {
    if (dirty && !window.confirm("Discard unsaved template changes and create a new copy?")) return;
    const name = window.prompt(
      duplicateOf ? "Name for the copy" : "New template name",
      duplicateOf ? "My custom template" : "My template",
    );
    if (!name) return;
    const selectionAtStart = selectedIdRef.current;
    setBusy(true);
    setError(null);
    try {
      const layout = duplicateOf ? undefined : await fetchDefaultLayout();
      const created = await createTemplate({ name, layout, duplicateOf });
      const catalog = await reload();
      if (selectedIdRef.current === selectionAtStart) {
        open(catalog.find((template) => template.id === created.id) ?? created);
      }
      setNotice(`Created “${created.name}”.`);
    } catch (caught) {
      setError(describeError(caught, "Could not create the template."));
    } finally {
      setBusy(false);
    }
  };

  const handleUpgrade = async () => {
    if (!selected || !draft || isTemplateLayoutV2(draft)) return;
    const sourceId = selected.id;
    const name = window.prompt("Name for the five-block copy", `${selected.name} (five-block)`);
    if (!name) return;
    setBusy(true);
    setError(null);
    try {
      const upgraded = upgradeLegacyLayout(draft as TemplateLayoutV1, selected.defaultStyle);
      const created = await createTemplate({
        name,
        description: selected.description,
        layout: upgraded,
        defaultStyle: selected.defaultStyle,
      });
      const catalog = await reload();
      if (selectedIdRef.current === sourceId) {
        open(catalog.find((template) => template.id === created.id) ?? created);
      }
      setNotice(`Created “${created.name}” in the five-block builder.`);
    } catch (caught) {
      setError(describeError(caught, "Could not upgrade the template."));
    } finally {
      setBusy(false);
    }
  };

  const handleSave = async () => {
    if (!selectedId || !draft || !isTemplateLayoutV2(draft)) return;
    const templateId = selectedId;
    const snapshot = structuredClone(draft);
    const styleSnapshot = structuredClone(draftStyle);
    const requestNumber = ++saveSequence.current;
    setBusy(true);
    setError(null);
    try {
      const updated = await updateTemplate(templateId, {
        layout: snapshot,
        defaultStyle: styleSnapshot,
      });
      const updatedLayout = structuredClone(updated.layout as TemplateLayoutV2);
      const updatedStyle = structuredClone(updated.defaultStyle);
      const stillEditingSavedTemplate =
        requestNumber === saveSequence.current && selectedIdRef.current === templateId;
      if (stillEditingSavedTemplate) {
        setSaved(updatedLayout);
        setSavedStyle(updatedStyle);
        // Do not erase edits made while the request was in flight.
        setDraft((current) =>
          current && JSON.stringify(current) === JSON.stringify(snapshot) ? updatedLayout : current,
        );
        setDraftStyle((current) =>
          JSON.stringify(current) === JSON.stringify(styleSnapshot) ? updatedStyle : current,
        );
      }
      await reload();
      if (stillEditingSavedTemplate && selectedIdRef.current === templateId) {
        setNotice(`Saved (version ${updated.version}).`);
      }
    } catch (caught) {
      if (selectedIdRef.current === templateId) {
        setError(describeError(caught, "Could not save the template."));
      }
    } finally {
      if (requestNumber === saveSequence.current) setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedId || !window.confirm("Delete this template?")) return;
    const templateId = selectedId;
    setBusy(true);
    setError(null);
    try {
      await deleteTemplate(templateId);
      await reload();
      if (selectedIdRef.current === templateId) open(null);
      setNotice("Template deleted.");
    } catch (caught) {
      setError(describeError(caught, "Could not delete the template."));
    } finally {
      setBusy(false);
    }
  };

  const mutate = (next: TemplateLayoutV2) => {
    setDraft(next);
    setNotice(null);
  };

  const mutateStyle = (fontFamily: string) => {
    setDraftStyle((current) => ({ ...current, fontFamily }));
    setNotice(null);
  };

  if (!systemStyle) {
    return (
      <div className="builder-page">
        {error ? <p className="error" role="alert">{error}</p> : <p>Loading builder…</p>}
      </div>
    );
  }

  const v2Draft = draft && isTemplateLayoutV2(draft) ? draft : null;
  const geometry = pageGeometry(v2Draft);

  return (
    <div className="builder-page">
      <div className="templates-toolbar">
        <label htmlFor="builder-template">Template</label>
        <select
          id="builder-template"
          value={selectedId ?? ""}
          onChange={(event) =>
            requestOpen(templates.find((template) => template.id === event.target.value) ?? null)
          }
        >
          <option value="">Select a template…</option>
          {userTemplates.map((template) => (
            <option key={template.id} value={template.id}>
              {template.name} (v{template.version})
            </option>
          ))}
        </select>
        <button type="button" onClick={() => handleCreate()} disabled={busy}>New</button>
        <select
          aria-label="Duplicate a built-in template"
          value=""
          onChange={(event) => event.target.value && handleCreate(event.target.value)}
          disabled={busy}
        >
          <option value="">Duplicate built-in…</option>
          {templates.filter((template) => template.source === "builtin").map((template) => (
            <option key={template.id} value={template.id}>{template.name}</option>
          ))}
        </select>
        <button type="button" onClick={() => setEditingSample(true)}>
          Edit sample data
        </button>
        <div className="templates-actions">
          {dirty && <span className="unsaved-badge">Unsaved changes</span>}
          <button type="button" onClick={() => open(selected)} disabled={!dirty || busy}>Cancel</button>
          <button type="button" onClick={handleDelete} disabled={!selectedId || busy}>Delete</button>
          <button
            type="button"
            className="primary"
            onClick={handleSave}
            disabled={!v2Draft || !dirty || busy}
          >
            {busy ? "Saving…" : "Save template"}
          </button>
        </div>
      </div>

      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}

      {!draft && (
        <p className="notice">
          Select a template to edit, create a new one, or duplicate a built-in.
          Built-in templates are read-only.
        </p>
      )}

      {draft && effectiveStyle && !v2Draft && previewData && (
        <div className="builder-layout builder-layout--legacy">
          <aside className="builder-structure builder-legacy" aria-label="Legacy template upgrade">
            <h2>Previous builder format</h2>
            <p>
              This template remains available exactly as saved, but its free-form blocks cannot be
              edited in the five-block builder.
            </p>
            <p className="notice">
              Upgrading creates a new copy. Name, title, and contact are regrouped into Header;
              regions with more than two columns are collapsed; unsupported custom text, spacer,
              and divider blocks are not copied.
            </p>
            <button type="button" className="primary" onClick={handleUpgrade} disabled={busy}>
              Upgrade as five-block copy
            </button>
          </aside>
          <div className="template-preview-pane">
            <ResumePreview
              data={previewData}
              style={effectiveStyle}
              template={selected}
              layout={draft}
              isSample
            />
          </div>
        </div>
      )}

      {v2Draft && effectiveStyle && previewData && (
        <div className="builder-layout">
          <TemplateStructureEditor
            layout={v2Draft}
            style={effectiveStyle}
            experienceCount={previewData.experience.length}
            educationCount={previewData.education.length}
            onChange={mutate}
          />

          <div className="template-preview-pane">
            <ResumePreview
              data={previewData}
              style={effectiveStyle}
              template={selected}
              layout={v2Draft}
              isSample
            />
          </div>

          <aside className="style-pane builder-settings" aria-label="Template settings">
            <h2 className="style-pane-title">Template settings</h2>
            <label htmlFor="builder-paper-size">Paper size</label>
            <select
              id="builder-paper-size"
              value={geometry.size}
              onChange={(event) =>
                mutate(setPaperSize(v2Draft, event.target.value as (typeof PAPER_OPTIONS)[number]["id"]))
              }
            >
              {PAPER_OPTIONS.map((paper) => (
                <option key={paper.id} value={paper.id}>{paper.label}</option>
              ))}
            </select>
            <fieldset className="builder-page-margins">
              <legend>Page margins (inches)</legend>
              {([
                ["top", geometry.marginTopIn],
                ["bottom", geometry.marginBottomIn],
                ["left", geometry.marginLeftIn],
                ["right", geometry.marginRightIn],
              ] as const).map(([side, value]) => (
                <label key={side}>
                  {side[0].toUpperCase() + side.slice(1)}
                  <input
                    type="number"
                    min={0}
                    max={2}
                    step={0.05}
                    value={value}
                    onChange={(event) =>
                      mutate(setPageMargin(v2Draft, side, Number(event.target.value)))
                    }
                  />
                </label>
              ))}
            </fieldset>
            <label htmlFor="builder-font-family">Font family</label>
            <select
              id="builder-font-family"
              value={effectiveStyle.fontFamily}
              onChange={(event) => mutateStyle(event.target.value)}
            >
              {APPROVED_FONTS.map((font) => (
                <option key={font} value={font}>{font}</option>
              ))}
            </select>
            <p className="builder-help">
              The selected face is used when installed; preview and PDF use a matching fallback otherwise.
            </p>
            <label htmlFor="builder-divider-character">Default divider character</label>
            <input
              id="builder-divider-character"
              className="builder-character-input"
              value={v2Draft.dividerDefaults.character}
              maxLength={6}
              onChange={(event) =>
                mutate(setDividerDefaultCharacter(v2Draft, event.target.value))
              }
            />
            <p className="builder-help">
              Character dividers use this value unless that gap has its own character.
            </p>
            <label className="builder-toggle">
              <input
                type="checkbox"
                checked={v2Draft.blocks.some((block) => block.type === "summary")}
                onChange={(event) =>
                  mutate(event.target.checked ? addSummary(v2Draft) : removeSummary(v2Draft))
                }
              />
              Include Summary block
            </label>
            <div className="builder-guidance">
              <strong>Structured placement</strong>
              <p>
                Blocks stay in page columns. Sections stay inside their owning block and can be
                placed beside or below one another, so the resume still flows across pages.
              </p>
            </div>
          </aside>
        </div>
      )}

      <SampleResumeEditor
        open={editingSample}
        initialData={sampleResume}
        onClose={() => setEditingSample(false)}
        onSaved={setSampleResume}
      />
    </div>
  );
}

function TemplateStructureEditor({
  layout,
  style,
  experienceCount,
  educationCount,
  onChange,
}: {
  layout: TemplateLayoutV2;
  style: ResumeStyle;
  experienceCount: number;
  educationCount: number;
  onChange: (layout: TemplateLayoutV2) => void;
}) {
  const pageColumns = layout.page.regions.flatMap((region) =>
    region.columns.map((column) => ({ id: column.id, label: `${region.id} / ${column.id}` })),
  );

  return (
    <aside className="builder-structure" aria-label="Template structure">
      <div className="builder-structure-intro">
        <h2>Blocks and sections</h2>
        <p>Use the controls in each card to place content. Mandatory sections cannot be removed.</p>
      </div>
      {layout.page.regions.map((region, regionIndex) => (
        <section key={region.id} className="builder-region" aria-labelledby={`region-${region.id}`}>
          {regionIndex > 0 && (
            <DividerControl
              label={`Horizontal divider before ${region.id} region`}
              orientation="horizontal"
              value={region.dividerBefore}
              defaultCharacter={layout.dividerDefaults.character}
              defaultColor={style.sectionColor}
              onChange={(value) => onChange(setRegionDivider(layout, region.id, value))}
            />
          )}
          <header className="builder-region-head">
            <strong id={`region-${region.id}`}>{region.id}</strong>
            <label>
              <span className="sr-only">Columns in {region.id}</span>
              <select
                value={region.columns.length}
                onChange={(event) =>
                  onChange(setRegionColumnCount(layout, region.id, event.target.value === "2" ? 2 : 1))
                }
              >
                <option value={1}>1 page column</option>
                <option value={2}>2 page columns</option>
              </select>
            </label>
          </header>
          {region.columns.length === 2 && (
            <label className="builder-split">
              Page split {Math.round(region.columns[0].widthPct)}% / {Math.round(region.columns[1].widthPct)}%
              <input
                type="range"
                min={15}
                max={85}
                step={5}
                value={region.columns[0].widthPct}
                onChange={(event) =>
                  onChange(setRegionSplit(layout, region.id, Number(event.target.value)))
                }
              />
            </label>
          )}
          <div className="builder-columns">
            {region.columns.map((column, columnIndex) => {
              const blocks = blocksInColumn(layout, column.id);
              return (
                <div key={column.id} className="builder-page-column">
                  {columnIndex > 0 && (
                    <DividerControl
                      label={`Vertical divider before ${column.id}`}
                      orientation="vertical"
                      value={column.dividerBefore}
                      defaultCharacter={layout.dividerDefaults.character}
                      defaultColor={style.sectionColor}
                      onChange={(value) =>
                        onChange(setPageColumnDivider(layout, region.id, column.id, value))
                      }
                    />
                  )}
                  <div className="builder-column-name">{column.id}</div>
                  {blocks.length === 0 && <p className="notice">No blocks in this column.</p>}
                  <div className="builder-semantic-list">
                    {blocks.map((block, index) => (
                      <SemanticBlockCard
                        key={block.id}
                        layout={layout}
                        block={block}
                        baseStyle={style}
                        index={index}
                        siblingCount={blocks.length}
                        pageColumns={pageColumns}
                        repeatCount={
                          block.type === "experience"
                            ? experienceCount
                            : block.type === "education"
                              ? educationCount
                              : 0
                        }
                        onChange={onChange}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </aside>
  );
}

function SemanticBlockCard({
  layout,
  block,
  baseStyle,
  index,
  siblingCount,
  pageColumns,
  repeatCount,
  onChange,
}: {
  layout: TemplateLayoutV2;
  block: SemanticBlock;
  baseStyle: ResumeStyle;
  index: number;
  siblingCount: number;
  pageColumns: Array<{ id: string; label: string }>;
  repeatCount: number;
  onChange: (layout: TemplateLayoutV2) => void;
}) {
  const blockStyle = { ...baseStyle, ...(block.style ?? {}) } as ResumeStyle;
  const heading = block.contentFlow.rows
    .flatMap((currentRow) => currentRow.columns)
    .flatMap((column) => column.items)
    .find((currentItem) => currentItem.ref === "blockTitle");
  const headingLabel = String(heading?.props?.label ?? BLOCK_LABELS[block.type]);
  const optionalLocation = block.type === "experience" || block.type === "education";

  return (
    <div className="builder-semantic-wrap">
      {index > 0 && (
        <DividerControl
          label={`Horizontal divider before ${BLOCK_LABELS[block.type]} block`}
          orientation="horizontal"
          value={block.dividerBefore}
          defaultCharacter={layout.dividerDefaults.character}
          defaultColor={blockStyle.sectionColor}
          onChange={(value) => onChange(setBlockDivider(layout, block.id, value))}
        />
      )}
      <details className="builder-semantic-block">
        <summary>{BLOCK_LABELS[block.type]}</summary>
        <div className="builder-block-body">
          <div className="builder-block-actions">
            <button
              type="button"
              onClick={() => onChange(moveBlock(layout, block.id, -1))}
              disabled={index === 0}
              aria-label={`Move ${BLOCK_LABELS[block.type]} up`}
            >
              Move up
            </button>
            <button
              type="button"
              onClick={() => onChange(moveBlock(layout, block.id, 1))}
              disabled={index === siblingCount - 1}
              aria-label={`Move ${BLOCK_LABELS[block.type]} down`}
            >
              Move down
            </button>
            {block.type === "summary" && (
              <button type="button" onClick={() => onChange(removeSummary(layout))}>
                Remove Summary
              </button>
            )}
          </div>
          <label className="builder-control-label">
            Page column
            <select
              value={block.columnId}
              onChange={(event) => onChange(moveBlockToColumn(layout, block.id, event.target.value))}
            >
              {pageColumns.map((column) => (
                <option key={column.id} value={column.id}>{column.label}</option>
              ))}
            </select>
          </label>
          {heading && (
            <label className="builder-control-label">
              Block title text
              <input
                value={headingLabel}
                maxLength={120}
                onChange={(event) => onChange(setBlockLabel(layout, block.id, event.target.value))}
              />
            </label>
          )}
          {optionalLocation && (
            <label className="builder-toggle">
              <input
                type="checkbox"
                checked={hasSection(block, "item", "location")}
                onChange={(event) =>
                  onChange(setOptionalLocation(layout, block.id, event.target.checked))
                }
              />
              Include location
            </label>
          )}

          <FlowEditor
            layout={layout}
            block={block}
            scope="content"
            title="Block content"
            baseStyle={blockStyle}
            onChange={onChange}
          />

          {block.itemFlow && (
            <div className="builder-group-editor">
              <div className="builder-group-heading">
                <strong>Entry group</strong>
                <span>Repeats {repeatCount} {repeatCount === 1 ? "time" : "times"} in this preview</span>
              </div>
              <DividerControl
                label="Horizontal divider between repeated groups"
                orientation="horizontal"
                value={block.itemDivider}
                defaultCharacter={layout.dividerDefaults.character}
                defaultColor={blockStyle.sectionColor}
                onChange={(value) => onChange(setItemDivider(layout, block.id, value))}
              />
              <FlowEditor
                layout={layout}
                block={block}
                scope="item"
                title="Group sections"
                baseStyle={{
                  ...blockStyle,
                  ...(block.contentFlow.rows
                    .flatMap((row) => row.columns)
                    .flatMap((column) => column.items)
                    .find((item) => item.ref === "groups")?.style ?? {}),
                } as ResumeStyle}
                onChange={onChange}
              />
            </div>
          )}
        </div>
      </details>
    </div>
  );
}

function FlowEditor({
  layout,
  block,
  scope,
  title,
  baseStyle,
  onChange,
}: {
  layout: TemplateLayoutV2;
  block: SemanticBlock;
  scope: FlowScope;
  title: string;
  baseStyle: ResumeStyle;
  onChange: (layout: TemplateLayoutV2) => void;
}) {
  const target = flowFor(block, scope);
  if (!target) return null;
  const canSplitRow = target.rows.some((currentRow) =>
    currentRow.columns.some((column) => column.items.length > 1),
  );

  return (
    <fieldset className="builder-flow">
      <legend>{title}</legend>
      {target.rows.map((currentRow, rowIndex) => {
        const itemCount = currentRow.columns.reduce((sum, column) => sum + column.items.length, 0);
        const compactEntryRow =
          scope === "item" &&
          currentRow.columns.every((column) => isCompactEntryColumn(block, column));
        const maxColumns = Math.min(
          compactEntryRow ? 4 : 2,
          itemCount,
        );
        return (
          <div key={currentRow.id} className="builder-flow-row">
            {rowIndex > 0 && (
              <DividerControl
                label={`Horizontal divider before row ${rowIndex + 1}`}
                orientation="horizontal"
                value={currentRow.dividerBefore}
                defaultCharacter={layout.dividerDefaults.character}
                defaultColor={baseStyle.sectionColor}
                onChange={(value) =>
                  onChange(setFlowRowDivider(layout, block.id, scope, currentRow.id, value))
                }
              />
            )}
            <div className="builder-row-head">
              <strong>Row {rowIndex + 1}</strong>
              <label>
                <span className="sr-only">Columns in row {rowIndex + 1}</span>
                <select
                  value={currentRow.columns.length}
                  onChange={(event) =>
                    onChange(
                      setFlowRowColumnCount(
                        layout,
                        block.id,
                        scope,
                        currentRow.id,
                        Number(event.target.value) as 1 | 2 | 3 | 4,
                      ),
                    )
                  }
                >
                  {Array.from({ length: maxColumns }, (_, index) => index + 1).map((count) => (
                    <option key={count} value={count}>
                      {count} {count === 1 ? "cell" : "cells"} in this line
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                onClick={() => onChange(removeFlowRow(layout, block.id, scope, currentRow.id))}
                disabled={target.rows.length === 1}
                aria-label={
                  rowIndex === 0
                    ? "Merge row 1 into row 2"
                    : `Merge row ${rowIndex + 1} into row ${rowIndex}`
                }
              >
                Merge row
              </button>
            </div>
            {currentRow.columns.length === 2 && (
              <label className="builder-split">
                Row split {Math.round(currentRow.columns[0].widthPct)}% / {Math.round(currentRow.columns[1].widthPct)}%
                <input
                  type="range"
                  min={15}
                  max={85}
                  step={5}
                  value={currentRow.columns[0].widthPct}
                  onChange={(event) =>
                    onChange(
                      setFlowRowSplit(
                        layout,
                        block.id,
                        scope,
                        currentRow.id,
                        Number(event.target.value),
                      ),
                    )
                  }
                />
              </label>
            )}
            <div className="builder-flow-columns">
              {currentRow.columns.map((column, columnIndex) => (
                <FlowColumnEditor
                  key={column.id}
                  layout={layout}
                  block={block}
                  flow={target}
                  scope={scope}
                  rowId={currentRow.id}
                  rowIndex={rowIndex}
                  column={column}
                  columnIndex={columnIndex}
                  rowColumnCount={currentRow.columns.length}
                  baseStyle={baseStyle}
                  onChange={onChange}
                />
              ))}
            </div>
          </div>
        );
      })}
      <button
        type="button"
        className="builder-add-row"
        onClick={() => onChange(addFlowRow(layout, block.id, scope))}
        disabled={!canSplitRow}
      >
        Move last stacked section to a new row
      </button>
    </fieldset>
  );
}

function FlowColumnEditor({
  layout,
  block,
  flow,
  scope,
  rowId,
  rowIndex,
  column,
  columnIndex,
  rowColumnCount,
  baseStyle,
  onChange,
}: {
  layout: TemplateLayoutV2;
  block: SemanticBlock;
  flow: Flow;
  scope: FlowScope;
  rowId: string;
  rowIndex: number;
  column: FlowColumn;
  columnIndex: number;
  rowColumnCount: number;
  baseStyle: ResumeStyle;
  onChange: (layout: TemplateLayoutV2) => void;
}) {
  const compactEntryColumn = scope === "item" && isCompactEntryColumn(block, column);
  const destinations = flow.rows.flatMap((currentRow, destinationRowIndex) =>
    currentRow.columns.map((currentColumn, destinationColumnIndex) => ({
      value: `${currentRow.id}\u0000${currentColumn.id}`,
      label: `Row ${destinationRowIndex + 1}, column ${destinationColumnIndex + 1}`,
      rowId: currentRow.id,
      columnId: currentColumn.id,
    })),
  );

  return (
    <div className="builder-flow-column">
      {columnIndex > 0 && (
        <DividerControl
          label={`Vertical divider before row ${rowIndex + 1}, column ${columnIndex + 1}`}
          orientation="vertical"
          value={column.dividerBefore}
          defaultCharacter={layout.dividerDefaults.character}
          defaultColor={baseStyle.sectionColor}
          onChange={(value) =>
            onChange(setFlowColumnDivider(layout, block.id, scope, rowId, column.id, value))
          }
        />
      )}
      <span className="builder-column-name">Column {columnIndex + 1}</span>
      {compactEntryColumn && (
        <div className="builder-inline-controls">
          {column.items.length > 1 && (
            <label>
              Sections in this cell
              <select
                value={column.mode ?? "stack"}
                onChange={(event) =>
                  onChange(
                    setFlowColumnMode(
                      layout,
                      block.id,
                      scope,
                      rowId,
                      column.id,
                      event.target.value === "inline" ? "inline" : "stack",
                    ),
                  )
                }
              >
                <option value="stack">Stack vertically</option>
                <option value="inline">Merge into one line</option>
              </select>
            </label>
          )}
          <label>
            Position in line
            <select
              value={column.align ?? "left"}
              onChange={(event) =>
                onChange(
                  setFlowColumnAlign(
                    layout,
                    block.id,
                    scope,
                    rowId,
                    column.id,
                    event.target.value as "left" | "center" | "right",
                  ),
                )
              }
            >
              <option value="left">Align left</option>
              <option value="center">Align center</option>
              <option value="right">Align right</option>
            </select>
          </label>
        </div>
      )}
      {column.items.map((currentItem, itemIndex) => (
        <FlowItemEditor
          key={currentItem.id}
          layout={layout}
          block={block}
          scope={scope}
          rowId={rowId}
          column={column}
          item={currentItem}
          itemIndex={itemIndex}
          columnIndex={columnIndex}
          rowColumnCount={rowColumnCount}
          compactEntry={compactEntryColumn}
          destinations={destinations}
          baseStyle={baseStyle}
          onChange={onChange}
        />
      ))}
    </div>
  );
}

function FlowItemEditor({
  layout,
  block,
  scope,
  rowId,
  column,
  item,
  itemIndex,
  columnIndex,
  rowColumnCount,
  compactEntry,
  destinations,
  baseStyle,
  onChange,
}: {
  layout: TemplateLayoutV2;
  block: SemanticBlock;
  scope: FlowScope;
  rowId: string;
  column: FlowColumn;
  item: FlowItem;
  itemIndex: number;
  columnIndex: number;
  rowColumnCount: number;
  compactEntry: boolean;
  destinations: Array<{ value: string; label: string; rowId: string; columnId: string }>;
  baseStyle: ResumeStyle;
  onChange: (layout: TemplateLayoutV2) => void;
}) {
  const currentDestination = `${rowId}\u0000${column.id}`;
  const colorField = sectionColorField(item.ref);
  const explicitColor = item.style?.[colorField];
  const currentColor =
    typeof explicitColor === "string" ? explicitColor : String(baseStyle[colorField]);
  return (
    <div className="builder-flow-item-wrap">
      {itemIndex > 0 && (
        <DividerControl
          label={
            column.mode === "inline"
              ? `Inline divider before ${SECTION_LABELS[item.ref]}`
              : `Horizontal divider before ${SECTION_LABELS[item.ref]} section`
          }
          orientation={column.mode === "inline" ? "inline" : "horizontal"}
          value={item.dividerBefore}
          defaultCharacter={layout.dividerDefaults.character}
          defaultColor={baseStyle.sectionColor}
          required={column.mode === "inline"}
          onChange={(value) =>
            onChange(setFlowItemDivider(layout, block.id, scope, item.id, value))
          }
        />
      )}
      <div className="builder-flow-item">
        <strong>{SECTION_LABELS[item.ref]}</strong>
        <span className="builder-item-tools">
          <button
            type="button"
            onClick={() => onChange(moveSectionBy(layout, block.id, scope, item.id, -1))}
            disabled={itemIndex === 0}
            aria-label={`Move ${SECTION_LABELS[item.ref]} up in its column`}
          >
            ↑
          </button>
          <button
            type="button"
            onClick={() => onChange(moveSectionBy(layout, block.id, scope, item.id, 1))}
            disabled={itemIndex === column.items.length - 1}
            aria-label={`Move ${SECTION_LABELS[item.ref]} down in its column`}
          >
            ↓
          </button>
        </span>
        <label className="builder-section-visibility">
          <input
            type="checkbox"
            checked={!item.hidden}
            onChange={(event) =>
              onChange(setFlowItemHidden(layout, block.id, scope, item.id, !event.target.checked))
            }
          />
          Show section
        </label>
        <div className="builder-section-color">
          <label>
            <span>Section color</span>
            <input
              type="color"
              value={currentColor}
              onChange={(event) =>
                onChange(setFlowItemColor(layout, block.id, scope, item.id, event.target.value))
              }
            />
          </label>
          <button
            type="button"
            disabled={typeof explicitColor !== "string"}
            onClick={() => onChange(setFlowItemColor(layout, block.id, scope, item.id, null))}
          >
            Use inherited color
          </button>
        </div>
        <label>
          <span className="sr-only">Place {SECTION_LABELS[item.ref]}</span>
          <select
            value={currentDestination}
            onChange={(event) => {
              const destination = destinations.find((candidate) => candidate.value === event.target.value);
              if (destination) {
                onChange(
                  moveSection(
                    layout,
                    block.id,
                    scope,
                    item.id,
                    destination.rowId,
                    destination.columnId,
                    Number.MAX_SAFE_INTEGER,
                  ),
                );
              }
            }}
          >
            {destinations.map((destination) => (
              <option key={destination.value} value={destination.value}>{destination.label}</option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => onChange(moveSectionToNewRow(layout, block.id, scope, item.id, rowId))}
        >
          Place below
        </button>
        {compactEntry && columnIndex > 0 && (
          <button
            type="button"
            onClick={() => onChange(mergeSectionIntoPreviousColumn(layout, block.id, item.id))}
          >
            Merge left
          </button>
        )}
        {compactEntry && column.mode === "inline" && itemIndex > 0 && rowColumnCount < 4 && (
          <button
            type="button"
            onClick={() => onChange(splitSectionToNewColumn(layout, block.id, item.id))}
          >
            Separate into cell
          </button>
        )}
      </div>
    </div>
  );
}

function DividerControl({
  label,
  orientation,
  value,
  defaultCharacter,
  defaultColor,
  required = false,
  onChange,
}: {
  label: string;
  orientation: "horizontal" | "vertical" | "inline";
  value?: LayoutDivider;
  defaultCharacter: string;
  defaultColor: string;
  required?: boolean;
  onChange: (value: LayoutDivider | null) => void;
}) {
  const id = useId();
  const changeKind = (kind: LayoutDivider["kind"]) => {
    const spacing = {
      ...(value?.spaceBeforeIn !== undefined ? { spaceBeforeIn: value.spaceBeforeIn } : {}),
      ...(value?.spaceAfterIn !== undefined ? { spaceAfterIn: value.spaceAfterIn } : {}),
    };
    const color = value?.color ? { color: value.color } : {};
    if (kind === "none" && Object.keys(spacing).length === 0) onChange(null);
    else if (kind === "character") {
      onChange({
        kind,
        ...(value?.character ? { character: value.character } : {}),
        ...color,
        ...spacing,
      });
    } else onChange({ kind, ...color, ...spacing });
  };

  const changeSpace = (field: "spaceBeforeIn" | "spaceAfterIn", raw: string) => {
    const next: LayoutDivider = { ...(value ?? { kind: "none" }) };
    if (raw === "") delete next[field];
    else next[field] = Math.max(0, Math.min(1, Number(raw)));
    if (
      next.kind === "none" &&
      next.spaceBeforeIn === undefined &&
      next.spaceAfterIn === undefined
    ) {
      onChange(null);
    } else onChange(next);
  };

  return (
    <div className={`builder-divider builder-divider--${orientation}`}>
      <label htmlFor={`${id}-kind`}>{label}</label>
      <select
        id={`${id}-kind`}
        value={value?.kind ?? (required ? "character" : "none")}
        onChange={(event) => {
          changeKind(event.target.value as LayoutDivider["kind"]);
        }}
      >
        {!required && <option value="none">No divider</option>}
        <option value="line">
          {orientation === "vertical" ? "Vertical rule" : orientation === "inline" ? "Inline rule" : "Horizontal rule"}
        </option>
        <option value="character">Character</option>
      </select>
      {value?.kind === "character" && (
        <label className="builder-divider-character">
          <span>Character</span>
          <input
            value={value.character ?? defaultCharacter}
            maxLength={6}
            onChange={(event) =>
              onChange({ ...value, kind: "character", character: event.target.value })
            }
          />
        </label>
      )}
      {value?.kind && value.kind !== "none" && (
        <div className="builder-divider-color">
          <label>
            <span>Divider color</span>
            <input
              type="color"
              value={value.color ?? defaultColor}
              onChange={(event) => onChange({ ...value, color: event.target.value })}
            />
          </label>
          <button
            type="button"
            disabled={!value.color}
            onClick={() => {
              const next = { ...value };
              delete next.color;
              onChange(next);
            }}
          >
            Use inherited color
          </button>
        </div>
      )}
      {orientation === "horizontal" && (
        <div className="builder-divider-spacing">
          <label>
            {value?.kind && value.kind !== "none" ? "Before divider (in)" : "Space before (in)"}
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              placeholder={value?.kind && value.kind !== "none" ? "Default" : "0"}
              value={value?.spaceBeforeIn ?? ""}
              onChange={(event) => changeSpace("spaceBeforeIn", event.target.value)}
            />
          </label>
          <label>
            {value?.kind && value.kind !== "none" ? "After divider (in)" : "Additional space (in)"}
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              placeholder={value?.kind && value.kind !== "none" ? "Default" : "0"}
              value={value?.spaceAfterIn ?? ""}
              onChange={(event) => changeSpace("spaceAfterIn", event.target.value)}
            />
          </label>
        </div>
      )}
    </div>
  );
}
