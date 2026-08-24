/** Versioned renderer for user-built templates.
 *
 * Layout v1 is intentionally preserved as its original flat renderer. Layout
 * v2 renders five semantic blocks whose child sections live in constrained
 * flows, including repeatable Experience and Education item flows.
 */

import { type CSSProperties, type ReactNode } from "react";
import {
  BlockTitleSection,
  ContactBlock,
  CustomTextBlock,
  DividerBlock,
  EducationDate,
  EducationDegree,
  EducationLocation,
  EducationSection,
  EducationUniversityName,
  ExperienceBullets,
  ExperienceCompanyName,
  ExperienceCompanySummary,
  ExperienceLocation,
  ExperiencePeriod,
  ExperienceRoleTitle,
  ExperienceSection,
  NameBlock,
  SkillsContentBlock,
  SkillsSection,
  SpacerBlock,
  SummaryContentBlock,
  SummarySection,
  TitleBlock,
  experienceBullets,
  fontStack,
  hasContactContent,
  type TemplateChrome,
} from "./blocks";
import { dateRange, groupSkills, isEmptyExperience, yearRange } from "./format";
import {
  isTemplateLayoutV2,
  type Flow,
  type FlowItem,
  type FlowRow,
  type LayoutBlock,
  type LayoutDivider,
  type SemanticBlock,
  type SemanticBlockType,
  type TemplateLayout,
  type TemplateLayoutV1,
  type TemplateLayoutV2,
} from "./layoutTypes";
import type { Education, Experience, ResumeData, ResumeStyle, SectionId } from "./types";

// Historical imports in the builder/API came from this module. Re-export the
// versioned contracts while their implementation now lives in layoutTypes.ts.
export type {
  Flow,
  FlowColumn,
  FlowItem,
  FlowItemRef,
  FlowRow,
  LayoutBlock,
  LayoutBlockType,
  LayoutColumn,
  LayoutDivider,
  LayoutRegion,
  SemanticBlock,
  SemanticBlockType,
  TemplateLayout,
  TemplateLayoutV1,
  TemplateLayoutV2,
} from "./layoutTypes";

interface LayoutRendererProps {
  data: ResumeData;
  style: ResumeStyle;
  layout: TemplateLayout;
  chrome?: TemplateChrome;
}

const DEFAULT_DIVIDER_CHARACTER = "\u00b7";
const BLOCK_TITLES: Record<Exclude<SemanticBlockType, "header">, string> = {
  summary: "Summary",
  skills: "Skills",
  experience: "Experience",
  education: "Education",
};

function mergeStyle(base: ResumeStyle, override?: Partial<ResumeStyle>): ResumeStyle {
  return override ? ({ ...base, ...override } as ResumeStyle) : base;
}

// ---------------------------------------------------------------------------
// Layout v1 — keep this path visually identical to the original renderer.
// ---------------------------------------------------------------------------

function renderLegacyBlock(
  block: LayoutBlock,
  data: ResumeData,
  baseStyle: ResumeStyle,
  chrome: TemplateChrome,
) {
  const style = mergeStyle(baseStyle, block.style);

  switch (block.type) {
    case "name":
      return <NameBlock data={data} style={style} />;
    case "title":
      return <TitleBlock data={data} style={style} />;
    case "contact":
      return <ContactBlock data={data} style={style} />;
    case "summary":
      return <SummarySection data={data} style={style} chrome={chrome} />;
    case "experience":
      return <ExperienceSection data={data} style={style} chrome={chrome} />;
    case "skills":
      return <SkillsSection data={data} style={style} chrome={chrome} />;
    case "education":
      return <EducationSection data={data} style={style} chrome={chrome} />;
    case "customText":
      return (
        <CustomTextBlock
          heading={String(block.props?.heading ?? "")}
          body={String(block.props?.body ?? "")}
          style={style}
          chrome={chrome}
        />
      );
    case "divider":
      return <DividerBlock style={style} />;
    case "spacer":
      return <SpacerBlock heightInches={Number(block.props?.heightInches ?? 0.1)} />;
    default:
      return null;
  }
}

