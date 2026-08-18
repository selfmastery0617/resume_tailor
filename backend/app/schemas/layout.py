"""Template layout documents (template-builder step 1).

A user-created template is *data*: regions -> columns -> blocks. This module is
the contract for that data and the only place it is validated.

Validation runs server-side because a malformed layout would otherwise surface
as a broken PDF long after the fact, and because `customText` is the first place
template content is user-authored rather than source-controlled.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.schemas.style import validate_overrides

LAYOUT_VERSION = 1

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
    # A multi-column region cannot be split across pages in v1 (see the
    # pagination risk in docs/template-builder-plan.md); single-column regions
    # flow normally.
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

    version: int = Field(default=LAYOUT_VERSION, ge=1)
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


def validate_layout(raw: dict) -> TemplateLayout:
    """Parse and validate a layout document.

    Raises LayoutError with a message the API can hand straight back as a 400.
    """
    if not isinstance(raw, dict):
        raise LayoutError("Layout must be an object")
    try:
        return TemplateLayout(**raw)
    except ValidationError as exc:
        raise LayoutError(_readable(exc)) from exc


# A minimal starting point for "create new template", and the fixture the
# renderer tests build on.
def default_layout() -> TemplateLayout:
    return TemplateLayout(
        version=LAYOUT_VERSION,
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
