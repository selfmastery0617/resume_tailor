/** Template builder (steps 5-6).
 *
 *  Structure panel on the left, live preview in the middle, block properties on
 *  the right. Every structural edit has a keyboard-operable control (add,
 *  remove, ↑/↓, column dropdown); drag-and-drop is layered on top rather than
 *  being the only way to do something (§9.4).
 *
 *  Edits are local until Save — the same contract as the style editor.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createTemplate,
  deleteTemplate,
  fetchDefaultLayout,
  updateTemplate,
} from "../api/builder";
import { fetchProfiles, fetchTemplates } from "../api/templates";
import { ResumePreview } from "../components/ResumePreview";
import type { LayoutBlock, LayoutBlockType, TemplateLayout } from "../resume/LayoutRenderer";
import {
  BLOCK_LABELS,
  SINGLETON_BLOCKS,
  addBlock,
  blocksInColumn,
  moveBlock,
  moveBlockToColumn,
  placeBlock,
  removeBlock,
  setRegionColumnCount,
  setRegionSplit,
  updateBlock,
  usedSingletons,
} from "../resume/layoutOps";
import { SAMPLE_RESUME } from "../resume/sampleData";
import type { Profile, ResumeStyle, TemplateDefinition } from "../resume/types";

const ALL_BLOCK_TYPES: LayoutBlockType[] = [
  "name",
  "title",
  "contact",
  "summary",
  "experience",
  "education",
  "skills",
  "customText",
  "divider",
  "spacer",
];

interface TemplateBuilderPageProps {
  active?: boolean;
}

export function TemplateBuilderPage({ active = true }: TemplateBuilderPageProps) {
  const [templates, setTemplates] = useState<TemplateDefinition[]>([]);
  const [systemStyle, setSystemStyle] = useState<ResumeStyle | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [profileId, setProfileId] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<TemplateLayout | null>(null);
  const [saved, setSaved] = useState<TemplateLayout | null>(null);
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);
  const [draggingId, setDraggingId] = useState<string | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const userTemplates = templates.filter((t) => t.source === "user");
  const selected = templates.find((t) => t.id === selectedId) ?? null;
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(saved);

  const reload = useCallback(async () => {
    try {
      const [catalog, profileList] = await Promise.all([fetchTemplates(), fetchProfiles()]);
      setTemplates(catalog.templates);
      setSystemStyle(catalog.systemDefaultStyle);
      setProfiles(profileList);
      setProfileId((current) => current ?? profileList[0]?.id ?? null);
    } catch {
      setError("Could not load templates. Is the backend running?");
    }
  }, []);

  useEffect(() => {
    if (active) void reload();
  }, [active, reload]);

  // Open a template for editing.
  const open = (template: TemplateDefinition | null) => {
    setSelectedId(template?.id ?? null);
    setSelectedBlockId(null);
    const layout = (template?.layout as TemplateLayout | undefined) ?? null;
    setDraft(layout ? structuredClone(layout) : null);
    setSaved(layout ? structuredClone(layout) : null);
    setNotice(null);
  };

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const activeProfile = profiles.find((p) => p.id === profileId) ?? null;
  const previewData = activeProfile?.data.profile.fullName
    ? activeProfile.data
    : SAMPLE_RESUME;

  const effectiveStyle = useMemo<ResumeStyle | null>(() => {
    if (!systemStyle) return null;
    return { ...systemStyle, ...(selected?.defaultStyle ?? {}) } as ResumeStyle;
  }, [systemStyle, selected]);

  const selectedBlock: LayoutBlock | null =
    draft?.blocks.find((b) => b.id === selectedBlockId) ?? null;

  // ---- actions ----------------------------------------------------------

  const handleCreate = async (duplicateOf?: string) => {
    const name = window.prompt(
      duplicateOf ? "Name for the copy" : "New template name",
      duplicateOf ? "My custom template" : "My template",
    );
    if (!name) return;
    setBusy(true);
    setError(null);
    try {
      const layout = duplicateOf ? undefined : await fetchDefaultLayout();
      const created = await createTemplate({ name, layout, duplicateOf });
      await reload();
      open(created);
      setNotice(`Created “${created.name}”.`);
    } catch {
      setError("Could not create the template.");
    } finally {
      setBusy(false);
    }
  };

  const handleSave = async () => {
    if (!selectedId || !draft) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await updateTemplate(selectedId, { layout: draft });
      setSaved(structuredClone(updated.layout as TemplateLayout));
      setDraft(structuredClone(updated.layout as TemplateLayout));
      await reload();
      setNotice(`Saved (version ${updated.version}).`);
    } catch (err) {
      // The backend explains exactly which rule the layout broke.
      const detail = (err as { response?: { data?: { detail?: { message?: string } } } })
        .response?.data?.detail?.message;
      setError(detail ?? "Could not save the template.");
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedId || !window.confirm("Delete this template?")) return;
    setBusy(true);
    try {
      await deleteTemplate(selectedId);
      await reload();
      open(null);
      setNotice("Template deleted.");
    } catch {
      setError("Could not delete the template.");
    } finally {
      setBusy(false);
    }
  };

  const mutate = (next: TemplateLayout) => {
    setDraft(next);
    setNotice(null);
  };

  // ---- drag and drop (additive; every action also has a button) ----------

  const onDropInColumn = (columnId: string, index: number) => {
    if (!draft || !draggingId) return;
    mutate(placeBlock(draft, draggingId, columnId, index));
    setDraggingId(null);
  };

  if (!systemStyle) return <p>Loading builder…</p>;

  return (
    <div className="builder-page">
      <div className="templates-toolbar">
        <label htmlFor="builder-template">Template</label>
        <select
          id="builder-template"
          value={selectedId ?? ""}
          onChange={(e) => open(templates.find((t) => t.id === e.target.value) ?? null)}
        >
          <option value="">Select a template…</option>
          {userTemplates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} (v{t.version})
            </option>
          ))}
        </select>
        <button type="button" onClick={() => handleCreate()} disabled={busy}>
          New
        </button>
        <select
          aria-label="Duplicate a built-in template"
          value=""
          onChange={(e) => e.target.value && handleCreate(e.target.value)}
          disabled={busy}
        >
          <option value="">Duplicate built-in…</option>
          {templates
            .filter((t) => t.source === "builtin")
            .map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
        </select>

        <label htmlFor="builder-profile">Preview with</label>
        <select
          id="builder-profile"
          value={profileId ?? ""}
          onChange={(e) => setProfileId(e.target.value || null)}
        >
          {profiles.length === 0 && <option value="">Sample data</option>}
          {profiles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>

        <div className="templates-actions">
          {dirty && <span className="unsaved-badge">Unsaved changes</span>}
          <button type="button" onClick={() => open(selected)} disabled={!dirty || busy}>
            Cancel
          </button>
          <button type="button" onClick={handleDelete} disabled={!selectedId || busy}>
            Delete
          </button>
          <button
            type="button"
            className="primary"
            onClick={handleSave}
            disabled={!selectedId || !dirty || busy}
          >
            {busy ? "Saving…" : "Save template"}
          </button>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}

      {!draft && (
        <p className="notice">
          Select a template to edit, create a new one, or duplicate a built-in.
          Built-in templates are read-only.
        </p>
      )}

      {draft && effectiveStyle && (
        <div className="builder-layout">
          {/* ---- structure ---- */}
          <aside className="builder-structure" aria-label="Template structure">
            {draft.page.regions.map((region) => (
              <section key={region.id} className="builder-region">
                <header className="builder-region-head">
                  <strong>{region.id}</strong>
                  <select
                    aria-label={`Columns in ${region.id}`}
                    value={region.columns.length}
                    onChange={(e) =>
                      mutate(
                        setRegionColumnCount(
                          draft,
                          region.id,
                          Number(e.target.value) === 2 ? 2 : 1,
                        ),
                      )
                    }
                  >
                    <option value={1}>1 column</option>
                    <option value={2}>2 columns</option>
                  </select>
                </header>

                {region.columns.length === 2 && (
                  <label className="builder-split">
                    Split {region.columns[0].widthPct}% / {region.columns[1].widthPct}%
                    <input
                      type="range"
                      min={15}
                      max={85}
                      step={5}
                      value={region.columns[0].widthPct}
                      onChange={(e) =>
                        mutate(setRegionSplit(draft, region.id, Number(e.target.value)))
                      }
                    />
                  </label>
                )}

                <div className="builder-columns">
                  {region.columns.map((column) => {
                    const blocks = blocksInColumn(draft, column.id);
                    return (
                      <div
                        key={column.id}
                        className="builder-column"
                        onDragOver={(e) => {
                          if (draggingId) e.preventDefault();
                        }}
                        onDrop={() => onDropInColumn(column.id, blocks.length)}
                      >
                        <div className="builder-column-name">{column.id}</div>
                        {blocks.length === 0 && <p className="notice">Empty</p>}
                        <ul className="builder-block-list">
                          {blocks.map((block, index) => (
                            <li
                              key={block.id}
                              draggable
                              onDragStart={() => setDraggingId(block.id)}
                              onDragEnd={() => setDraggingId(null)}
                              onDragOver={(e) => {
                                if (draggingId) e.preventDefault();
                              }}
                              onDrop={(e) => {
                                e.stopPropagation();
                                onDropInColumn(column.id, index);
                              }}
                              className={
                                "builder-block" +
                                (block.id === selectedBlockId ? " builder-block--selected" : "")
                              }
                            >
                              <button
                                type="button"
                                className="builder-block-name"
                                onClick={() => setSelectedBlockId(block.id)}
                                aria-pressed={block.id === selectedBlockId}
                              >
                                {block.id === selectedBlockId ? "▸ " : ""}
                                {BLOCK_LABELS[block.type]}
                              </button>
                              <span className="builder-block-tools">
                                <button
                                  type="button"
                                  aria-label={`Move ${BLOCK_LABELS[block.type]} up`}
                                  disabled={index === 0}
                                  onClick={() => mutate(moveBlock(draft, block.id, -1))}
                                >
                                  ↑
                                </button>
                                <button
                                  type="button"
                                  aria-label={`Move ${BLOCK_LABELS[block.type]} down`}
                                  disabled={index === blocks.length - 1}
                                  onClick={() => mutate(moveBlock(draft, block.id, 1))}
                                >
                                  ↓
                                </button>
                                <button
                                  type="button"
                                  aria-label={`Remove ${BLOCK_LABELS[block.type]}`}
                                  onClick={() => {
                                    mutate(removeBlock(draft, block.id));
                                    if (selectedBlockId === block.id) setSelectedBlockId(null);
                                  }}
                                >
                                  ✕
                                </button>
                              </span>
                            </li>
                          ))}
                        </ul>

                        <AddBlockControl
                          layout={draft}
                          columnId={column.id}
                          onAdd={(type) => {
                            const result = addBlock(draft, type, column.id);
                            mutate(result.layout);
                            setSelectedBlockId(result.blockId);
                          }}
                        />
                      </div>
                    );
                  })}
                </div>
              </section>
            ))}
          </aside>

          {/* ---- preview ---- */}
          <div className="template-preview-pane">
            <ResumePreview
              data={previewData}
              style={effectiveStyle}
              template={selected}
              layout={draft}
              isSample={previewData === SAMPLE_RESUME}
            />
          </div>

          {/* ---- properties ---- */}
          <aside className="style-pane" aria-label="Block properties">
            <h2 className="style-pane-title">Block</h2>
            {!selectedBlock && <p className="notice">Select a block to edit it.</p>}
            {selectedBlock && (
              <BlockProperties
                layout={draft}
                block={selectedBlock}
                onChange={(patch) => mutate(updateBlock(draft, selectedBlock.id, patch))}
                onMoveColumn={(columnId) =>
                  mutate(moveBlockToColumn(draft, selectedBlock.id, columnId))
                }
              />
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

function AddBlockControl({
  layout,
  columnId,
  onAdd,
}: {
  layout: TemplateLayout;
  columnId: string;
  onAdd: (type: LayoutBlockType) => void;
}) {
  const used = usedSingletons(layout);
  return (
    <select
      className="builder-add"
      aria-label={`Add a block to ${columnId}`}
      value=""
      onChange={(e) => e.target.value && onAdd(e.target.value as LayoutBlockType)}
    >
      <option value="">+ Add block…</option>
      {ALL_BLOCK_TYPES.map((type) => (
        <option
          key={type}
          value={type}
          // A profile-bound block already placed would be rejected by the
          // validator, so it is disabled rather than offered and refused.
          disabled={SINGLETON_BLOCKS.includes(type) && used.has(type)}
        >
          {BLOCK_LABELS[type]}
          {SINGLETON_BLOCKS.includes(type) && used.has(type) ? " (used)" : ""}
        </option>
      ))}
    </select>
  );
}

function BlockProperties({
  layout,
  block,
  onChange,
  onMoveColumn,
}: {
  layout: TemplateLayout;
  block: LayoutBlock;
  onChange: (patch: Partial<LayoutBlock>) => void;
  onMoveColumn: (columnId: string) => void;
}) {
  const columns = layout.page.regions.flatMap((r) =>
    r.columns.map((c) => ({ id: c.id, region: r.id })),
  );

  return (
    <div className="style-editor">
      <div className="style-row">
        <span className="style-label">Type</span>
        <div className="style-control">{BLOCK_LABELS[block.type]}</div>
      </div>

      <div className="style-row">
        <label className="style-label" htmlFor="blk-column">
          Column
        </label>
        <div className="style-control">
          <select
            id="blk-column"
            value={block.columnId}
            onChange={(e) => onMoveColumn(e.target.value)}
          >
            {columns.map((c) => (
              <option key={c.id} value={c.id}>
                {c.region} / {c.id}
              </option>
            ))}
          </select>
        </div>
      </div>

      {block.type === "customText" && (
        <>
          <div className="prompt-section">
            <label htmlFor="blk-heading">Heading</label>
            <input
              id="blk-heading"
              value={String(block.props?.heading ?? "")}
              onChange={(e) =>
                onChange({ props: { ...block.props, heading: e.target.value } })
              }
            />
          </div>
          <div className="prompt-section">
            <label htmlFor="blk-body">Text — one line per bullet</label>
            <textarea
              id="blk-body"
              className="prompt-textarea"
              rows={5}
              value={String(block.props?.body ?? "")}
              onChange={(e) => onChange({ props: { ...block.props, body: e.target.value } })}
            />
          </div>
        </>
      )}

      {block.type === "spacer" && (
        <div className="style-row">
          <label className="style-label" htmlFor="blk-height">
            Height (in)
          </label>
          <div className="style-control">
            <input
              id="blk-height"
              type="number"
              min={0.05}
              max={3}
              step={0.05}
              value={Number(block.props?.heightInches ?? 0.2)}
              onChange={(e) =>
                onChange({ props: { heightInches: Number(e.target.value) || 0.1 } })
              }
            />
          </div>
        </div>
      )}
    </div>
  );
}
