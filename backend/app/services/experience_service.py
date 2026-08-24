"""Experience extraction.

Job 1 (earlier role)  — the company chosen in Settings.
    Filter to that company, rank its challenges against the JD, take the
    best-matching product, pick top challenges from *different* projects,
    and generate exactly 6 bullets.

Job 2 (recent role)   — chosen automatically from FAANG companies.
    Rank challenges across all FAANG companies (excluding Job 1's company),
    take the single highest-scoring product globally, pick exactly 2 projects
    by their challenge scores, and generate exactly 8 bullets (4 per project).

Bullet generation goes through the configured AI provider; if that is
unavailable the challenges are rendered deterministically instead, so the
feature degrades rather than failing.
"""

import asyncio
import json
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator, Sequence

if TYPE_CHECKING:
    from app.services.deepseek import DeepSeekConversation

from sqlalchemy import func

from app.db import get_db
from app.schemas.experience_db import Challenge, ExperienceDatabase, ProductEntry, Project
from app.services import vector_search
from app.services.progress import progress

JOB1_BULLET_COUNT = 6
JOB2_BULLET_COUNT = 8
JOB2_PROJECT_COUNT = 2
SUMMARY_SENTENCES = 3


class ExperienceExtractionError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class ScoredChallenge:
    challenge: Challenge
    project: Project
    # The flat company/product entry this challenge belongs to.
    entry: ProductEntry
    score: float

    @property
    def company(self) -> str:
        return self.entry.company

    @property
    def product(self) -> str:
        return self.entry.product


@dataclass
class JobSelection:
    company: str
    product: str
    timeline: str = ""
    company_summary: str = ""
    projects: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    source_challenge_ids: list[str] = field(default_factory=list)


def _flatten(entries: Sequence[ProductEntry]) -> list[tuple[Challenge, Project, ProductEntry]]:
    rows: list[tuple[Challenge, Project, ProductEntry]] = []
    for entry in entries:
        for project in entry.projects:
            for challenge in project.challenges:
                if challenge.search_text():
                    rows.append((challenge, project, entry))
    return rows


def _rank(query: str, rows: Sequence[tuple], label: str = "") -> list[ScoredChallenge]:
    if not rows:
        return []
    import time as _time

    started = _time.monotonic()
    scores = vector_search.score_documents(query, [r[0].search_text() for r in rows])
    elapsed = _time.monotonic() - started

    scored = [
        ScoredChallenge(challenge=r[0], project=r[1], entry=r[2], score=s)
        for r, s in zip(rows, scores)
    ]
    scored.sort(key=lambda s: s.score, reverse=True)

    backend = vector_search.backend()
    progress.emit(
        label or "rank",
        f"Scored {len(rows)} challenges in {elapsed:.2f}s ({backend['mode']})",
        level="step",
        matches=[
            {
                "score": round(s.score, 4),
                "company": s.company,
                "product": s.product,
                "project": s.project.name,
                "id": s.challenge.id,
                "text": s.challenge.challenge[:90],
            }
            for s in scored[:8]
        ],
    )
    return scored


def _best_product(
    scored: Sequence[ScoredChallenge], min_projects: int = 1
) -> ProductEntry | None:
    """Highest-scoring product, judged by the sum of its top few challenges.

    Summing rather than taking a single best hit rewards a product with
    several genuinely strong matches over one with just one lucky challenge
    and nothing else behind it — a company with three solid 0.5s beats one
    with a single 0.9 and no other supporting evidence.

    `min_projects` filters to products that can actually satisfy the caller's
    project quota — Job 2 must yield exactly two projects, and the highest
    scoring product overall may only have one. Products meeting the quota are
    always preferred; the filter is relaxed only if none qualify, so a thin
    database still returns something rather than failing.
    """
    by_product: dict[tuple[str, str], list[ScoredChallenge]] = {}
    for item in scored:
        by_product.setdefault((item.company, item.product), []).append(item)

    def rank(candidates: dict[tuple[str, str], list[ScoredChallenge]]):
        best_key = None
        best_score = float("-inf")
        for key, items in candidates.items():
            top = sorted((i.score for i in items), reverse=True)[:3]
            total = sum(top)
            if total > best_score:
                best_score = total
                best_key = key
        return best_key

    eligible = {
        key: items
        for key, items in by_product.items()
        if len({i.project.name for i in items}) >= min_projects
    }
    best_key = rank(eligible) or rank(by_product)
    if best_key is None:
        return None
    return by_product[best_key][0].entry


def _select_job1(db: ExperienceDatabase, company_name: str, query: str) -> tuple[JobSelection, list[ScoredChallenge]]:
    canonical = db.find_company(company_name)
    if canonical is None:
        raise ExperienceExtractionError(
            f"The selected first company {company_name!r} is not in database.json."
        )

    company_entries = db.entries_for_company(canonical)
    progress.emit(
        "job1",
        f"Job 1 company: {canonical} — {len(company_entries)} product(s): "
        + ", ".join(e.product for e in company_entries),
        level="info",
    )

    # All products belonging to this company.
    scored = _rank(query, _flatten(company_entries), label="job1")
    if not scored:
        raise ExperienceExtractionError(
            f"{canonical} has no challenges in database.json to extract from."
        )

    entry = _best_product(scored)
    if entry is None:
        raise ExperienceExtractionError(f"No product found for {canonical}.")

    in_product = [s for s in scored if s.product == entry.product]
    progress.emit(
        "job1",
        f"Best product: {entry.product} ({entry.timeline}) — "
        f"{len(in_product)} challenges available",
        level="result",
    )

    # Prefer breadth: one challenge per project first, then fill by score.
    # A single project rarely evidences a whole role.
    picked: list[ScoredChallenge] = []
    seen_projects: set[str] = set()
    for item in in_product:
        if item.project.name not in seen_projects:
            picked.append(item)
            seen_projects.add(item.project.name)
        if len(picked) >= JOB1_BULLET_COUNT:
            break
    for item in in_product:
        if len(picked) >= JOB1_BULLET_COUNT:
            break
        if item not in picked:
            picked.append(item)

    selection = JobSelection(
        company=entry.company,
        product=entry.product,
        timeline=entry.timeline,
        company_summary=entry.summary,
        projects=sorted({p.project.name for p in picked}),
        source_challenge_ids=[p.challenge.id for p in picked],
    )
    return selection, picked