function DocumentRoot({ style, children }: { style: ResumeStyle; children: ReactNode }) {
  return (
    <div
      className="resume-document"
      style={{
        fontFamily: fontStack(style.fontFamily),
        width: "100%",
        boxSizing: "border-box",
        background: "#ffffff",
        color: style.bodyColor,
      }}
    >
      {children}
    </div>
  );
}

function LegacyLayoutRenderer({
  data,
  style,
  layout,
  chrome,
}: {
  data: ResumeData;
  style: ResumeStyle;
  layout: TemplateLayoutV1;
  chrome: TemplateChrome;
}) {
  const blocksByColumn = new Map<string, LayoutBlock[]>();
  for (const block of layout.blocks) {
    const list = blocksByColumn.get(block.columnId);
    if (list) list.push(block);
    else blocksByColumn.set(block.columnId, [block]);
  }
  for (const list of blocksByColumn.values()) list.sort((a, b) => a.order - b.order);

  return (
    <DocumentRoot style={style}>
      {layout.page.regions.map((region) => {
        const multiColumn = region.columns.length > 1;
        const regionStyle: CSSProperties = {
          display: multiColumn ? "flex" : "block",
          gap: multiColumn ? "0.25in" : undefined,
          alignItems: "flex-start",
          breakInside: region.keepTogether ? "avoid" : "auto",
        };

        return (
          <div
            key={region.id}
            data-keep-together={region.keepTogether ? "true" : undefined}
            style={regionStyle}
          >
            {region.columns.map((column) => {
              const blocks = blocksByColumn.get(column.id) ?? [];
              if (blocks.length === 0) return null;
              return (
                <div
                  key={column.id}
                  style={{
                    flexBasis: multiColumn ? `${column.widthPct}%` : undefined,
                    flexGrow: 0,
                    flexShrink: 1,
                    minWidth: 0,
                    width: multiColumn ? undefined : "100%",
                  }}
                >
                  {blocks.map((block) => (
                    <div key={block.id}>{renderLegacyBlock(block, data, style, chrome)}</div>
                  ))}
                </div>
              );
            })}
          </div>
        );
      })}
    </DocumentRoot>
  );
}

// ---------------------------------------------------------------------------
// Shared v2 flow and divider rendering.
// ---------------------------------------------------------------------------

function dividerCharacter(divider: LayoutDivider, fallback: string): string {
  return divider.character || fallback || DEFAULT_DIVIDER_CHARACTER;
}

function dividerColor(divider: LayoutDivider, style: ResumeStyle): string {
  return divider.color || style.sectionColor;
}

/** Own a horizontal gap on the following content so a page break cannot leave
 * a rule behind on the preceding page. The wrapper itself remains fragmentable. */
