"""Template layout documents (template-builder step 1).

A user-created template is *data*: regions -> columns -> blocks. This module is
the contract for that data and the only place it is validated.

Validation runs server-side because a malformed layout would otherwise surface
as a broken PDF long after the fact, and because `customText` is the first place
template content is user-authored rather than source-controlled.
"""

from collections import Counter
from typing import Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.schemas.style import validate_overrides

LEGACY_LAYOUT_VERSION = 1
LAYOUT_VERSION = 2

BlockType = Literal[
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
]

# Blocks bound to profile data may appear at most once — two Experience blocks
# would render the same entries twice.
SINGLETON_BLOCKS: frozenset[str] = frozenset(
    {"name", "title", "contact", "summary", "experience", "education", "skills"}
)

# Purely presentational blocks can repeat freely.
REPEATABLE_BLOCKS: frozenset[str] = frozenset({"customText", "divider", "spacer"})

# Bounds a pathological paste; the resume itself is the place for long prose.
MAX_CUSTOM_TEXT = 2000
MAX_CUSTOM_HEADING = 120

# Column widths are percentages and must tile a region exactly. Float maths
# makes an exact 100 comparison unreliable, so allow a hair of slack.
WIDTH_TOLERANCE = 0.01


class Column(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    widthPct: float = Field(gt=0, le=100)


class Region(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    columns: list[Column] = Field(min_length=1)
    # Regions split by default. Authors may opt a compact region into
    # keep-together behavior when it can fit on a fresh page.
    keepTogether: bool = False

    @model_validator(mode="after")
    def _check_columns(self) -> "Region":
        ids = [c.id for c in self.columns]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Region {self.id!r} has duplicate column ids")

        total = sum(c.widthPct for c in self.columns)
        if abs(total - 100) > WIDTH_TOLERANCE:
            raise ValueError(
                f"Region {self.id!r} column widths must total 100%, got {total:g}%"
            )
        return self


class CustomTextProps(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str = Field(default="", max_length=MAX_CUSTOM_HEADING)
    # Stored and rendered as plain text (RG-FR-003). The renderer never injects
    # this as markup, so no sanitising is required here — only bounding.
    body: str = Field(default="", max_length=MAX_CUSTOM_TEXT)


class Block(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    type: BlockType
    columnId: str = Field(min_length=1, max_length=64)
    order: int = Field(ge=0)
    # Per-block style overrides, validated by the same rules as profile styles.
    style: dict = Field(default_factory=dict)
    # Only meaningful for customText / spacer.
    props: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_props_and_style(self) -> "Block":
        self.style = validate_overrides(self.style)

        if self.type == "customText":
            parsed = CustomTextProps(**self.props)
            if not parsed.heading.strip() and not parsed.body.strip():
                raise ValueError(f"Block {self.id!r}: customText needs a heading or body")
            self.props = parsed.model_dump()
        elif self.type == "spacer":
            height = self.props.get("heightInches", 0.1)
            if not isinstance(height, (int, float)) or isinstance(height, bool):
                raise ValueError(f"Block {self.id!r}: spacer heightInches must be a number")
            if not 0 < float(height) <= 3:
                raise ValueError(f"Block {self.id!r}: spacer height must be 0-3 inches")
            self.props = {"heightInches": float(height)}
        elif self.props:
            raise ValueError(f"Block {self.id!r} of type {self.type!r} takes no props")

        return self


class Page(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regions: list[Region] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_region_ids(self) -> "Page":
        ids = [r.id for r in self.regions]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate region ids")
        return self


class TemplateLayout(BaseModel):
    """The full layout document stored as template_definitions.layout_json."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = LEGACY_LAYOUT_VERSION
    page: Page
    blocks: list[Block] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_blocks(self) -> "TemplateLayout":
        known_columns = {c.id for region in self.page.regions for c in region.columns}

        block_ids = [b.id for b in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("Duplicate block ids")

        seen_singletons: set[str] = set()
        order_by_column: dict[str, set[int]] = {}

        for block in self.blocks:
            if block.columnId not in known_columns:
                raise ValueError(
                    f"Block {block.id!r} references unknown column {block.columnId!r}"
                )

            if block.type in SINGLETON_BLOCKS:
                if block.type in seen_singletons:
                    raise ValueError(
                        f"Block type {block.type!r} may appear only once per template"
                    )
                seen_singletons.add(block.type)

            orders = order_by_column.setdefault(block.columnId, set())
            if block.order in orders:
                raise ValueError(
                    f"Duplicate order {block.order} in column {block.columnId!r}"
                )
            orders.add(block.order)

        return self

    def column_ids(self) -> list[str]:
        return [c.id for region in self.page.regions for c in region.columns]

    def blocks_for_column(self, column_id: str) -> list[Block]:
        return sorted(
            (b for b in self.blocks if b.columnId == column_id), key=lambda b: b.order
        )


# Public name for the immutable legacy contract. ``TemplateLayout`` remains an
# alias for source compatibility with callers written before layout v2.
TemplateLayoutV1 = TemplateLayout


# ---------------------------------------------------------------------------
# Layout v2: five semantic blocks containing structured section flows.
# ---------------------------------------------------------------------------

SemanticBlockType = Literal[
    "header",
    "summary",
    "skills",
    "experience",
    "education",
]
DividerKind = Literal["none", "line", "character"]
FlowMode = Literal["stack", "inline"]
FlowAlign = Literal["left", "center", "right"]
PaperSize = Literal[
    "letter",
    "tabloid",
    "legal",
    "statement",
    "executive",
    "folio",
    "a3",
    "a4",
    "a5",
    "b4",
    "b5",
]

PAPER_DIMENSIONS_IN: dict[str, tuple[float, float]] = {
    "letter": (8.5, 11),
    "tabloid": (11, 17),
    "legal": (8.5, 14),
    "statement": (5.5, 8.5),
    "executive": (7.25, 10.5),
    "folio": (8.5, 13),
    "a3": (11.69, 16.54),
    "a4": (8.27, 11.69),
    "a5": (5.83, 8.27),
    "b4": (9.84, 13.9),
    "b5": (6.93, 9.84),
}

MANDATORY_V2_BLOCKS: frozenset[str] = frozenset(
    {"header", "skills", "experience", "education"}
)
OPTIONAL_V2_BLOCKS: frozenset[str] = frozenset({"summary"})

CONTENT_REFS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "header": (frozenset({"name", "title", "contactInfo"}), frozenset()),
    "summary": (frozenset({"blockTitle", "summaryContent"}), frozenset()),
    "skills": (frozenset({"blockTitle", "skills"}), frozenset()),
    "experience": (frozenset({"blockTitle", "groups"}), frozenset()),
    "education": (frozenset({"blockTitle", "groups"}), frozenset()),
}

ITEM_REFS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "experience": (
        frozenset(
            {
                "companyName",
                "roleTitle",
                "period",
                "companySummary",
                "bullets",
            }
        ),
        frozenset({"location"}),
    ),
    "education": (
        frozenset({"universityName", "degree", "date"}),
        frozenset({"location"}),
    ),
}

# These compact metadata fields may share one line. Long prose and bullet
# content deliberately remain stacked so they can fragment naturally.
INLINE_ITEM_REFS: dict[str, frozenset[str]] = {
    "experience": frozenset({"companyName", "roleTitle", "period", "location"}),
    "education": frozenset({"universityName", "degree", "date", "location"}),
}


def _validate_character(value: str, label: str) -> str:
    if not 1 <= len(value) <= 3:
        raise ValueError(f"{label} must contain 1-3 characters")
    if not value.isprintable():
        raise ValueError(f"{label} must contain only printable characters")
    if not value.strip():
        raise ValueError(f"{label} cannot be whitespace only")
    return value


class DividerConfig(BaseModel):
    """A divider owned by the gap immediately before an item/container."""

    model_config = ConfigDict(extra="forbid")

    kind: DividerKind = "line"
    # When omitted, the divider inherits the effective section color. Keeping
    # this on each gap lets authors color horizontal, vertical, and inline
    # dividers independently without changing surrounding text.
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    # None inherits dividerDefaults.character. It is accepted for line rules as
    # well so changing a divider's kind in the editor does not discard input.
    character: str | None = None
    spaceBeforeIn: float | None = Field(default=None, ge=0, le=1)
    spaceAfterIn: float | None = Field(default=None, ge=0, le=1)

    @field_validator("character")
    @classmethod
    def _check_character(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_character(value, "Divider character")


class DividerDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character: str = "·"

    @field_validator("character")
    @classmethod
    def _check_character(cls, value: str) -> str:
        return _validate_character(value, "Default divider character")


class PageColumnV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    widthPct: float = Field(gt=0, le=100)
    dividerBefore: DividerConfig | None = None


class PageRegionV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    columns: list[PageColumnV2] = Field(min_length=1, max_length=2)
    keepTogether: bool = False
    dividerBefore: DividerConfig | None = None

    @model_validator(mode="after")
    def _check_columns(self) -> "PageRegionV2":
        ids = [column.id for column in self.columns]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Region {self.id!r} has duplicate column ids")
        total = sum(column.widthPct for column in self.columns)
        if abs(total - 100) > WIDTH_TOLERANCE:
            raise ValueError(
                f"Region {self.id!r} column widths must total 100%, got {total:g}%"
            )
        if self.columns[0].dividerBefore is not None:
            raise ValueError(
                f"Region {self.id!r}: the first column cannot have dividerBefore"
            )
        return self


class PageV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    size: PaperSize = "letter"
    marginTopIn: float = Field(default=0.7, ge=0, le=2)
    marginBottomIn: float = Field(default=0.5, ge=0, le=2)
    marginLeftIn: float = Field(default=0.65, ge=0, le=2)
    marginRightIn: float = Field(default=0.65, ge=0, le=2)
    regions: list[PageRegionV2] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_regions(self) -> "PageV2":
        width, height = PAPER_DIMENSIONS_IN[self.size]
        if width - self.marginLeftIn - self.marginRightIn < 2:
            raise ValueError("Page margins must leave at least 2 inches of content width")
        if height - self.marginTopIn - self.marginBottomIn < 2:
            raise ValueError("Page margins must leave at least 2 inches of content height")

        ids = [region.id for region in self.regions]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate region ids")
        if self.regions[0].dividerBefore is not None:
            raise ValueError("The first page region cannot have dividerBefore")

        column_ids = [
            column.id for region in self.regions for column in region.columns
        ]
        if len(column_ids) != len(set(column_ids)):
            raise ValueError("Duplicate page column ids")
        return self


class BlockTitleProps(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(default="", max_length=120)


class FlowItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    ref: str = Field(min_length=1, max_length=64)
    hidden: bool = False
    style: dict = Field(default_factory=dict)
    props: dict = Field(default_factory=dict)
    dividerBefore: DividerConfig | None = None

    @model_validator(mode="after")
    def _check_style_and_props(self) -> "FlowItem":
        self.style = validate_overrides(self.style)
        if self.ref == "blockTitle":
            # Omitted means "use the block-type default"; an explicitly empty
            # label means the author intentionally hid the heading.
            self.props = BlockTitleProps(**self.props).model_dump(exclude_unset=True)
        elif self.props:
            raise ValueError(f"Flow item ref {self.ref!r} does not take props")
        return self


class FlowColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    widthPct: float = Field(gt=0, le=100)
    items: list[FlowItem] = Field(min_length=1)
    mode: FlowMode = "stack"
    align: FlowAlign = "left"
    dividerBefore: DividerConfig | None = None

    @model_validator(mode="after")
    def _check_items(self) -> "FlowColumn":
        ids = [item.id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Flow column {self.id!r} has duplicate item ids")
        if self.items[0].dividerBefore is not None:
            raise ValueError(
                f"Flow column {self.id!r}: the first item cannot have dividerBefore"
            )
        if self.mode == "inline" and any(
            item.dividerBefore is None or item.dividerBefore.kind == "none"
            for item in self.items[1:]
        ):
            raise ValueError(
                f"Flow column {self.id!r}: merged inline items require dividers"
            )
        return self


class FlowRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    columns: list[FlowColumn] = Field(min_length=1, max_length=4)
    dividerBefore: DividerConfig | None = None

    @model_validator(mode="after")
    def _check_columns(self) -> "FlowRow":
        ids = [column.id for column in self.columns]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Flow row {self.id!r} has duplicate column ids")
        total = sum(column.widthPct for column in self.columns)
        if abs(total - 100) > WIDTH_TOLERANCE:
            raise ValueError(
                f"Flow row {self.id!r} column widths must total 100%, got {total:g}%"
            )
        if self.columns[0].dividerBefore is not None:
            raise ValueError(
                f"Flow row {self.id!r}: the first column cannot have dividerBefore"
            )
        return self


class Flow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[FlowRow] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_rows(self) -> "Flow":
        ids = [row.id for row in self.rows]
        if len(ids) != len(set(ids)):
            raise ValueError("Flow has duplicate row ids")
        if self.rows[0].dividerBefore is not None:
            raise ValueError("The first flow row cannot have dividerBefore")
        return self

    def items(self) -> list[FlowItem]:
        return [
            item
            for row in self.rows
            for column in row.columns
            for item in column.items
        ]


class SemanticBlockV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    type: SemanticBlockType
    columnId: str = Field(min_length=1, max_length=64)
    order: int = Field(ge=0)
    style: dict = Field(default_factory=dict)
    dividerBefore: DividerConfig | None = None
    contentFlow: Flow
    itemFlow: Flow | None = None
    itemDivider: DividerConfig | None = None

    @model_validator(mode="after")
    def _check_style_and_scope(self) -> "SemanticBlockV2":
        self.style = validate_overrides(self.style)

        required, optional = CONTENT_REFS[self.type]
        _check_refs(
            f"Block {self.id!r} contentFlow",
            [item.ref for item in self.contentFlow.items()],
            required,
            optional,
        )

        item_scope = ITEM_REFS.get(self.type)
        if item_scope is None:
            if self.itemFlow is not None:
                raise ValueError(
                    f"Block {self.id!r} of type {self.type!r} cannot have itemFlow"
                )
            if self.itemDivider is not None:
                raise ValueError(
                    f"Block {self.id!r} of type {self.type!r} cannot have itemDivider"
                )
        else:
            if self.itemFlow is None:
                raise ValueError(
                    f"Block {self.id!r} of type {self.type!r} requires itemFlow"
                )
            item_required, item_optional = item_scope
            _check_refs(
                f"Block {self.id!r} itemFlow",
                [item.ref for item in self.itemFlow.items()],
                item_required,
                item_optional,
            )

        # Page/block content stays at the original two-column limit. The
        # expanded four-cell rows and inline merging are intentionally scoped
        # to the short Experience/Education metadata named in the requirement.
        for row in self.contentFlow.rows:
            if len(row.columns) > 2:
                raise ValueError(
                    f"Block {self.id!r} contentFlow rows support at most 2 columns"
                )
            if any(column.mode == "inline" for column in row.columns):
                raise ValueError(
                    f"Block {self.id!r} contentFlow cannot use inline columns"
                )

        if self.itemFlow is not None:
            inline_refs = INLINE_ITEM_REFS[self.type]
            for row in self.itemFlow.rows:
                row_refs = {
                    item.ref for column in row.columns for item in column.items
                }
                if len(row.columns) > 2 and not row_refs <= inline_refs:
                    raise ValueError(
                        f"Block {self.id!r}: 3-4 column rows may contain only "
                        "compact entry metadata"
                    )
                for column in row.columns:
                    column_refs = {item.ref for item in column.items}
                    if column.mode == "inline" and not column_refs <= inline_refs:
                        raise ValueError(
                            f"Block {self.id!r}: inline columns may contain only "
                            "compact entry metadata"
                        )
        return self


def _check_refs(
    label: str,
    refs: list[str],
    required: frozenset[str],
    optional: frozenset[str],
) -> None:
    counts = Counter(refs)
    allowed = required | optional
    unexpected = sorted(set(refs) - allowed)
    missing = sorted(ref for ref in required if counts[ref] == 0)
    duplicates = sorted(ref for ref, count in counts.items() if count > 1)
    if unexpected:
        raise ValueError(f"{label} has invalid refs: {', '.join(unexpected)}")
    if missing:
        raise ValueError(f"{label} is missing refs: {', '.join(missing)}")
    if duplicates:
        raise ValueError(f"{label} has duplicate refs: {', '.join(duplicates)}")


class TemplateLayoutV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[2] = LAYOUT_VERSION
    dividerDefaults: DividerDefaults = Field(default_factory=DividerDefaults)
    page: PageV2
    blocks: list[SemanticBlockV2] = Field(min_length=4, max_length=5)

    @model_validator(mode="after")
    def _check_layout(self) -> "TemplateLayoutV2":
        column_ids = {
            column.id for region in self.page.regions for column in region.columns
        }

        block_ids = [block.id for block in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("Duplicate block ids")

        types = Counter(block.type for block in self.blocks)
        missing = sorted(block for block in MANDATORY_V2_BLOCKS if types[block] == 0)
        duplicates = sorted(block for block, count in types.items() if count > 1)
        unknown = sorted(set(types) - MANDATORY_V2_BLOCKS - OPTIONAL_V2_BLOCKS)
        if missing:
            raise ValueError(f"Missing mandatory blocks: {', '.join(missing)}")
        if duplicates:
            raise ValueError(f"Duplicate semantic blocks: {', '.join(duplicates)}")
        if unknown:
            raise ValueError(f"Unknown semantic blocks: {', '.join(unknown)}")

        order_by_column: dict[str, set[int]] = {}
        for block in self.blocks:
            if block.columnId not in column_ids:
                raise ValueError(
                    f"Block {block.id!r} references unknown column {block.columnId!r}"
                )
            orders = order_by_column.setdefault(block.columnId, set())
            if block.order in orders:
                raise ValueError(
                    f"Duplicate order {block.order} in column {block.columnId!r}"
                )
            orders.add(block.order)

        by_column: dict[str, list[SemanticBlockV2]] = {}
        for block in self.blocks:
            by_column.setdefault(block.columnId, []).append(block)
        for column_id, blocks in by_column.items():
            first = min(blocks, key=lambda block: block.order)
            if first.dividerBefore is not None:
                raise ValueError(
                    f"Column {column_id!r}: the first block cannot have dividerBefore"
                )

        self._check_global_ids()
        return self

    def _check_global_ids(self) -> None:
        seen: set[str] = set()

        def add(identifier: str, label: str) -> None:
            if identifier in seen:
                raise ValueError(f"Duplicate id {identifier!r} ({label})")
            seen.add(identifier)

        for region in self.page.regions:
            add(region.id, "page region")
            for column in region.columns:
                add(column.id, "page column")

        for block in self.blocks:
            add(block.id, "block")
            for flow_name, flow in (
                ("contentFlow", block.contentFlow),
                ("itemFlow", block.itemFlow),
            ):
                if flow is None:
                    continue
                for row in flow.rows:
                    add(row.id, f"{block.id}.{flow_name} row")
                    for column in row.columns:
                        add(column.id, f"{block.id}.{flow_name} column")
                        for item in column.items:
                            add(item.id, f"{block.id}.{flow_name} item")


LayoutDocument: TypeAlias = TemplateLayoutV1 | TemplateLayoutV2


class LayoutError(ValueError):
    """A layout document that failed validation, with a human-readable reason."""


def _readable(error: ValidationError) -> str:
    """Flatten pydantic's report into one line fit for an API response.

    Raw ValidationError text ends with a docs URL and repeats the model path,
    which is noise in a 400 body shown to a user in the template builder.
    """
    parts: list[str] = []
    for item in error.errors():
        location = ".".join(str(piece) for piece in item["loc"] if piece != "__root__")
        message = item["msg"].removeprefix("Value error, ")
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts[:4]) or "Invalid layout"


def validate_layout(raw: dict) -> LayoutDocument:
    """Parse and validate a layout document.

    Raises LayoutError with a message the API can hand straight back as a 400.
    """
    if not isinstance(raw, dict):
        raise LayoutError("Layout must be an object")

    version = raw.get("version", LEGACY_LAYOUT_VERSION)
    if not isinstance(version, int) or isinstance(version, bool):
        raise LayoutError("Layout version must be an integer")
    if version == LEGACY_LAYOUT_VERSION:
        model: type[TemplateLayoutV1] | type[TemplateLayoutV2] = TemplateLayoutV1
    elif version == LAYOUT_VERSION:
        model = TemplateLayoutV2
    else:
        raise LayoutError(f"Unsupported layout version: {version}")

    try:
        return model(**raw)
    except ValidationError as exc:
        raise LayoutError(_readable(exc)) from exc


# Kept for rendering and testing stored user layouts created by the first
# builder. New templates start from default_layout(), below.
def default_layout_v1() -> TemplateLayoutV1:
    return TemplateLayoutV1(
        version=LEGACY_LAYOUT_VERSION,
        page=Page(
            regions=[
                Region(id="header", columns=[Column(id="header-main", widthPct=100)]),
                Region(id="body", columns=[Column(id="body-main", widthPct=100)]),
            ]
        ),
        blocks=[
            Block(id="blk-name", type="name", columnId="header-main", order=0),
            Block(id="blk-title", type="title", columnId="header-main", order=1),
            Block(id="blk-contact", type="contact", columnId="header-main", order=2),
            Block(id="blk-summary", type="summary", columnId="body-main", order=0),
            Block(id="blk-experience", type="experience", columnId="body-main", order=1),
            Block(id="blk-skills", type="skills", columnId="body-main", order=2),
            Block(id="blk-education", type="education", columnId="body-main", order=3),
        ],
    )


def _single_column_flow(prefix: str, refs: list[str]) -> Flow:
    return Flow(
        rows=[
            FlowRow(
                id=f"{prefix}-row",
                columns=[
                    FlowColumn(
                        id=f"{prefix}-column",
                        widthPct=100,
                        items=[
                            FlowItem(id=f"{prefix}-{ref}", ref=ref)
                            for ref in refs
                        ],
                    )
                ],
            )
        ]
    )


def _entry_metadata_row(
    prefix: str,
    left_refs: list[str],
    right_refs: list[str],
) -> FlowRow:
    """Conventional one-line entry heading with mergeable inline groups."""

    def inline_items(refs: list[str]) -> list[FlowItem]:
        return [
            FlowItem(
                id=f"{prefix}-{ref}",
                ref=ref,
                dividerBefore=(
                    DividerConfig(kind="character") if index > 0 else None
                ),
            )
            for index, ref in enumerate(refs)
        ]

    return FlowRow(
        id=f"{prefix}-metadata-row",
        columns=[
            FlowColumn(
                id=f"{prefix}-left-column",
                widthPct=65,
                mode="inline",
                align="left",
                items=inline_items(left_refs),
            ),
            FlowColumn(
                id=f"{prefix}-right-column",
                widthPct=35,
                mode="inline",
                align="right",
                items=inline_items(right_refs),
            ),
        ],
    )


def _entry_flow(
    prefix: str,
    left_refs: list[str],
    right_refs: list[str],
    trailing_refs: list[str],
) -> Flow:
    rows = [_entry_metadata_row(prefix, left_refs, right_refs)]
    rows.extend(
        FlowRow(
            id=f"{prefix}-{ref}-row",
            columns=[
                FlowColumn(
                    id=f"{prefix}-{ref}-column",
                    widthPct=100,
                    items=[FlowItem(id=f"{prefix}-{ref}", ref=ref)],
                )
            ],
        )
        for ref in trailing_refs
    )
    return Flow(rows=rows)


def default_layout() -> TemplateLayoutV2:
    """The structured five-block document used for every new template."""

    return TemplateLayoutV2(
        version=LAYOUT_VERSION,
        dividerDefaults=DividerDefaults(character="·"),
        page=PageV2(
            regions=[
                PageRegionV2(
                    id="page-header",
                    columns=[
                        PageColumnV2(id="page-header-main", widthPct=100)
                    ],
                ),
                PageRegionV2(
                    id="page-body",
                    columns=[PageColumnV2(id="page-body-main", widthPct=100)],
                    dividerBefore=DividerConfig(kind="line"),
                ),
            ]
        ),
        blocks=[
            SemanticBlockV2(
                id="block-header",
                type="header",
                columnId="page-header-main",
                order=0,
                contentFlow=_single_column_flow(
                    "header-content", ["name", "title", "contactInfo"]
                ),
            ),
            SemanticBlockV2(
                id="block-summary",
                type="summary",
                columnId="page-body-main",
                order=0,
                contentFlow=_single_column_flow(
                    "summary-content", ["blockTitle", "summaryContent"]
                ),
            ),
            # Right after Summary by default -- the tailored skill set
            # DeepSeek writes (see experience_service._generate_skill_set)
            # is meant to be seen early, not buried below the full experience
            # section. A user can still drag it elsewhere per-template.
            SemanticBlockV2(
                id="block-skills",
                type="skills",
                columnId="page-body-main",
                order=1,
                contentFlow=_single_column_flow(
                    "skills-content", ["blockTitle", "skills"]
                ),
            ),
            SemanticBlockV2(
                id="block-experience",
                type="experience",
                columnId="page-body-main",
                order=2,
                contentFlow=_single_column_flow(
                    "experience-content", ["blockTitle", "groups"]
                ),
                itemFlow=_entry_flow(
                    "experience-item",
                    ["companyName", "roleTitle"],
                    ["period", "location"],
                    ["companySummary", "bullets"],
                ),
            ),
            SemanticBlockV2(
                id="block-education",
                type="education",
                columnId="page-body-main",
                order=3,
                contentFlow=_single_column_flow(
                    "education-content", ["blockTitle", "groups"]
                ),
                itemFlow=_entry_flow(
                    "education-item",
                    ["universityName", "degree"],
                    ["date", "location"],
                    [],
                ),
            ),
        ],
    )


def dump_layout(layout: LayoutDocument) -> dict:
    """Canonical JSON form used by the API and immutable version rows."""

    return layout.model_dump(exclude_none=True)