def _select_job2(db: ExperienceDatabase, exclude_company: str, query: str) -> tuple[JobSelection, list[ScoredChallenge]]:
    faang = db.faang_entries(exclude=exclude_company)
    if not faang:
        raise ExperienceExtractionError(
            "No FAANG company found in database.json for the most recent role. "
            "Add one of Google, Amazon, Meta, Netflix, Apple or Microsoft."
        )

    progress.emit(
        "job2",
        f"FAANG candidates (excluding {exclude_company}): "
        + ", ".join(f"{e.company}/{e.product}" for e in faang),
        level="info",
    )

    scored = _rank(query, _flatten(faang), label="job2")
    if not scored:
        raise ExperienceExtractionError("The FAANG companies have no challenges to extract from.")

    # Sum of scores per product near the top — an approximate view of the
    # signal _best_product actually decides on below (which sums each
    # product's own top 3, not this top-40 window).
    tally: dict[str, float] = {}
    for item in scored[:40]:
        key = f"{item.company}/{item.product}"
        tally[key] = tally.get(key, 0.0) + item.score
    progress.emit(
        "job2",
        "Product scores in top 40 matches",
        level="step",
        tally=[{"product": k, "score": round(v, 4)} for k, v in
               sorted(tally.items(), key=lambda kv: kv[1], reverse=True)],
    )

    # Require a product that can supply the two projects the spec calls for.
    entry = _best_product(scored, min_projects=JOB2_PROJECT_COUNT)
    if entry is None:
        raise ExperienceExtractionError("No FAANG product could be selected.")

    in_product = [
        s for s in scored if s.company == entry.company and s.product == entry.product
    ]
    progress.emit(
        "job2",
        f"Selected: {entry.company} / {entry.product} ({entry.timeline})",
        level="result",
    )

    # Exactly 2 projects, ranked by the sum of their challenge scores — a
    # project with several solid matches beats one with a single great hit
    # and nothing else, same reasoning as _best_product above.
    project_scores: dict[str, float] = {}
    for item in in_product:
        project_scores[item.project.name] = project_scores.get(item.project.name, 0.0) + item.score
    chosen_projects = [
        name for name, _ in sorted(project_scores.items(), key=lambda kv: kv[1], reverse=True)
    ][:JOB2_PROJECT_COUNT]
    progress.emit(
        "job2",
        f"Chose {len(chosen_projects)} project(s) by summed challenge score",
        level="step",
        projects=[
            {"project": name, "totalScore": round(project_scores[name], 4)}
            for name in sorted(project_scores, key=lambda n: project_scores[n], reverse=True)
        ],
        chosen=chosen_projects,
    )

    # Split the bullets across the chosen projects (4/4 for two projects).
    per_project = JOB2_BULLET_COUNT // max(1, len(chosen_projects))
    picked: list[ScoredChallenge] = []
    for project_name in chosen_projects:
        items = [s for s in in_product if s.project.name == project_name][:per_project]
        picked.extend(items)
    # Top up if a project had too few challenges to hit the quota.
    for item in in_product:
        if len(picked) >= JOB2_BULLET_COUNT:
            break
        if item not in picked and item.project.name in chosen_projects:
            picked.append(item)

    selection = JobSelection(
        company=entry.company,
        product=entry.product,
        timeline=entry.timeline,
        company_summary=entry.summary,
        projects=chosen_projects,
        source_challenge_ids=[p.challenge.id for p in picked],
    )
    return selection, picked


# --- bullet generation ------------------------------------------------------


def _sentence(*parts: str) -> str:
    text = ", ".join(p.strip().rstrip(".") for p in parts if p and p.strip())
    return (text[:1].upper() + text[1:] + ".") if text else ""


def _bullet_variants(item: ScoredChallenge) -> list[str]:
    """Bullets derivable from one challenge, best first.

    A challenge often carries two distinct, non-overlapping claims — what was
    done and what it was worth to the business — so it can legitimately yield
    two bullets without inventing anything.
    """
    c = item.challenge
    variants = [
        _sentence(c.action or c.challenge, c.achievement),
        _sentence(c.business_impact, c.seniority_indicator),
        _sentence(c.challenge, c.action),
    ]
    seen: set[str] = set()
    unique: list[str] = []
    for text in variants:
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            unique.append(text)
    return unique


def _deterministic_bullets(picked: Sequence[ScoredChallenge], count: int) -> list[str]:
    """Exactly `count` bullets from the picked challenges, where possible.

    Takes one bullet per challenge first (breadth), then draws additional
    variants from the highest-scoring challenges. Only ever restates facts that
    are already in the database — nothing is fabricated to hit the quota, so
    fewer than `count` is returned when the source genuinely lacks material.
    """
    variants = [_bullet_variants(p) for p in picked]
    bullets: list[str] = []
    depth = 0
    while len(bullets) < count:
        added = False
        for options in variants:
            if depth < len(options):
                bullets.append(options[depth])
                added = True
                if len(bullets) >= count:
                    break
        if not added:  # every challenge exhausted
            break
        depth += 1
    return bullets[:count]