function HorizontalGap({
  divider,
  defaultCharacter,
  style,
  breakBefore = false,
  children,
}: {
  divider?: LayoutDivider;
  defaultCharacter: string;
  style: ResumeStyle;
  breakBefore?: boolean;
  children: ReactNode;
}) {
  const paginationStyle: CSSProperties = breakBefore ? { breakBefore: "page" } : {};
  if (!divider) {
    return (
      <div
        data-break-before={breakBefore ? "page" : undefined}
        style={paginationStyle}
      >
        {children}
      </div>
    );
  }

  const defaultGap = Math.max(0.02, Math.min(0.12, style.sectionBottomInches));
  if (divider.kind === "none") {
    const totalSpace = (divider.spaceBeforeIn ?? 0) + (divider.spaceAfterIn ?? 0);
    return (
      <div
        data-break-before={breakBefore ? "page" : undefined}
        data-divider-kind="none"
        style={{ marginTop: totalSpace ? `${totalSpace}in` : undefined, ...paginationStyle }}
      >
        {children}
      </div>
    );
  }

  const spaceBeforeIn = divider.spaceBeforeIn ?? defaultGap;
  if (divider.kind === "line") {
    const spaceAfterIn = divider.spaceAfterIn ?? defaultGap;
    return (
      <div
        data-break-before={breakBefore ? "page" : undefined}
        data-divider-kind="line"
        data-divider-orientation="horizontal"
        style={{
          borderTop: `1px solid ${dividerColor(divider, style)}`,
          marginTop: `${spaceBeforeIn}in`,
          paddingTop: `${spaceAfterIn}in`,
          ...paginationStyle,
        }}
      >
        {children}
      </div>
    );
  }

  const character = dividerCharacter(divider, defaultCharacter);
  const characterLineHeight = `${style.bodySize * style.bodyLineHeight}pt`;
  const spaceAfterIn = divider.spaceAfterIn ?? 0;
  return (
    <div
      data-break-before={breakBefore ? "page" : undefined}
      data-divider-kind="character"
      data-divider-orientation="horizontal"
      style={{
        position: "relative",
        marginTop: `${spaceBeforeIn}in`,
        paddingTop: `calc(${characterLineHeight} + ${spaceAfterIn}in)`,
        ...paginationStyle,
      }}
    >
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          inset: "0 0 auto 0",
          height: characterLineHeight,
          overflow: "hidden",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: dividerColor(divider, style),
          fontSize: `${style.bodySize}pt`,
          lineHeight: style.bodyLineHeight,
        }}
      >
        {character}
      </div>
      {children}
    </div>
  );
}

function verticalGapStyle(
  divider: LayoutDivider | undefined,
  style: ResumeStyle,
): CSSProperties {
  if (!divider || divider.kind === "none") return {};
  return {
    boxSizing: "border-box",
    borderLeft:
      divider.kind === "line" ? `1px solid ${dividerColor(divider, style)}` : undefined,
    paddingLeft: "0.14in",
    position: "relative",
  };
}

function VerticalCharacterDivider({
  divider,
  defaultCharacter,
  style,
}: {
  divider?: LayoutDivider;
  defaultCharacter: string;
  style: ResumeStyle;
}) {
  if (!divider || divider.kind !== "character") return null;
  return (
    <div
      aria-hidden="true"
      data-divider-kind="character"
      data-divider-orientation="vertical"
      style={{
        position: "absolute",
        left: 0,
        top: "50%",
        transform: "translate(-50%, -50%)",
        color: dividerColor(divider, style),
        fontSize: `${style.bodySize}pt`,
        lineHeight: 1,
        whiteSpace: "nowrap",
      }}
    >
      {dividerCharacter(divider, defaultCharacter)}
    </div>
  );
}

interface ResolvedFlowItem {
  id: string;
  dividerBefore?: LayoutDivider;
  node: ReactNode;
}

interface ResolvedFlowColumn {
  id: string;
  widthPct: number;
  mode: "stack" | "inline";
  align: "left" | "center" | "right";
  dividerBefore?: LayoutDivider;
  items: ResolvedFlowItem[];
}

interface ResolvedFlowRow {
  id: string;
  dividerBefore?: LayoutDivider;
  columns: ResolvedFlowColumn[];
}

type ItemResolver = (item: FlowItem) => ReactNode | null;

function resolveFlow(flow: Flow, resolveItem: ItemResolver): ResolvedFlowRow[] {
  return flow.rows
    .map((row) => ({
      id: row.id,
      dividerBefore: row.dividerBefore,
      columns: row.columns
        .map((column) => ({
          id: column.id,
          widthPct: column.widthPct,
          mode: column.mode ?? "stack",
          align: column.align ?? "left",
          dividerBefore: column.dividerBefore,
          items: column.items
            .map((item): ResolvedFlowItem | null => {
              if (item.hidden) return null;
              const node = resolveItem(item);
              return node === null || node === undefined
                ? null
                : { id: item.id, dividerBefore: item.dividerBefore, node };
            })
            .filter((item): item is ResolvedFlowItem => item !== null),
        }))
        .filter((column) => column.items.length > 0),
    }))
    .filter((row) => row.columns.length > 0);
}

