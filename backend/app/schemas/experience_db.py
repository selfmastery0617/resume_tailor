"""Schema for database.json — the source of truth for experience challenges.

Canonical shape is a flat array of company+product entries:

    [
      {
        "company":  "Company Name",
        "product":  "Specific Product Name",
        "timeline": "YYYY - YYYY",
        "summary":  "One-sentence overview.",
        "projects": [ { "name", "description", "challenges": [ STAR... ] } ]
      }
    ]

A company with several products appears as several entries sharing one
`company` value; the dropdown reads the unique values.

An older nested form ({"companies": [{"name", "products": [...]}]}) is still
accepted on read and converted, so an existing file keeps working.
"""

from pydantic import BaseModel, ConfigDict, Field, ValidationError

# Used for the "Job 2" selection. Matched case-insensitively against company
# names, so "Google LLC" or "Meta Platforms" still resolve.
FAANG_COMPANIES: tuple[str, ...] = (
    "google",
    "amazon",
    "meta",
    "facebook",
    "netflix",
    "apple",
    "microsoft",
)


def is_faang(company_name: str) -> bool:
    name = (company_name or "").strip().lower()
    return any(brand in name for brand in FAANG_COMPANIES)


class Challenge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    challenge: str = ""
    action: str = ""
    achievement: str = ""
    business_impact: str = ""
    skills_used: list[str] = Field(default_factory=list)
    seniority_indicator: str = ""

    def search_text(self) -> str:
        """One string for the embedder: every field that carries signal."""
        return " ".join(
            part
            for part in (
                self.challenge,
                self.action,
                self.achievement,
                self.business_impact,
                " ".join(self.skills_used),
                self.seniority_indicator,
            )
            if part
        ).strip()


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    challenges: list[Challenge] = Field(default_factory=list)


class ProductEntry(BaseModel):
    """One element of the top-level array: a company/product pairing."""

    model_config = ConfigDict(extra="forbid")

    company: str
    product: str
    timeline: str = ""
    summary: str = ""
    projects: list[Project] = Field(default_factory=list)


class ExperienceDatabase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[ProductEntry] = Field(default_factory=list)

    def company_names(self) -> list[str]:
        """Unique company values in file order — this feeds the dropdown."""
        seen: set[str] = set()
        names: list[str] = []
        for entry in self.entries:
            name = entry.company.strip()
            key = name.lower()
            if name and key not in seen:
                seen.add(key)
                names.append(name)
        return names

    def entries_for_company(self, name: str) -> list[ProductEntry]:
        target = (name or "").strip().lower()
        return [e for e in self.entries if e.company.strip().lower() == target]

    def find_company(self, name: str) -> str | None:
        """The canonical spelling of a company, or None when absent."""
        matches = self.entries_for_company(name)
        return matches[0].company.strip() if matches else None

    def faang_entries(self, exclude: str | None = None) -> list[ProductEntry]:
        excluded = (exclude or "").strip().lower()
        return [
            e
            for e in self.entries
            if is_faang(e.company) and e.company.strip().lower() != excluded
        ]


class ExperienceDatabaseError(ValueError):
    """database.json failed validation, with a readable reason."""


def _readable(error: ValidationError) -> str:
    parts: list[str] = []
    for item in error.errors():
        location = ".".join(str(p) for p in item["loc"])
        message = item["msg"].removeprefix("Value error, ")
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts[:4]) or "Invalid database.json"


def _from_legacy_nested(companies: list) -> list[dict]:
    """Flatten {"companies":[{"name","products":[...]}]} into entries."""
    entries: list[dict] = []
    for company in companies:
        if not isinstance(company, dict):
            raise ExperienceDatabaseError("Each company must be an object")
        name = company.get("name", "")
        for product in company.get("products", []) or []:
            entries.append(
                {
                    "company": name,
                    "product": product.get("name", ""),
                    "timeline": product.get("timeline", ""),
                    "summary": product.get("summary", ""),
                    "projects": product.get("projects", []) or [],
                }
            )
    return entries


def validate_database(raw: object) -> ExperienceDatabase:
    """Parse the canonical array form, the legacy nested form, or {"entries": []}."""
    if isinstance(raw, list):
        payload = {"entries": raw}
    elif isinstance(raw, dict):
        if "entries" in raw:
            payload = {"entries": raw.get("entries") or []}
        elif "companies" in raw:
            payload = {"entries": _from_legacy_nested(raw.get("companies") or [])}
        else:
            raise ExperienceDatabaseError(
                "database.json must be an array of company/product entries"
            )
    else:
        raise ExperienceDatabaseError(
            "database.json must be an array of company/product entries"
        )

    try:
        return ExperienceDatabase(**payload)
    except ValidationError as exc:
        raise ExperienceDatabaseError(_readable(exc)) from exc


def to_canonical(db: ExperienceDatabase) -> list[dict]:
    """The database as the flat array the file should contain."""
    return [entry.model_dump() for entry in db.entries]