def _parse_bullets(reply: str, wanted: int) -> list[str]:
    """Pull bullet lines out of a model reply, tolerating numbering/markers."""
    lines = []
    for raw in (reply or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^[-*•●◦▪▸]\s*", "", line)
        line = re.sub(r"^\d+[.)]\s*", "", line)
        # Skip headings the model may add ("Job 1:", "Bullets:").
        if len(line) < 25 and line.endswith(":"):
            continue
        if line:
            lines.append(line)
    return lines[:wanted]


async def _generate_bullets(
    chat: "DeepSeekConversation | None",
    picked: Sequence[ScoredChallenge],
    selection: JobSelection,
    job_description: str,
    count: int,
) -> tuple[list[str], str]:
    """Returns (bullets, generator) where generator is 'deepseek' or 'fallback'."""
    if not picked:
        return [], "fallback"

    facts = "\n\n".join(
        f"Challenge {i + 1}:\n"
        f"- Problem: {p.challenge.challenge}\n"
        f"- Action: {p.challenge.action}\n"
        f"- Achievement: {p.challenge.achievement}\n"
        f"- Business impact: {p.challenge.business_impact}\n"
        f"- Skills: {', '.join(p.challenge.skills_used)}\n"
        f"- Seniority: {p.challenge.seniority_indicator}"
        for i, p in enumerate(picked)
    )

    # The prompt is user-editable in Settings; fall back to the shipped default
    # if it has been blanked out.
    from app.services import settings_service

    template = (settings_service.get_settings().get("tailoringPrompt") or "").strip()
    if not template:
        template = settings_service.DEFAULT_TAILORING_PROMPT

    prompt = settings_service.render_template(
        template,
        {
            "count": count,
            "company": selection.company,
            "product": selection.product,
            "job_description": job_description[:4000],
            "achievements": facts,
        },
    )

    progress.emit(
        "generate",
        f"Generating {count} bullets for {selection.company} / {selection.product} "
        f"from {len(picked)} challenges…",
        level="step",
        sources=[p.challenge.id for p in picked],
    )

    if chat is None:
        return _deterministic_bullets(picked, count), "fallback"

    try:
        reply = await chat.ask(prompt)
        bullets = _parse_bullets(reply, count)
        if len(bullets) >= max(1, count // 2):
            if len(bullets) < count:
                # Top up from source rather than returning fewer than promised;
                # skip anything the model already covered.
                existing = {b.lower()[:40] for b in bullets}
                for extra in _deterministic_bullets(picked, count * 2):
                    if len(bullets) >= count:
                        break
                    if extra.lower()[:40] not in existing:
                        bullets.append(extra)
                        existing.add(extra.lower()[:40])
            progress.emit(
                "generate",
                f"DeepSeek returned {len(bullets)} bullets",
                level="result",
            )
            return bullets[:count], "deepseek"
        progress.emit(
            "generate",
            f"DeepSeek returned only {len(bullets)} usable lines — composing from source instead",
            level="warn",
        )
    except Exception as exc:  # noqa: BLE001 - provider unavailable or session expired
        progress.emit(
            "generate",
            f"AI generation unavailable ({type(exc).__name__}) — composing from database.json",
            level="warn",
        )

    return _deterministic_bullets(picked, count), "fallback"


# --- orchestration ----------------------------------------------------------


@asynccontextmanager
async def _chat_session() -> AsyncIterator["DeepSeekConversation | None"]:
    """One DeepSeek chat for the whole job, or None if it can't be opened.

    A missing or expired session must not fail the extraction — every step has a
    deterministic fallback — so a failed sign-in is reported and yields None.

    The class-level prompt lock is held for the whole conversation: the browser
    profile can only be opened once at a time, so two extractions must queue
    here rather than fight over the profile directory.
    """
    from app.services.deepseek import DeepSeekConversation, DeepSeekService

    lock = DeepSeekService._get_prompt_lock()
    async with lock:
        conversation = DeepSeekConversation()
        try:
            await conversation.start()
        except Exception as exc:  # noqa: BLE001 - expired session or no browser
            progress.emit(
                "session",
                f"DeepSeek unavailable ({type(exc).__name__}) — "
                "composing everything from database.json",
                level="warn",
            )
            yield None
            return

        progress.emit(
            "session",
            "Opened one DeepSeek chat for this job",
            level="step",
        )
        try:
            yield conversation
        finally:
            await conversation.close()


def _parse_skills_reply(reply: str) -> tuple[list[str], str]:
    """Pull 'Skills: a, b' and 'Mission: ...' out of the model's reply."""
    skills: list[str] = []
    mission = ""
    for line in (reply or "").splitlines():
        stripped = line.strip().lstrip("-*• ").strip()
        lowered = stripped.lower()
        if lowered.startswith("skills:"):
            skills = [
                s.strip()
                for s in stripped.split(":", 1)[1].replace(";", ",").split(",")
                if s.strip()
            ]
        elif lowered.startswith("mission:"):
            mission = stripped.split(":", 1)[1].strip()
    return skills[:15], mission


async def _extract_skills_and_mission(
    chat: "DeepSeekConversation | None",
    job_description: str,
    existing_mission: str,
) -> tuple[list[str], str]:
    """Step 1 of the pipeline: skills + mission from the job description.

    Falls back to an empty skill list on failure — the search query still works
    from the description text alone, just with less signal.
    """
    from app.services import settings_service

    prompt_template = settings_service.get_settings().get("skillsPrompt") or ""
    prompt = f"{prompt_template}\n\nJob Description:\n{job_description[:4000]}"

    progress.emit(
        "skills",
        f"Extracting skills and mission from a {len(job_description)}-character description…",
        level="step",
    )

    if chat is None:
        return [], existing_mission

    try:
        reply = await chat.ask(prompt)
        skills, mission = _parse_skills_reply(reply)
        if skills:
            progress.emit(
                "skills",
                f"Found {len(skills)} skills",
                level="result",
                skills=skills,
                preview=(mission or "")[:200],
            )
            return skills, existing_mission or mission
        progress.emit(
            "skills",
            "No skills parsed from the reply — ranking on the description text alone",
            level="warn",
        )
    except Exception as exc:  # noqa: BLE001 - provider unavailable
        progress.emit(
            "skills",
            f"Skill extraction unavailable ({type(exc).__name__}) — "
            "ranking on the description text alone",
            level="warn",
        )
    return [], existing_mission


def _clean_summary(reply: str) -> str:
    """Strip the wrapping a chat model tends to add around a one-paragraph answer."""
    text = (reply or "").strip()
    if not text:
        return ""

    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Drop markdown headings and any "Summary:" / "Professional Summary:"
        # label the model prefixed, keeping anything that followed on the line.
        if line.startswith("#"):
            continue
        stripped = line.lstrip("*-• ").strip()
        lowered = stripped.lower()
        for label in ("professional summary:", "summary:"):
            if lowered.startswith(label):
                stripped = stripped[len(label):].strip()
                break
        if stripped:
            lines.append(stripped)

    text = " ".join(lines)
    text = text.replace("**", "").strip()
    # Models often wrap the whole paragraph in quotes despite being told not to.
    if len(text) >= 2 and text[0] in "\"“'" and text[-1] in "\"”'":
        text = text[1:-1].strip()
    return text


async def _generate_summary(
    chat: "DeepSeekConversation | None",
    job1: JobSelection,
    job2: JobSelection,
    job_description: str,
    job_title: str,
) -> tuple[str, str]:
    """Step 4: a resume summary written from the bullets just generated.

    Returns (summary, source) where source is 'deepseek' or 'none'. There is no
    deterministic fallback: a summary is a claim about the candidate as a whole,
    and composing one from template text would be inventing that claim. When
    DeepSeek is unavailable the resume simply keeps the profile's own summary.
    """
    from app.services import settings_service

    bullets = [*job2.bullets, *job1.bullets]
    if not bullets:
        return "", "none"

    template = (settings_service.get_settings().get("summaryPrompt") or "").strip()
    if not template:
        template = settings_service.DEFAULT_SUMMARY_PROMPT

    companies = " and ".join(dict.fromkeys(c for c in (job2.company, job1.company) if c))
    prompt = settings_service.render_template(
        template,
        {
            "sentences": SUMMARY_SENTENCES,
            "job_title": job_title or "this role",
            "job_description": job_description[:4000],
            "companies": companies,
            "bullets": "\n".join(f"- {b}" for b in bullets),
        },
    )

    progress.emit(
        "summary",
        f"Writing the resume summary from {len(bullets)} bullets…",
        level="step",
    )

    if chat is None:
        progress.emit(
            "summary",
            "DeepSeek unavailable — keeping the profile's own summary",
            level="warn",
        )
        return "", "none"

    try:
        summary = _clean_summary(await chat.ask(prompt))
        if summary:
            progress.emit(
                "summary",
                f"Summary written ({len(summary.split())} words)",
                level="result",
                preview=summary,
            )
            return summary, "deepseek"
        progress.emit(
            "summary", "DeepSeek returned an empty summary", level="warn"
        )
    except Exception as exc:  # noqa: BLE001 - provider unavailable
        progress.emit(
            "summary",
            f"Summary generation failed ({type(exc).__name__}) — "
            "keeping the profile's own summary",
            level="warn",
        )
    return "", "none"


async def _generate_company_summary(
    chat: "DeepSeekConversation | None",
    selection: JobSelection,
    job_description: str,
    job_title: str,
) -> tuple[str, str]:
    """One summary per role, written right after that role's own bullets, in
    the same chat -- unlike _generate_summary, which speaks for the candidate
    as a whole, this describes only `selection`'s company/product so it can
    introduce that section of the resume.

    Returns (summary, source) where source is 'deepseek' or 'none'. Same
    reasoning as _generate_summary: no deterministic fallback, since this is a
    claim about the role. When it fails, the field keeps whatever the corpus
    or profile already had (see JobSelection.company_summary's own default).
    """
    from app.services import settings_service

    if not selection.bullets:
        return selection.company_summary, "none"

    template = (settings_service.get_settings().get("companySummaryPrompt") or "").strip()
    if not template:
        template = settings_service.DEFAULT_COMPANY_SUMMARY_PROMPT

    prompt = settings_service.render_template(
        template,
        {
            "sentences": SUMMARY_SENTENCES,
            "company": selection.company,
            "product": selection.product,
            "job_title": job_title or "this role",
            "job_description": job_description[:4000],
            "bullets": "\n".join(f"- {b}" for b in selection.bullets),
        },
    )

    progress.emit(
        "companySummary",
        f"Writing the {selection.company} section summary…",
        level="step",
    )

    if chat is None:
        progress.emit(
            "companySummary",
            "DeepSeek unavailable — keeping the existing company summary",
            level="warn",
        )
        return selection.company_summary, "none"

    try:
        summary = _clean_summary(await chat.ask(prompt))
        if summary:
            progress.emit(
                "companySummary",
                f"{selection.company} summary written ({len(summary.split())} words)",
                level="result",
                preview=summary,
            )
            return summary, "deepseek"
        progress.emit(
            "companySummary", "DeepSeek returned an empty company summary", level="warn"
        )
    except Exception as exc:  # noqa: BLE001 - provider unavailable
        progress.emit(
            "companySummary",
            f"Company summary generation failed ({type(exc).__name__}) — "
            "keeping the existing company summary",
            level="warn",
        )
    return selection.company_summary, "none"


def _role_payload(label: str, selection: JobSelection) -> dict[str, Any]:
    """One finished role, shaped for the console's result block."""
    return {
        "label": label,
        "company": selection.company,
        "product": selection.product,
        "timeline": selection.timeline,
        "companySummary": selection.company_summary,
        "projects": list(selection.projects),
        "bullets": list(selection.bullets),
    }


def _clean_title(reply: str) -> str:
    """One line, no wrapper. Chat models like to explain and to quote."""
    text = (reply or "").strip()
    for line in text.splitlines():
        candidate = line.strip().lstrip("*-# ").strip()
        if not candidate:
            continue
        # Drop a "Title:" label but keep whatever followed it on the line.
        for label in ("professional title:", "title:"):
            if candidate.lower().startswith(label):
                candidate = candidate[len(label):].strip()
                break
        candidate = candidate.replace("**", "").strip()
        if len(candidate) >= 2 and candidate[0] in "\"“'" and candidate[-1] in "\"”'":
            candidate = candidate[1:-1].strip()
        candidate = candidate.rstrip(".").strip()
        if candidate:
            # A model that ignores "output only the title" tends to write a
            # sentence. Anything that long is prose, not a headline.
            return candidate[:80]
    return ""


async def _generate_title(
    chat: "DeepSeekConversation | None",
    job1: JobSelection,
    job2: JobSelection,
    summary: str,
    current_title: str,
    job_description: str,
    job_title: str,
) -> tuple[str, str]:
    """Step 5: the resume headline, written once the summary exists.

    Returns (title, source) where source is 'deepseek' or 'none'. Like the
    summary there is no deterministic fallback -- a title is a claim about what
    the candidate is, and composing one from a template would be inventing it.
    When unavailable the resume keeps the profile's own title.
    """
    from app.services import settings_service

    bullets = [*job2.bullets, *job1.bullets]
    if not bullets:
        return "", "none"

    template = (settings_service.get_settings().get("titlePrompt") or "").strip()
    if not template:
        template = settings_service.DEFAULT_TITLE_PROMPT

    prompt = settings_service.render_template(
        template,
        {
            "job_title": job_title or "this role",
            "current_title": current_title or "(none set)",
            "job_description": job_description[:4000],
            "summary": summary,
            "bullets": "\n".join(f"- {b}" for b in bullets),
        },
    )

    progress.emit("title", "Writing the resume title…", level="step")

    if chat is None:
        progress.emit(
            "title", "DeepSeek unavailable — keeping the profile's own title", level="warn"
        )
        return "", "none"

    try:
        title = _clean_title(await chat.ask(prompt))
        if title:
            progress.emit("title", f"Title: {title}", level="result", preview=title)
            return title, "deepseek"
        progress.emit("title", "DeepSeek returned an empty title", level="warn")
    except Exception as exc:  # noqa: BLE001 - provider unavailable
        progress.emit(
            "title",
            f"Title generation failed ({type(exc).__name__}) — "
            "keeping the profile's own title",
            level="warn",
        )
    return "", "none"


def _build_revision_message(
    job1_bullets: Sequence[str],
    job2_bullets: Sequence[str],
    job1_company_summary: str,
    job2_company_summary: str,
    summary: str,
    revision_prompt: str,
) -> str:
    """One message: the resume content, then the user's revision instructions,
    then a fixed, non-editable request for a reply shaped so it can be parsed
    back out. Mirrors the existing precedent in _extract_skills_and_mission()
    of appending structured, non-editable content around a user-editable
    template, rather than substituting placeholders into it.
    """
    content = (
        "Here is my resume content.\n\n"
        f"Job 1 ({len(job1_bullets)} bullets):\n"
        + "\n".join(f"- {b}" for b in job1_bullets)
        + f"\n\nJob 1 Company Summary:\n{job1_company_summary}"
        + f"\n\nJob 2 ({len(job2_bullets)} bullets):\n"
        + "\n".join(f"- {b}" for b in job2_bullets)
        + f"\n\nJob 2 Company Summary:\n{job2_company_summary}"
        + f"\n\nSummary:\n{summary}\n\n---\n\n"
    )
    format_request = (
        "\n\nReply with the revised version in exactly this format, and "
        "nothing else (no preamble, no explanation) — keep exactly "
        f"{len(job1_bullets)} bullets in Job 1 and exactly {len(job2_bullets)} "
        "in Job 2:\n\nJob 1:\n- revised bullet\n- revised bullet\n...\n\n"
        "Job 1 Company Summary:\n...\n\nJob 2:\n- revised bullet\n...\n\n"
        "Job 2 Company Summary:\n...\n\nSummary:\n..."
    )
    return content + revision_prompt + format_request


# Tolerant of "Job 1:" / "Job1" / "JOB 1 -", any case, any amount of
# whitespace between label and colon — the model is asked for this exact
# shape, but chat models still drift on punctuation. The two company-summary
# sections are wrapped in their own optional (?:...)? group: they're new and
# easier for a model to drop from a now-five-section format than the original
# three ever were, and if that happens this must still match on job1/job2/
# summary alone rather than fail the whole reply over two missing extras.
_REVISION_SECTION_RE = re.compile(
    r"job\s*1\s*[:\-]?\s*(?P<job1>.*?)\s*"
    r"(?:job\s*1\s*company\s*summary\s*[:\-]?\s*(?P<job1_summary>.*?)\s*)?"
    r"job\s*2\s*[:\-]?\s*(?P<job2>.*?)\s*"
    r"(?:job\s*2\s*company\s*summary\s*[:\-]?\s*(?P<job2_summary>.*?)\s*)?"
    r"summary\s*[:\-]?\s*(?P<summary>.*)",
    re.IGNORECASE | re.DOTALL,
)


def _parse_revision_reply(
    reply: str, job1_count: int, job2_count: int
) -> tuple[list[str], list[str], str, str, str] | None:
    """Split a revision reply into (job1 bullets, job2 bullets, job1 company
    summary, job2 company summary, summary), or None when there isn't enough
    usable content to trust.

    Locates the labeled sections, then reuses the existing tolerant cleaners —
    _parse_bullets() and _clean_summary() — rather than reimplementing
    bullet/summary cleanup for a second time.

    Acceptance is still gated only on job1/job2 bullets and the overall
    summary, exactly as before this function grew two more fields: those three
    are the resume's core content, and the caller labels the whole run
    "chatgpt" based on them. The company summaries are extracted opportunistically
    alongside — a model that skips or garbles one of them (they're new, and a
    model can drift on a five-section format more easily than a three-section
    one) shouldn't discard an otherwise good bullets+summary revision. The
    caller applies each company summary only when it actually came back
    non-empty, keeping whatever it had otherwise.
    """
    text = (reply or "").replace("**", "")
    match = _REVISION_SECTION_RE.search(text)
    if not match:
        return None

    job1_bullets = _parse_bullets(match.group("job1"), job1_count)
    job2_bullets = _parse_bullets(match.group("job2"), job2_count)
    job1_company_summary = _clean_summary(match.group("job1_summary"))
    job2_company_summary = _clean_summary(match.group("job2_summary"))
    summary = _clean_summary(match.group("summary"))

    # Same acceptance bar _generate_bullets() already uses (line ~437): enough
    # of what was asked for to trust, not necessarily every last one — there
    # is no corpus to top up from here, unlike a first-generation bullet.
    job1_ok = len(job1_bullets) >= max(1, job1_count // 2)
    job2_ok = len(job2_bullets) >= max(1, job2_count // 2)
    if not (job1_ok and job2_ok and summary):
        return None

    return job1_bullets, job2_bullets, job1_company_summary, job2_company_summary, summary


async def _revise_with_chatgpt(
    job1_bullets: list[str],
    job2_bullets: list[str],
    job1_company_summary: str,
    job2_company_summary: str,
    summary: str,
) -> tuple[list[str], list[str], str, str, str, bool]:
    """Step 6, the pipeline's last step: a fresh ChatGPT chat revises the
    bullets, company summaries, and overall summary DeepSeek just wrote.

    Returns (job1_bullets, job2_bullets, job1_company_summary,
    job2_company_summary, summary, applied) — applied=False whenever ChatGPT
    isn't connected, the call fails, or the reply doesn't parse into
    something usable, in which case every field comes back unchanged. Like
    every other step here, this must never fail the extraction: a missing or
    broken revision just means the resume keeps DeepSeek's own text.

    The bullets and overall summary are still accepted or reverted together —
    generator is one value for the whole run, so a half-revised resume must
    not be labeled "chatgpt". Each company summary is applied independently
    of that (see _parse_revision_reply's docstring): a model that garbles the
    newer, extra company-summary sections shouldn't cost the resume an
    otherwise good bullets+summary revision, or vice versa.

    Must run after _chat_session()'s conversation has fully closed: ChatGPT
    and DeepSeek share one browser profile, and that block holds the
    profile's lock for its entire lifetime. Calling this from inside it would
    wait forever for a lock that only releases once the outer block exits.
    """
    if not job1_bullets or not job2_bullets or not summary:
        return job1_bullets, job2_bullets, job1_company_summary, job2_company_summary, summary, False

    from app.services import chatgpt, chatgpt_session, settings_service

    try:
        status = await chatgpt_session.verify_session()
    except Exception as exc:  # noqa: BLE001 - a status check must never crash extraction
        progress.emit(
            "revision",
            f"Could not check the ChatGPT session ({type(exc).__name__}) — "
            "keeping DeepSeek's bullets and summary",
            level="warn",
        )
        return job1_bullets, job2_bullets, job1_company_summary, job2_company_summary, summary, False

    if not status.get("connected"):
        progress.emit(
            "revision",
            "ChatGPT is not connected — keeping DeepSeek's bullets and "
            "summary. Connect ChatGPT in Settings to enable the final "
            "revision pass.",
            level="info",
        )
        return job1_bullets, job2_bullets, job1_company_summary, job2_company_summary, summary, False

    template = (settings_service.get_settings().get("revisionPrompt") or "").strip()
    if not template:
        template = settings_service.DEFAULT_REVISION_PROMPT

    message = _build_revision_message(
        job1_bullets, job2_bullets, job1_company_summary, job2_company_summary, summary, template
    )

    progress.emit(
        "revision",
        "Sending the resume to a new ChatGPT chat for final revision…",
        level="step",
    )

    try:
        reply = await chatgpt.ask(message)
        parsed = _parse_revision_reply(reply, len(job1_bullets), len(job2_bullets))
        if parsed is not None:
            new_job1, new_job2, new_job1_summary, new_job2_summary, new_summary = parsed
            progress.emit(
                "revision",
                f"ChatGPT revised {len(new_job1)} + {len(new_job2)} bullets, "
                "the company summaries, and the summary",
                level="result",
            )
            return (
                new_job1,
                new_job2,
                new_job1_summary or job1_company_summary,
                new_job2_summary or job2_company_summary,
                new_summary,
                True,
            )
        progress.emit(
            "revision",
            "ChatGPT's revision did not parse into usable bullets and a "
            "summary — keeping DeepSeek's version",
            level="warn",
        )
    except Exception as exc:  # noqa: BLE001 - provider unavailable or reply timed out
        progress.emit(
            "revision",
            f"ChatGPT revision failed ({type(exc).__name__}) — keeping "
            "DeepSeek's version",
            level="warn",
        )

    return job1_bullets, job2_bullets, job1_company_summary, job2_company_summary, summary, False


async def extract_experience(
    db: ExperienceDatabase,
    first_company: str,
    job_description: str,
    tech_skills: Sequence[str] | None = None,
    job_title: str = "",
    job_mission: str = "",
    current_title: str = "",
) -> dict[str, Any]:
    if not (first_company or "").strip():
        raise ExperienceExtractionError("Please select a First Company in Settings first.")

    backend = vector_search.backend()
    progress.emit(
        "start",
        f"Extracting experience for “{job_title or 'this role'}”",
        level="info",
        searchMode=backend["mode"],
        model=backend["model"],
    )
    if backend["mode"] != "semantic":
        progress.emit("start", backend["detail"] or "Semantic search unavailable", level="warn")

    # One chat for the whole job: skills, both sets of bullets and the summary
    # are four turns in the same conversation, so each prompt still has the
    # earlier ones in context. `chat` is None when DeepSeek is unreachable, and
    # every step falls back on its own rather than failing the extraction.
    async with _chat_session() as chat:
        # Step 1: derive skills and mission from the job description when the
        # caller hasn't supplied them. This used to be a separate button in the
        # Jobs table; folding it in keeps the pipeline traceable in one place.
        skills = list(tech_skills or [])
        mission = job_mission or ""
        if not skills and job_description.strip():
            skills, mission = await _extract_skills_and_mission(
                chat, job_description, mission
            )

        query = vector_search.build_query(
            skills, mission or job_description[:600], job_title
        )
        progress.emit(
            "query",
            "Built hybrid search query",
            level="step",
            skills=skills,
            query=query[:300],
        )

        # Off the event loop. Ranking calls sentence-transformers, which is
        # CPU-bound and loads a ~90MB model on first use — measured at 30s.
        # Run inline it froze the whole server for that long: every request,
        # including /health, waits behind it because nothing else can be
        # served while the loop is executing Python.
        job1_sel, job1_picked = await asyncio.to_thread(
            _select_job1, db, first_company, query
        )
        job2_sel, job2_picked = await asyncio.to_thread(
            _select_job2, db, first_company, query
        )

        job1_sel.bullets, gen1 = await _generate_bullets(
            chat, job1_picked, job1_sel, job_description, JOB1_BULLET_COUNT
        )
        job1_sel.company_summary, _ = await _generate_company_summary(
            chat, job1_sel, job_description, job_title
        )
        job2_sel.bullets, gen2 = await _generate_bullets(
            chat, job2_picked, job2_sel, job_description, JOB2_BULLET_COUNT
        )
        job2_sel.company_summary, _ = await _generate_company_summary(
            chat, job2_sel, job_description, job_title
        )

        # Step 4: the summary is written from the bullets that now exist.
        summary, summary_source = await _generate_summary(
            chat, job1_sel, job2_sel, job_description, job_title
        )

        # Step 5: the headline, which reads better once the summary is settled.
        generated_title, title_source = await _generate_title(
            chat, job1_sel, job2_sel, summary, current_title, job_description, job_title
        )

        turns = chat.turns if chat else 0

    # Step 6, run only now that DeepSeek's chat has fully closed and released
    # the shared browser profile — see the docstring on _revise_with_chatgpt.
    (
        job1_sel.bullets,
        job2_sel.bullets,
        job1_sel.company_summary,
        job2_sel.company_summary,
        summary,
        revised,
    ) = await _revise_with_chatgpt(
        job1_sel.bullets,
        job2_sel.bullets,
        job1_sel.company_summary,
        job2_sel.company_summary,
        summary,
    )

    progress.emit(
        "done",
        f"Finished: {len(job1_sel.bullets)} + {len(job2_sel.bullets)} bullets "
        f"({job1_sel.company} → {job2_sel.company})"
        + (f", summary, title, {turns} DeepSeek turns in 1 session" if turns else "")
        + (", revised by ChatGPT" if revised else ""),
        level="result",
        job1={"company": job1_sel.company, "product": job1_sel.product,
              "bullets": len(job1_sel.bullets)},
        job2={"company": job2_sel.company, "product": job2_sel.product,
              "bullets": len(job2_sel.bullets)},
        deepseekTurns=turns,
        # The full text, because the console is now the only place the finished
        # bullets are shown — the Jobs table no longer has an Experience column.
        extracted={
            "summary": summary,
            "roles": [
                _role_payload("Job 1 · first company", job1_sel),
                _role_payload("Job 2 · most recent", job2_sel),
            ],
        },
    )

    return {
        "job1": job1_sel.__dict__,
        "job2": job2_sel.__dict__,
        "summary": summary,
        "summarySource": summary_source,
        "title": generated_title,
        "titleSource": title_source,
        "search": vector_search.backend(),
        # 'fallback' on either half means the AI provider wasn't used, which the
        # UI surfaces rather than passing template text off as generated.
        # 'chatgpt' overrides both: it means the text actually on the resume
        # was revised by ChatGPT in step 6, regardless of which tier produced
        # the bullets it revised.
        "generator": (
            "chatgpt" if revised else ("deepseek" if gen1 == gen2 == "deepseek" else "fallback")
        ),
        # How many prompts shared the one chat; 0 means DeepSeek was unavailable.
        "deepseekTurns": turns,
        "extractedAt": _now(),
    }


# --- persistence ------------------------------------------------------------


# --- persistence ------------------------------------------------------------
#
# What used to be one JSON blob per job is now a run, its two roles, and their
# bullets. The dict the router returns is unchanged, so the frontend never sees
# the difference — but "which challenge produced this claim" and "how long did
# the run take" became queries instead of parsing exercises.


def _store_run(conn, job_row, payload: dict[str, Any]) -> None:
    from sqlalchemy import delete as sql_delete

    from app.ids import uuid7
    from app.models import (
        extraction_bullets,
        extraction_roles,
        extraction_runs,
        extraction_skills,
    )

    # One run per job: re-extracting replaces rather than accumulating, which
    # matches what the single-row upsert used to do.
    conn.execute(sql_delete(extraction_runs).where(extraction_runs.c.job_id == job_row.id))

    search = payload.get("search") or {}
    run_id = conn.execute(
        extraction_runs.insert()
        .values(
            id=uuid7(),
            job_id=job_row.id,
            user_id=job_row.user_id,
            state="succeeded",
            summary=payload.get("summary") or "",
            generated_title=payload.get("title") or "",
            generator=payload.get("generator") or "fallback",
            search_mode=search.get("mode") or "lexical",
            search_model=search.get("model") or "",
            provider_turns=int(payload.get("deepseekTurns") or 0),
            finished_at=func.now(),
        )
        .returning(extraction_runs.c.id)
    ).scalar_one()

    for slot in ("job1", "job2"):
        selection = payload.get(slot) or {}
        if not selection:
            continue
        role_id = conn.execute(
            extraction_roles.insert()
            .values(
                id=uuid7(),
                run_id=run_id,
                slot=slot,
                # The corpus still lives in database.json, so there is no row to
                # point at yet. The names carry the meaning until it moves.
                company_id=None,
                product_id=None,
                company_name=selection.get("company") or "",
                product_name=selection.get("product") or "",
                timeline=selection.get("timeline") or "",
                # `selection` is JobSelection.__dict__, so this is the
                # dataclass field's own snake_case name -- not "companySummary"
                # (the camelCase key used only in the API-facing payloads built
                # by _role_payload and build_tailored_data).
                company_summary=selection.get("company_summary") or "",
            )
            .returning(extraction_roles.c.id)
        ).scalar_one()

        bullets = [b for b in (selection.get("bullets") or []) if b]
        if bullets:
            conn.execute(
                extraction_bullets.insert(),
                [
                    {
                        "id": uuid7(),
                        "role_id": role_id,
                        "position": index,
                        "text": text_value,
                        "source_challenge_id": None,
                    }
                    for index, text_value in enumerate(bullets)
                ],
            )

    skills = [s for s in (payload.get("skills") or []) if s]
    if skills:
        conn.execute(
            extraction_skills.insert(),
            [
                {"run_id": run_id, "name": name, "position": index}
                for index, name in enumerate(dict.fromkeys(skills))
            ],
        )


def _load_run(conn, job_row) -> dict[str, Any] | None:
    from sqlalchemy import select

    from app.models import extraction_bullets, extraction_roles, extraction_runs

    run = conn.execute(
        select(extraction_runs)
        .where(extraction_runs.c.job_id == job_row.id)
        .order_by(extraction_runs.c.started_at.desc())
        .limit(1)
    ).first()
    if run is None:
        return None

    payload: dict[str, Any] = {
        "job1": {},
        "job2": {},
        "summary": run.summary,
        "summarySource": "deepseek" if run.summary else "none",
        "title": run.generated_title,
        "titleSource": "deepseek" if run.generated_title else "none",
        "search": {"mode": run.search_mode, "model": run.search_model or None,
                   "detail": None},
        "generator": run.generator,
        "deepseekTurns": run.provider_turns,
        "extractedAt": run.finished_at.isoformat() if run.finished_at else "",
    }

    for role in conn.execute(
        select(extraction_roles).where(extraction_roles.c.run_id == run.id)
    ):
        bullets = [
            r.text
            for r in conn.execute(
                select(extraction_bullets.c.text)
                .where(extraction_bullets.c.role_id == role.id)
                .order_by(extraction_bullets.c.position)
            )
        ]
        payload[role.slot] = {
            "company": role.company_name,
            "product": role.product_name,
            "timeline": role.timeline,
            "companySummary": role.company_summary,
            "projects": [],
            "bullets": bullets,
            "source_challenge_ids": [],
        }
    return payload


def save_experience(job_id: str, payload: dict[str, Any]) -> None:
    from app.services import job_store

    with get_db() as conn:
        job_row = job_store._find(conn, job_id)
        if job_row is None:
            # An extraction with no job to hang off cannot be stored now that
            # the foreign key is real. The caller already has the result.
            progress.emit(
                "done",
                "Extraction finished but the job is no longer stored, so it was not saved",
                level="warn",
            )
            return
        _store_run(conn, job_row, payload)


def get_experience(job_id: str) -> dict[str, Any] | None:
    from app.services import job_store

    with get_db() as conn:
        job_row = job_store._find(conn, job_id)
        if job_row is None:
            return None
        return _load_run(conn, job_row)


def all_experience() -> dict[str, dict[str, Any]]:
    """Every stored extraction, so the table can restore badges after reload."""
    from sqlalchemy import select

    from app.models import jobs as jobs_table

    out: dict[str, dict[str, Any]] = {}
    with get_db() as conn:
        for job_row in conn.execute(select(jobs_table)):
            found = _load_run(conn, job_row)
            if found is not None:
                out[str(job_row.id)] = found
    return out