function FlowView({
  rows,
  style,
  defaultCharacter,
}: {
  rows: ResolvedFlowRow[];
  style: ResumeStyle;
  defaultCharacter: string;
}) {
  if (!rows.length) return null;
  return (
    <>
      {rows.map((row, rowIndex) => {
        const multiColumn = row.columns.length > 1;
        return (
          <HorizontalGap
            key={row.id}
            divider={rowIndex > 0 ? row.dividerBefore : undefined}
            defaultCharacter={defaultCharacter}
            style={style}
          >
            <div
              style={{
                display: multiColumn ? "flex" : "block",
                gap: multiColumn ? "0.2in" : undefined,
                alignItems: "flex-start",
                minWidth: 0,
              }}
            >
              {row.columns.map((column, columnIndex) => {
                const divider = columnIndex > 0 ? column.dividerBefore : undefined;
                const inline = column.mode === "inline";
                return (
                  <div
                    key={column.id}
                    data-divider-kind={divider?.kind}
                    data-divider-orientation={divider ? "vertical" : undefined}
                    style={{
                      flexBasis: multiColumn ? `${column.widthPct}%` : undefined,
                      flexGrow: 0,
                      flexShrink: 1,
                      minWidth: 0,
                      width: multiColumn ? undefined : "100%",
                      textAlign: column.align,
                      ...verticalGapStyle(divider, style),
                    }}
                  >
                    <VerticalCharacterDivider
                      divider={divider}
                      defaultCharacter={defaultCharacter}
                      style={style}
                    />
                    {inline ? (
                      <div
                        data-flow-mode="inline"
                        style={{
                          display: "flex",
                          alignItems: "baseline",
                          justifyContent:
                            column.align === "right"
                              ? "flex-end"
                              : column.align === "center"
                                ? "center"
                                : "flex-start",
                          minWidth: 0,
                          whiteSpace: "nowrap",
                        }}
                      >
                        {column.items.map((item, itemIndex) => (
                          <div key={item.id} style={{ display: "inline-flex", alignItems: "baseline" }}>
                            {itemIndex > 0 && (
                              <InlineDivider
                                divider={item.dividerBefore}
                                defaultCharacter={defaultCharacter}
                                style={style}
                              />
                            )}
                            <div style={{ minWidth: 0 }}>{item.node}</div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      column.items.map((item, itemIndex) => (
                        <HorizontalGap
                          key={item.id}
                          divider={itemIndex > 0 ? item.dividerBefore : undefined}
                          defaultCharacter={defaultCharacter}
                          style={style}
                        >
                          {item.node}
                        </HorizontalGap>
                      ))
                    )}
                  </div>
                );
              })}
            </div>
          </HorizontalGap>
        );
      })}
    </>
  );
}

function InlineDivider({
  divider,
  defaultCharacter,
  style,
}: {
  divider?: LayoutDivider;
  defaultCharacter: string;
  style: ResumeStyle;
}) {
  if (!divider || divider.kind === "none") return null;
  if (divider.kind === "line") {
    return (
      <span
        aria-hidden="true"
        data-divider-kind="line"
        data-divider-orientation="inline"
        style={{
          alignSelf: "stretch",
          borderLeft: `1px solid ${dividerColor(divider, style)}`,
          margin: "0 0.09in",
        }}
      />
    );
  }

  return (
    <span
      aria-hidden="true"
      data-divider-kind="character"
      data-divider-orientation="inline"
      style={{
        color: dividerColor(divider, style),
        margin: "0 0.07in",
        fontSize: `${style.bodySize}pt`,
        lineHeight: 1,
      }}
    >
      {dividerCharacter(divider, defaultCharacter)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Semantic block resolution.
// ---------------------------------------------------------------------------

function renderableExperienceEntries(data: ResumeData): Experience[] {
  return data.experience.filter(
    (entry) => !isEmptyExperience(entry) || Boolean((entry.companySummary ?? "").trim()),
  );
}

function renderableEducationEntries(data: ResumeData): Education[] {
  return data.education.filter((entry) => Boolean((entry.university || entry.degree || "").trim()));
}

function blockTitle(block: SemanticBlock, item: FlowItem): string {
  const authored = item.props?.label ?? item.props?.text ?? item.props?.title;
  if (authored !== undefined) return String(authored);
  return block.type === "header" ? "" : BLOCK_TITLES[block.type];
}

interface ItemContext {
  experience?: Experience;
  education?: Education;
}

function resolveSemanticItem(
  item: FlowItem,
  block: SemanticBlock,
  data: ResumeData,
  blockStyle: ResumeStyle,
  chrome: TemplateChrome,
  defaultCharacter: string,
  context: ItemContext = {},
): ReactNode | null {
  const style = mergeStyle(blockStyle, item.style);

  switch (item.ref) {
    case "name":
      return data.profile.fullName.trim() ? <NameBlock data={data} style={style} /> : null;
    case "title":
      return data.profile.professionalTitle.trim() ? <TitleBlock data={data} style={style} /> : null;
    case "contactInfo":
      return hasContactContent(data, style) ? (
        <ContactBlock data={data} style={style} separator={defaultCharacter} />
      ) : null;
    case "blockTitle": {
      const title = blockTitle(block, item);
      return title.trim() ? <BlockTitleSection title={title} style={style} chrome={chrome} /> : null;
    }
    case "summaryContent":
      return data.profile.summary.trim() ? <SummaryContentBlock data={data} style={style} /> : null;
    case "skills":
      return groupSkills(data.skills).length ? (
        <SkillsContentBlock
          data={data}
          style={style}
          chrome={chrome}
          separator={defaultCharacter}
        />
      ) : null;
    case "groups":
      return resolveRepeatedGroups(
        block,
        data,
        style,
        chrome,
        defaultCharacter,
      );
    case "companyName": {
      const entry = context.experience;
      return entry?.company.trim() ? <ExperienceCompanyName entry={entry} style={style} /> : null;
    }
    case "roleTitle": {
      const entry = context.experience;
      return entry?.title.trim() ? <ExperienceRoleTitle entry={entry} style={style} /> : null;
    }
    case "period": {
      const entry = context.experience;
      return entry && dateRange(entry.startDate, entry.endDate, entry.current) ? (
        <ExperiencePeriod entry={entry} style={style} />
      ) : null;
    }
    case "companySummary": {
      const entry = context.experience;
      return entry && (entry.companySummary ?? "").trim() ? (
        <ExperienceCompanySummary entry={entry} style={style} />
      ) : null;
    }
    case "bullets": {
      const entry = context.experience;
      return entry && experienceBullets(entry, style).length ? (
        <ExperienceBullets entry={entry} style={style} />
      ) : null;
    }
    case "universityName": {
      const entry = context.education;
      return entry?.university.trim() ? <EducationUniversityName entry={entry} style={style} /> : null;
    }
    case "degree": {
      const entry = context.education;
      return entry?.degree.trim() ? <EducationDegree entry={entry} style={style} /> : null;
    }
    case "date": {
      const entry = context.education;
      return entry && yearRange(entry.startYear, entry.endYear) ? (
        <EducationDate entry={entry} style={style} />
      ) : null;
    }
    case "location": {
      if (context.experience?.location.trim()) {
        return <ExperienceLocation entry={context.experience} style={style} />;
      }
      if (context.education?.location.trim()) {
        return <EducationLocation entry={context.education} style={style} />;
      }
      return null;
    }
    default:
      return null;
  }
}

function flowHasItemRef(flow: Flow, ref: FlowItem["ref"]): boolean {
  return flow.rows.some((row) =>
    row.columns.some((column) => column.items.some((flowItem) => flowItem.ref === ref)),
  );
}

// Templates saved before per-company titles existed have no "roleTitle" ref
// anywhere in their itemFlow, so it would otherwise never render there even
// though every Experience entry now carries one. A template that DOES
// design for it -- anywhere, not just the default position -- is left
// untouched; this only fills the gap for templates with no design for it at
// all, in the same position default_layout() uses on the backend: its own
// row right after the company/period heading row.
function withDefaultRoleTitleRow(itemFlow: Flow): Flow {
  if (flowHasItemRef(itemFlow, "roleTitle")) return itemFlow;
  const titleRow: FlowRow = {
    id: "experience-item-roleTitle-row--fallback",
    columns: [
      {
        id: "experience-item-roleTitle-column--fallback",
        widthPct: 100,
        items: [{ id: "experience-item-roleTitle--fallback", ref: "roleTitle" }],
      },
    ],
  };
  const rows = [...itemFlow.rows];
  rows.splice(1, 0, titleRow);
  return { rows };
}

function resolveRepeatedGroups(
  block: SemanticBlock,
  data: ResumeData,
  style: ResumeStyle,
  chrome: TemplateChrome,
  defaultCharacter: string,
): ReactNode | null {
  if (!block.itemFlow) return null;
  const itemFlow =
    block.type === "experience" ? withDefaultRoleTitleRow(block.itemFlow) : block.itemFlow;

  const entries: Array<{ id: string; context: ItemContext; breakBefore: boolean }> =
    block.type === "experience"
      ? renderableExperienceEntries(data).map((entry) => ({
          id: entry.id,
          context: { experience: entry },
          breakBefore: style.forcePageBreakBeforeExperienceIds.includes(entry.id),
        }))
      : block.type === "education"
        ? renderableEducationEntries(data).map((entry) => ({
            id: entry.id,
            context: { education: entry },
            breakBefore: style.forcePageBreakBeforeEducationIds.includes(entry.id),
          }))
        : [];

  const resolvedEntries = entries
    .map((entry) => ({
      ...entry,
      rows: resolveFlow(itemFlow, (item) =>
        resolveSemanticItem(
          item,
          block,
          data,
          style,
          chrome,
          defaultCharacter,
          entry.context,
        ),
      ),
    }))
    .filter((entry) => entry.rows.length > 0);

  if (!resolvedEntries.length) return null;

  return (
    <>
      {resolvedEntries.map((entry, index) => (
          <HorizontalGap
            key={entry.id}
            divider={index > 0 ? block.itemDivider : undefined}
            defaultCharacter={defaultCharacter}
            style={style}
            breakBefore={entry.breakBefore}
          >
            <div
              style={{ marginBottom: `${style.sectionBottomInches}in` }}
            >
              <FlowView rows={entry.rows} style={style} defaultCharacter={defaultCharacter} />
            </div>
          </HorizontalGap>
      ))}
    </>
  );
}

interface ResolvedSemanticBlock {
  block: SemanticBlock;
  style: ResumeStyle;
  breakBefore: boolean;
  node: ReactNode;
}

function resolveSemanticBlock(
  block: SemanticBlock,
  data: ResumeData,
  baseStyle: ResumeStyle,
  chrome: TemplateChrome,
  defaultCharacter: string,
): ResolvedSemanticBlock | null {
  const style = mergeStyle(baseStyle, block.style);

  let meaningfulItems = 0;
  const rows = resolveFlow(block.contentFlow, (item) => {
    const node = resolveSemanticItem(item, block, data, style, chrome, defaultCharacter);
    if (item.ref !== "blockTitle" && node !== null && node !== undefined) meaningfulItems += 1;
    return node;
  });
  // A heading is presentation, not data. Empty sections disappear as a unit,
  // including when item-level styles hide the only available bullet content.
  if (!rows.length || meaningfulItems === 0) return null;

  const sectionId: SectionId | null = block.type === "header" ? null : block.type;
  const breakBefore = sectionId ? style.forcePageBreakBeforeSections.includes(sectionId) : false;
  const content = <FlowView rows={rows} style={style} defaultCharacter={defaultCharacter} />;
  const node =
    block.type === "header" ? (
      <header>{content}</header>
    ) : (
      <section>{content}</section>
    );

  return { block, style, breakBefore, node };
}

interface ResolvedPageColumn {
  id: string;
  widthPct: number;
  dividerBefore?: LayoutDivider;
  blocks: ResolvedSemanticBlock[];
}

function StructuredLayoutRenderer({
  data,
  style,
  layout,
  chrome,
}: {
  data: ResumeData;
  style: ResumeStyle;
  layout: TemplateLayoutV2;
  chrome: TemplateChrome;
}) {
  const defaultCharacter = layout.dividerDefaults.character || DEFAULT_DIVIDER_CHARACTER;
  const blocksByColumn = new Map<string, SemanticBlock[]>();
  for (const block of layout.blocks) {
    const list = blocksByColumn.get(block.columnId);
    if (list) list.push(block);
    else blocksByColumn.set(block.columnId, [block]);
  }
  for (const list of blocksByColumn.values()) list.sort((a, b) => a.order - b.order);

  const regions = layout.page.regions
    .map((region) => ({
      region,
      columns: region.columns
        .map<ResolvedPageColumn>((column) => ({
          id: column.id,
          widthPct: column.widthPct,
          dividerBefore: column.dividerBefore,
          blocks: (blocksByColumn.get(column.id) ?? [])
            .map((block) => resolveSemanticBlock(block, data, style, chrome, defaultCharacter))
            .filter((block): block is ResolvedSemanticBlock => block !== null),
        }))
        .filter((column) => column.blocks.length > 0),
    }))
    .filter((region) => region.columns.length > 0);

  return (
    <DocumentRoot style={style}>
      {regions.map(({ region, columns }, regionIndex) => {
        const multiColumn = columns.length > 1;
        return (
          <HorizontalGap
            key={region.id}
            divider={regionIndex > 0 ? region.dividerBefore : undefined}
            defaultCharacter={defaultCharacter}
            style={style}
          >
            <div
              data-keep-together={region.keepTogether ? "true" : undefined}
              style={{
                display: multiColumn ? "flex" : "block",
                gap: multiColumn ? "0.25in" : undefined,
                alignItems: "flex-start",
                breakInside: region.keepTogether ? "avoid" : "auto",
              }}
            >
              {columns.map((column, columnIndex) => {
                const divider = columnIndex > 0 ? column.dividerBefore : undefined;
                return (
                  <div
                    key={column.id}
                    data-divider-kind={divider?.kind}
                    data-divider-orientation={divider ? "vertical" : undefined}
                    style={{
                      flexBasis: multiColumn ? `${column.widthPct}%` : undefined,
                      flexGrow: 0,
                      flexShrink: 1,
                      minWidth: 0,
                      width: multiColumn ? undefined : "100%",
                      ...verticalGapStyle(divider, style),
                    }}
                  >
                    <VerticalCharacterDivider
                      divider={divider}
                      defaultCharacter={defaultCharacter}
                      style={style}
                    />
                    {column.blocks.map((resolved, blockIndex) => (
                      <HorizontalGap
                        key={resolved.block.id}
                        divider={blockIndex > 0 ? resolved.block.dividerBefore : undefined}
                        defaultCharacter={defaultCharacter}
                        style={resolved.style}
                        breakBefore={resolved.breakBefore}
                      >
                        {resolved.node}
                      </HorizontalGap>
                    ))}
                  </div>
                );
              })}
            </div>
          </HorizontalGap>
        );
      })}
    </DocumentRoot>
  );
}

export function LayoutRenderer({ data, style, layout, chrome = {} }: LayoutRendererProps) {
  if (isTemplateLayoutV2(layout)) {
    return <StructuredLayoutRenderer data={data} style={style} layout={layout} chrome={chrome} />;
  }
  // Stored layouts predating explicit versioning are v1 at runtime. The cast
  // keeps that compatibility even though new TypeScript documents require 1.
  return (
    <LegacyLayoutRenderer
      data={data}
      style={style}
      layout={layout as TemplateLayoutV1}
      chrome={chrome}
    />
  );
}
