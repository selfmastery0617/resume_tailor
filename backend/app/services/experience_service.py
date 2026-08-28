"""Experience extraction.

Job 1 (earlier role)  — the company chosen in Settings.
    Filter to that company, rank its challenges against the JD, take the
    best-matching product, pick top challenges from *different* projects,
    and generate exactly 6 bullets.

Job 2 (recent role)   — chosen automatically from the rest of the corpus.
    Rank challenges across every other company in database.json (excluding
    Job 1's company), take the single highest-scoring product globally, pick
    exactly 2 projects by their challenge scores, and generate exactly 8
    bullets (4 per project).

Bullet generation goes through the configured AI provider; if that is
unavailable the challenges are rendered deterministically instead, so the
feature degrades rather than failing.
"""

import asyncio
import json
import re
import xml.etree.ElementTree as ET
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

# How much a challenge's own industry-similarity score counts toward its
# final ranking score -- see _rank(). The job's industry and each
# challenge's industry are embedded and compared independently of the main
# query/document text (a focused comparison, not diluted by everything else
# in both blobs), then blended in: final = (1-w)*overall + w*industry. 0.35
# is a deliberate, sizable weight -- industry can meaningfully swing which
# challenge wins -- without letting it alone decide: the other 65% still
# comes from the actual skills/mission/challenge-text match.
INDUSTRY_SIMILARITY_WEIGHT = 0.35

# Filled into the tailoring prompt's {role_order} placeholder (see
# DEFAULT_TAILORING_PROMPT in settings_service.py) so the model can tell
# these two calls, in the same chat, apart -- job1 is the earlier company,
# job2 the most recent, matching _select_job1()/_select_job2() below.
ROLE_ORDER_LABELS = {
    "job1": "Job 1 of 2 - the first, earlier company on this resume",
    "job2": "Job 2 of 2 - the most recent company on this resume",
}


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
    # This role's own headline, finalized by ChatGPT in _revise_with_chatgpt
    # (step 8) from _draft_titles' step-5 draft, alongside the overall
    # resume title. Rendered on the resume as-is, below the company name --
    # see build_tailored_data() in tailored_resume_service.py. Product name
    # is left off there for now.
    title: str = ""
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


def _rank(
    query: str,
    rows: Sequence[tuple],
    label: str = "",
    industry: str = "",
    industry_weight: float = INDUSTRY_SIMILARITY_WEIGHT,
) -> list[ScoredChallenge]:
    if not rows:
        return []
    import time as _time

    documents = [r[0].search_text() for r in rows]
    progress.emit(
        label or "rank",
        f"Combined search text for {len(documents)} challenges",
        level="info",
        documents=[
            {
                "id": challenge.id,
                "company": entry.company,
                "product": entry.product,
                "project": project.name,
                "text": text,
            }
            for (challenge, project, entry), text in zip(rows, documents)
        ],
    )

    started = _time.monotonic()
    scores = vector_search.score_documents(query, documents)
    elapsed = _time.monotonic() - started

    # A second, focused comparison: the job's industry embedded and scored
    # against each challenge's own industry field alone, independent of
    # everything else in the query/document text -- then blended into the
    # overall score (see INDUSTRY_SIMILARITY_WEIGHT). Only challenges that
    # actually have an industry set take part; the rest keep their plain
    # semantic score unchanged rather than being compared against "".
    industry_key = industry.strip()
    blended = 0
    if industry_key:
        industry_idx = [i for i, r in enumerate(rows) if r[0].industry.strip()]
        if industry_idx:
            industry_scores = vector_search.score_documents(
                industry_key, [rows[i][0].industry for i in industry_idx]
            )
            for i, industry_score in zip(industry_idx, industry_scores):
                scores[i] = (
                    (1 - industry_weight) * scores[i] + industry_weight * industry_score
                )
                blended += 1

    scored = [
        ScoredChallenge(challenge=r[0], project=r[1], entry=r[2], score=s)
        for r, s in zip(rows, scores)
    ]
    scored.sort(key=lambda s: s.score, reverse=True)

    backend = vector_search.backend()
    progress.emit(
        label or "rank",
        f"Scored {len(rows)} challenges in {elapsed:.2f}s ({backend['mode']})"
        + (f" — blended industry similarity into {blended} challenges' scores" if industry_key else ""),
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


def _select_job1(
    db: ExperienceDatabase,
    company_name: str,
    query: str,
    industry: str = "",
    industry_weight: float = INDUSTRY_SIMILARITY_WEIGHT,
) -> tuple[JobSelection, list[ScoredChallenge]]:
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
    scored = _rank(
        query, _flatten(company_entries), label="job1", industry=industry,
        industry_weight=industry_weight,
    )
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


def _select_job2(
    db: ExperienceDatabase,
    exclude_company: str,
    query: str,
    industry: str = "",
    industry_weight: float = INDUSTRY_SIMILARITY_WEIGHT,
) -> tuple[JobSelection, list[ScoredChallenge]]:
    candidates = db.entries_excluding(exclude_company)
    if not candidates:
        raise ExperienceExtractionError(
            "No other company found in database.json for the most recent role. "
            "Add at least one company besides the first."
        )

    progress.emit(
        "job2",
        f"Candidates (excluding {exclude_company}): "
        + ", ".join(f"{e.company}/{e.product}" for e in candidates),
        level="info",
    )

    scored = _rank(
        query, _flatten(candidates), label="job2", industry=industry,
        industry_weight=industry_weight,
    )
    if not scored:
        raise ExperienceExtractionError("The other companies have no challenges to extract from.")

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
        raise ExperienceExtractionError("No product could be selected for the most recent role.")

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
    """Pull bullet lines out of a model reply, tolerating numbering/markers.

    The marker strip requires trailing whitespace (\\s+, not \\s*) so it
    can't mistake a leading "*" that isn't actually a bullet marker for one
    (e.g. a stray asterisk right up against the first word) -- a real
    "- "/"* " marker always has a space after it. Keywords are marked with
    [brackets] (see _revise_with_chatgpt), which this strip never touches at
    all since "[" was never one of the marker characters.
    """
    lines = []
    for raw in (reply or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^[-*•●◦▪▸]\s+", "", line)
        line = re.sub(r"^\d+[.)]\s*", "", line)
        # Skip headings the model may add ("Job 1:", "Bullets:").
        if len(line) < 25 and line.endswith(":"):
            continue
        if line:
            lines.append(line)
    return lines[:wanted]


def _format_achievements(picked: Sequence[ScoredChallenge]) -> str:
    """Shared by _generate_bullets() and _build_companies_announcement() --
    same challenge facts, same shape, in both places."""
    return "\n\n".join(
        f"Challenge {i + 1}:\n"
        f"- Problem: {p.challenge.challenge}\n"
        f"- Action: {p.challenge.action}\n"
        f"- Achievement: {p.challenge.achievement}\n"
        f"- Business impact: {p.challenge.business_impact}\n"
        f"- Seniority: {p.challenge.seniority_indicator}"
        for i, p in enumerate(picked)
    )


def _build_companies_announcement(
    job1: JobSelection,
    job1_picked: Sequence[ScoredChallenge],
    job2: JobSelection,
    job2_picked: Sequence[ScoredChallenge],
) -> str:
    """Step 2: one message, right after skills, that lays out both companies
    and their challenges together before either one's bullets are asked for.

    Without this, the two per-company bullet prompts (_generate_bullets, each
    with its own {role_order} label) are the model's ONLY signal for which
    company is which -- it never sees them side by side. This message gives
    it that full picture once, up front, so "the first company" / "the most
    recent company" in every later prompt in this chat refers back to
    something it already has in context, not just a label repeated in
    isolation each time.
    """

    def block(label: str, selection: JobSelection, picked: Sequence[ScoredChallenge]) -> str:
        return (
            f"{label}: {selection.company} / {selection.product}\n\n"
            f"{_format_achievements(picked)}"
        )

    return (
        "Here is the candidate's experience for this resume, both companies "
        "that will go on it, in order. In every prompt after this one, I'll "
        "refer to them as \"the first company\" and \"the most recent "
        "company\" -- keep track of which is which from here:\n\n"
        + block(ROLE_ORDER_LABELS["job1"], job1, job1_picked)
        + "\n\n---\n\n"
        + block(ROLE_ORDER_LABELS["job2"], job2, job2_picked)
        + "\n\nReply with just \"Ready.\" once you've reviewed both."
    )


async def _announce_companies(
    chat: "DeepSeekConversation | None",
    job1: JobSelection,
    job1_picked: Sequence[ScoredChallenge],
    job2: JobSelection,
    job2_picked: Sequence[ScoredChallenge],
) -> None:
    """Sends _build_companies_announcement() and moves on regardless of what
    comes back -- there's nothing to parse here, the point is only to put
    both companies in the chat's context before bullet generation starts.
    Like every other step, a failure here must not fail the extraction: the
    per-company prompts still carry their own achievements and {role_order}
    label, so losing this priming step just means slightly less context, not
    broken output.
    """
    if chat is None or (not job1_picked and not job2_picked):
        return

    progress.emit(
        "announce",
        "Introducing both companies and their challenges to the chat…",
        level="step",
    )
    try:
        await chat.ask(_build_companies_announcement(job1, job1_picked, job2, job2_picked))
    except Exception as exc:  # noqa: BLE001 - provider unavailable
        progress.emit(
            "announce",
            f"Could not send the company introduction ({type(exc).__name__}) — "
            "continuing without it",
            level="warn",
        )


async def _generate_bullets(
    chat: "DeepSeekConversation | None",
    picked: Sequence[ScoredChallenge],
    selection: JobSelection,
    job_description: str,
    count: int,
    role_key: str,
) -> tuple[list[str], str]:
    """Returns (bullets, generator) where generator is 'deepseek' or 'fallback'.

    role_key is "job1" or "job2" -- see ROLE_ORDER_LABELS, filled into the
    tailoring prompt's {role_order} so the model can tell which company this
    call is for when both calls share one chat.
    """
    if not picked:
        return [], "fallback"

    facts = _format_achievements(picked)

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
            "role_order": ROLE_ORDER_LABELS[role_key],
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
            # Nothing else logs what the reply actually said on this path, so a
            # bad-shaped reply (prose instead of a list, a refusal, ...) was
            # previously undiagnosable after the fact -- this is what it looked
            # like before parsing filtered it down to `bullets`.
            preview=reply[:300],
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


_EXTRACTION_XML_RE = re.compile(r"<extraction\b.*?</extraction\s*>", re.IGNORECASE | re.DOTALL)


def _parse_extraction_reply(reply: str) -> dict[str, str]:
    """Every field the skills-extraction prompt's <extraction> XML reply
    actually contains, keyed by its own tag name -- skills, mission,
    industry, and whatever else a future prompt edit adds reaches the
    query (see build_query in vector_search.py) with no code change here,
    since this just forwards whatever tags the model answered with rather
    than looking for specific ones. _BARE_AMPERSAND_RE (defined further
    below, alongside the resume XML parsing it was written for) pre-escapes
    a bare '&' the same way here -- skill/industry names commonly contain
    one (e.g. "Frameworks & Data Processing").
    """
    match = _EXTRACTION_XML_RE.search(reply or "")
    if not match:
        return {}
    try:
        root = ET.fromstring(_BARE_AMPERSAND_RE.sub("&amp;", match.group(0)))
    except ET.ParseError:
        return {}
    return {
        child.tag.strip().lower(): (child.text or "").strip()
        for child in root
        if child.tag and (child.text or "").strip()
    }


async def _extract_job_fields(
    chat: "DeepSeekConversation | None",
    job_description: str,
    existing_mission: str,
) -> dict[str, str]:
    """Step 1 of the pipeline: everything the skills-extraction prompt's XML
    reply contains (skills, mission, industry, ...), keyed by tag name.

    Falls back to an empty dict on failure — the search query still works
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
        return {"mission": existing_mission} if existing_mission else {}

    try:
        reply = await chat.ask(prompt)
        fields = _parse_extraction_reply(reply)
        skills = [s.strip() for s in fields.get("skills", "").split(",") if s.strip()]
        if skills:
            progress.emit(
                "skills",
                f"Found {len(skills)} skills",
                level="result",
                skills=skills,
                preview=(fields.get("mission") or "")[:200],
            )
            if existing_mission:
                fields["mission"] = existing_mission
            return fields
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
    return {"mission": existing_mission} if existing_mission else {}


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
        # Marker strip requires trailing whitespace, same reasoning as
        # _parse_bullets: a real "- "/"* " marker has a space after it, a
        # stray leading asterisk that isn't one doesn't.
        stripped = re.sub(r"^[*\-•]+\s+", "", line)
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
        "title": selection.title,
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
        # Drop a leading label ("Title:", "Professional Title:", "Whole
        # Profile Title:", ...) but keep whatever followed it on the line.
        # Whitelisting exact labels chases whatever wording a model happens
        # to invent (observed: "Whole Profile Title:", never asked for) --
        # any short, colon-terminated prefix is treated as one instead. Real
        # job titles essentially never start with "word(s):", so this is
        # safe in practice.
        candidate = re.sub(r"^[A-Za-z][\w /&-]{0,40}:\s*", "", candidate)
        candidate = candidate.replace("**", "").strip()
        if len(candidate) >= 2 and candidate[0] in "\"“'" and candidate[-1] in "\"”'":
            candidate = candidate[1:-1].strip()
        # A title-as-a-whole wrapped in [brackets] (observed: the keyword
        # marking pass treated the whole title as one keyword) doesn't mean
        # bold here the way it does in a bullet or the summary -- titles
        # don't render through RichText/parseBold, so a literal bracket
        # would otherwise show up in the PDF as-is.
        if len(candidate) >= 2 and candidate[0] == "[" and candidate[-1] == "]":
            candidate = candidate[1:-1].strip()
        candidate = candidate.rstrip(".").strip()
        if candidate:
            # A model that ignores "output only the title" tends to write a
            # sentence. Anything that long is prose, not a headline.
            return candidate[:80]
    return ""


def _build_titles_message(
    job1: JobSelection,
    job2: JobSelection,
    summary: str,
    current_title: str,
    job_description: str,
    job_title: str,
    title_prompt: str,
) -> str:
    """One message asking for all three titles at once -- the resume-wide
    headline and each company's own -- so drafting them costs one DeepSeek
    turn instead of three. Renders titlePrompt with the combined bullets
    (job2 first, most recent); titlePrompt's own rules already say what's
    wanted (one overall title, one per company), so no fixed format request
    is appended here. Nothing downstream parses this reply -- it's folded
    as unstructured text into what step 8 sends ChatGPT (see _draft_titles),
    which is what actually asks for -- and gets -- clean, separated lines.
    """
    from app.services import settings_service

    bullets = [*job2.bullets, *job1.bullets]
    return settings_service.render_template(
        title_prompt,
        {
            "job_title": job_title or "this role",
            "current_title": current_title or "",
            "job_description": job_description[:4000],
            "summary": summary,
            "bullets": "\n".join(f"- {b}" for b in bullets),
        },
    )


async def _draft_titles(
    chat: "DeepSeekConversation | None",
    job1: JobSelection,
    job2: JobSelection,
    summary: str,
    current_title: str,
    job_description: str,
    job_title: str,
) -> str:
    """Step 5: a first draft of all three headlines -- the resume-wide title
    and each company's own -- in ONE DeepSeek turn. Written once the summary
    exists so it can draw on it, same reasoning _generate_summary uses for
    reading the bullets first.

    Deliberately not parsed into three separate fields here. That used to be
    three separate calls sharing one prompt (once for the resume, once per
    company), then one call asking for all three at once and splitting the
    reply apart with a label-matching regex -- and models kept drifting on
    the label wording no matter how the request was worded (observed: the
    generic "Job 1 Title:" swapped for the literal company name instead).
    Rather than chase another label variant, this step's raw reply is folded
    as-is into what step 8 sends ChatGPT (_build_revision_message), which
    already has to produce reliable structured output for the bullets,
    summaries, and skill set -- asking it to also finalize the titles in
    that SAME structured reply (see _REVISION_SECTION_RE) means only one
    parse has to succeed, not two. This function's return value is that
    draft; _parse_revision_reply is what actually extracts the titles the
    resume ends up using (see _revise_with_chatgpt, and
    build_tailored_data() in tailored_resume_service.py for the fallback
    when even that never runs).

    Returns "" if there are no bullets yet, DeepSeek is unavailable, or the
    call fails -- an empty draft just means ChatGPT is asked to write the
    titles from scratch in step 8 rather than refine a draft.
    """
    from app.services import settings_service

    bullets = [*job2.bullets, *job1.bullets]
    if not bullets:
        return ""

    template = (settings_service.get_settings().get("titlePrompt") or "").strip()
    if not template:
        template = settings_service.DEFAULT_TITLE_PROMPT

    message = _build_titles_message(
        job1, job2, summary, current_title, job_description, job_title, template
    )

    progress.emit("title", "Drafting the resume and role titles…", level="step")

    if chat is None:
        progress.emit("title", "DeepSeek unavailable — no title draft", level="warn")
        return ""

    try:
        reply = await chat.ask(message)
        progress.emit("title", "Titles drafted", level="result", preview=reply[:300])
        return reply
    except Exception as exc:  # noqa: BLE001 - provider unavailable
        progress.emit(
            "title", f"Title drafting failed ({type(exc).__name__}) — no title draft", level="warn"
        )
        return ""


def _parse_skill_list(reply: str) -> list[str]:
    """A comma- or newline-separated list of skills -> deduped names, in the
    order the model gave them. Tolerant of either shape since the prompt
    asks for comma-separated but a model asked for "a list" sometimes writes
    one per line instead.
    """
    text = (reply or "").replace("**", "")
    seen: set[str] = set()
    skills: list[str] = []
    for part in re.split(r"[,\n]", text):
        name = part.strip().strip("-*•").strip()
        # Drop a "Skills:" label the model may prefix, and anything
        # implausibly long to be a single skill (a stray sentence, not a list).
        if name.lower().startswith("skills:"):
            name = name[len("skills:"):].strip()
        if not name or len(name) > 60:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        skills.append(name)
    return skills


async def _generate_skill_set(
    chat: "DeepSeekConversation | None",
    job1: JobSelection,
    job2: JobSelection,
    job_description: str,
    job_title: str,
) -> tuple[list[str], str]:
    """Step 6, the DeepSeek chat's last step: the resume's skill set, written
    from the bullets that now exist, before the chat closes and hands off to
    ChatGPT. Where it lands on the rendered resume is up to the template's
    own "skills" block placement, not this function.

    Returns (skills, source) where source is 'deepseek' or 'none'. Like the
    summary and title, there is no deterministic fallback: a skill set is a
    claim about the candidate, and composing one from a template would be
    inventing it. When DeepSeek is unavailable the resume keeps the
    profile's own skills (see build_tailored_data in
    tailored_resume_service.py).
    """
    from app.services import settings_service

    bullets = [*job2.bullets, *job1.bullets]
    if not bullets:
        return [], "none"

    template = (settings_service.get_settings().get("skillSetPrompt") or "").strip()
    if not template:
        template = settings_service.DEFAULT_SKILL_SET_PROMPT

    prompt = settings_service.render_template(
        template,
        {
            "job_title": job_title or "this role",
            "job_description": job_description[:4000],
            "bullets": "\n".join(f"- {b}" for b in bullets),
        },
    )

    progress.emit("skillSet", "Writing the resume skill set…", level="step")

    if chat is None:
        progress.emit(
            "skillSet",
            "DeepSeek unavailable — keeping the profile's own skills",
            level="warn",
        )
        return [], "none"

    try:
        skills = _parse_skill_list(await chat.ask(prompt))
        if skills:
            progress.emit(
                "skillSet",
                f"Skill set written ({len(skills)} skills)",
                level="result",
                preview=", ".join(skills),
            )
            return skills, "deepseek"
        progress.emit("skillSet", "DeepSeek returned an empty skill set", level="warn")
    except Exception as exc:  # noqa: BLE001 - provider unavailable
        progress.emit(
            "skillSet",
            f"Skill set generation failed ({type(exc).__name__}) — "
            "keeping the profile's own skills",
            level="warn",
        )
    return [], "none"


def _assemble_resume_content(
    job1_bullets: Sequence[str],
    job2_bullets: Sequence[str],
    job1_company_summary: str,
    job2_company_summary: str,
    summary: str,
    skill_set: Sequence[str],
) -> str:
    """The same structured shape _generate_whole_resume asks DeepSeek to
    produce (step 7), built here instead by plain string concatenation --
    the fallback used when that step is unavailable, fails, or its reply
    doesn't parse. Nothing is lost either way: every fact here already
    exists in the individually-generated fields regardless of which one
    produced the final text.
    """
    return (
        f"Job 1 ({len(job1_bullets)} bullets):\n"
        + "\n".join(f"- {b}" for b in job1_bullets)
        + f"\n\nJob 1 Company Summary:\n{job1_company_summary}"
        + f"\n\nJob 2 ({len(job2_bullets)} bullets):\n"
        + "\n".join(f"- {b}" for b in job2_bullets)
        + f"\n\nJob 2 Company Summary:\n{job2_company_summary}"
        + f"\n\nSummary:\n{summary}"
        + f"\n\nSkill Set:\n{', '.join(skill_set)}"
    )


def _build_whole_resume_message(whole_resume_prompt: str) -> str:
    """Step 7's message: unlike _build_revision_message (a FRESH ChatGPT
    chat with none of this in context), this runs in the SAME DeepSeek chat
    everything was already written in, so it doesn't repaste the bullets,
    summaries, or skill set -- just the user's own assembly instructions
    from the Profile page, sent exactly as written, with nothing appended
    (matching _build_revision_message and _build_keyword_message).
    """
    return whole_resume_prompt


async def _generate_whole_resume(
    chat: "DeepSeekConversation | None",
    job1: JobSelection,
    job2: JobSelection,
    summary: str,
    skill_set: Sequence[str],
) -> tuple[str, str]:
    """Step 7: DeepSeek assembles the complete resume content from
    everything already written in this chat -- both companies' bullets and
    summaries, the overall summary, the skill set -- into the same
    structured shape ChatGPT's revision step (and _parse_revision_reply)
    already expect, rather than that shape being built mechanically by
    _assemble_resume_content.

    Returns (resume_content, source) where source is 'deepseek' or 'none'.
    On failure, timeout, or an unparseable reply, returns ('', 'none') and
    the caller falls back to _assemble_resume_content -- nothing is lost,
    since every fact in what this step would produce already exists in
    job1/job2/summary/skill_set regardless of whether it runs.
    """
    from app.services import settings_service

    if not job1.bullets or not job2.bullets or not summary:
        return "", "none"

    template = (settings_service.get_settings().get("wholeResumePrompt") or "").strip()
    if not template:
        template = settings_service.DEFAULT_WHOLE_RESUME_PROMPT

    message = _build_whole_resume_message(template)

    progress.emit("assemble", "Assembling the complete resume from this chat…", level="step")

    if chat is None:
        progress.emit(
            "assemble",
            "DeepSeek unavailable — assembling the resume from the pieces already written",
            level="warn",
        )
        return "", "none"

    try:
        reply = await chat.ask(message)
        parsed = _parse_final_reply(
            reply, len(job1.bullets), len(job2.bullets), job1.company, job2.company
        )
        if parsed is not None:
            progress.emit("assemble", "Resume assembled", level="result")
            return reply, "deepseek"
        progress.emit(
            "assemble",
            "DeepSeek's assembly did not parse — assembling the resume "
            "from the pieces already written instead",
            level="warn",
            preview=reply[:300],
        )
    except Exception as exc:  # noqa: BLE001 - provider unavailable
        progress.emit(
            "assemble",
            f"Resume assembly failed ({type(exc).__name__}) — assembling "
            "the resume from the pieces already written instead",
            level="warn",
        )
    return "", "none"


def _build_revision_message(resume_content: str, revision_prompt: str) -> str:
    """One message: the resume content -- DeepSeek's own step-7 assembly, or
    _assemble_resume_content's programmatic fallback -- then the user's
    revision instructions from the Profile page, exactly as written. No
    fixed format request is appended here -- only the content and the
    prompt as edited, nothing added to it.

    Because nothing here asks ChatGPT to reply in the labeled shape
    _parse_revision_reply looks for, that parse will often fail and this
    step will often come back as applied=False, keeping DeepSeek's own
    text -- see _revise_with_chatgpt's docstring. That's expected, not a
    bug to fix: this function sends only what's asked for.
    """
    return f"Here is my resume content.\n\n{resume_content}\n\n---\n\n{revision_prompt}"


def _build_keyword_message(keywords_prompt: str) -> str:
    """The revision step's follow-up, sent in the SAME chat right after the
    revision reply -- so unlike _build_revision_message, this does not repeat
    the resume content: ChatGPT still has the text it just wrote in context.
    Sends the user's keywordsPrompt from the Profile page exactly as
    written, with nothing appended -- no fixed format request. Whatever
    shape the reply comes back in, _parse_revision_reply's tolerant, no
    minimum-count matching (see its docstring) is what actually extracts it.
    """
    return keywords_prompt


def _label_variants(position: str, company: str) -> str:
    """Alternation of every wording a model might use for one position's
    plain section label. Models substitute unpredictably regardless of
    which is actually asked for -- observed, each in its own reply: the
    company name in place of "Job 1 Title"; the reverse, "Job 1" in place
    of the company name; and, with nothing in the prompt saying what to
    call each company's section at all, a literal unfilled template
    marker -- "<Job 2 Company name>:" verbatim, not a real label of any
    kind. Tolerating all three is more robust than insisting on one.
    """
    generic = rf"job\s*{position}"
    placeholder = rf"<\s*{generic}(?:\s*company)?(?:\s*name)?\s*>"
    alternatives = [generic, placeholder]
    company = company.strip()
    if company:
        alternatives.append(re.escape(company))
    return "(?:" + "|".join(alternatives) + ")"


def _revision_label_regex(job1_company: str, job2_company: str) -> re.Pattern:
    r"""One pattern, a named group per section label, used to locate every
    labeled section in a reply wherever it actually falls -- not a fixed
    expected sequence. Built per call, not precompiled at module level,
    because the label alternatives depend on which two companies this run
    is about.

    Without a format request telling it what order to answer in (see
    _build_revision_message), a model reorganizes freely -- observed
    directly: title/summary/skills first, most-recent company first,
    "Job 2 Company Summary" before Job 2's own bullets rather than after.
    A single sequential pattern assuming one fixed order fails the whole
    reply the moment the actual order differs, even though every section is
    right there. This finds each label independently instead; the caller
    (_split_labeled_sections) sorts the hits by where they actually land.

    More specific labels (a company's own "Company Summary" / "Title") are
    listed before that company's bare label, so a match at the same
    starting position prefers the specific one -- alternation tries
    left-to-right and stops at the first success, so this ordering is what
    keeps "Job 2 Company Summary" from being claimed by the bare "Job 2"
    pattern instead.

    Every alternative is anchored to the start of a line (`^`, MULTILINE).
    Without that, a bare company name matches ANY mention of it anywhere in
    the reply -- including inside the summary's own prose, wrapped as a
    [keyword] (observed directly: "...across [Snowflake] and..." in the
    Summary section was mistaken for the "Snowflake:" heading itself, since
    it's literally the first occurrence of that word in the document). A
    real section heading always starts its own line; a `* bullet` mentioning
    the company mid-sentence never does, and neither does inline prose --
    so anchoring to line-start is what tells them apart. `\s*` after `^`
    allows leading spaces but not a bullet marker, so a bullet that happens
    to start with the company's name doesn't get mistaken for a heading
    either.

    The bare job1/job2 alternatives additionally consume the rest of their
    line up to a colon (`[^\n:]*`), not just the bare token -- a model
    sometimes expands the heading into a fuller name (observed: "Snowflake
    Data Cloud:" for a company whose corpus name is just "Snowflake").
    Without this, the match stops right after "Snowflake" and " Data
    Cloud:" is left dangling as if it were that company's own content,
    which then swallows the real title line right after it.
    """
    job1_label = _label_variants("1", job1_company)
    job2_label = _label_variants("2", job2_company)
    parts = [
        rf"^\s*(?P<job1_summary>{job1_label}\s*(?:company\s*)?summary\s*[:\-]?)",
        rf"^\s*(?P<job2_summary>{job2_label}\s*(?:company\s*)?summary\s*[:\-]?)",
        rf"^\s*(?P<job1_title>{job1_label}\s*title\s*[:\-]?)",
        rf"^\s*(?P<job2_title>{job2_label}\s*title\s*[:\-]?)",
        r"^\s*(?P<resume_title>resume\s*title\s*[:\-]?)",
        r"^\s*(?P<skill_set>skill\s*set\s*[:\-]?)",
        r"^\s*(?P<summary>summary\s*[:\-]?)",
        rf"^\s*(?P<job1>{job1_label}[^\n:]*[:\-]?)",
        rf"^\s*(?P<job2>{job2_label}[^\n:]*[:\-]?)",
    ]
    return re.compile("|".join(parts), re.IGNORECASE | re.MULTILINE)


def _split_labeled_sections(text: str, job1_company: str, job2_company: str) -> dict[str, str]:
    """Every labeled section found in `text`, keyed by field name, mapped to
    the text between that label and whichever label comes next in the
    reply -- in whatever order they actually appear. First occurrence of a
    given label wins if a model repeats one.
    """
    pattern = _revision_label_regex(job1_company, job2_company)
    hits = [
        (next(name for name, value in m.groupdict().items() if value is not None), m.start(), m.end())
        for m in pattern.finditer(text)
    ]
    sections: dict[str, str] = {}
    for i, (name, _start, end) in enumerate(hits):
        content_end = hits[i + 1][1] if i + 1 < len(hits) else len(text)
        if name not in sections:
            sections[name] = text[end:content_end].strip()
    return sections


_BULLET_LINE_RE = re.compile(r"^(?:[-*•●◦▪▸]\s+|\d+[.)]\s*)")


def _split_bullets_and_prose(text: str, count: int) -> tuple[list[str], str]:
    """Bullets and prose summary pulled from the SAME span, rather than
    assuming bullets and the company summary always land in separate,
    separately-labeled sections. Observed directly: a company's summary
    paragraph immediately followed by its bullets with nothing labeling
    where the bullets begin -- both ended up in that company's "Company
    Summary" section once split by label alone.

    Deliberately does NOT reuse _parse_bullets here, tempting as that
    looks: _parse_bullets treats any non-empty, non-heading line as a
    bullet, which is correct for a section that's ONLY ever bullets (its
    actual job everywhere else in this file) but wrong here, where a
    prose sentence and a `- bullet` line can sit in the same span --
    _parse_bullets would count the prose line as a bullet too (observed
    directly). A line only counts as a bullet here if it actually starts
    with a bullet or numbered-list marker; everything else is prose.
    """
    bullets: list[str] = []
    prose_lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if _BULLET_LINE_RE.match(line):
            cleaned = _BULLET_LINE_RE.sub("", line).strip()
            if cleaned:
                bullets.append(cleaned)
        elif len(line) < 25 and line.endswith(":"):
            continue  # a stray heading fragment, not prose either
        else:
            prose_lines.append(line)
    return bullets[:count], _clean_summary(" ".join(prose_lines))


def _extract_role_title_candidate(bare_span: str) -> tuple[str, str]:
    """If a company's bare-label span (before its "Company Summary" or
    "Title" section, if either exists) opens with a short, non-bullet line,
    treat that line as a candidate role title and split it off -- models
    sometimes write the title directly under the company name with no
    "Title:" label at all (observed: "Snowflake:\\n[Data Engineer]\\nJob 1
    Company Summary: ..."). An explicit "{company} Title:" section, when
    present, still wins over this candidate -- see _parse_revision_reply.

    Returns (title_candidate, remaining_text) -- title_candidate is "" when
    the first line doesn't look like a short standalone title (a bullet, or
    long enough to be prose), in which case remaining_text is bare_span
    unchanged.
    """
    lines = bare_span.splitlines()
    if not lines:
        return "", bare_span
    first = lines[0].strip()
    if first and len(first) <= 80 and not _BULLET_LINE_RE.match(first):
        return first, "\n".join(lines[1:])
    return "", bare_span


def _parse_skill_categories(text: str) -> list[tuple[str, list[str]]]:
    """"Category: skill, skill, skill" lines -> [(category, [skill, ...])].

    Skips any line without a colon (a heading or blank line the model added
    despite being asked not to) rather than failing the whole section over
    it -- same tolerant spirit as _parse_bullets.
    """
    groups: list[tuple[str, list[str]]] = []
    for raw in (text or "").replace("**", "").splitlines():
        line = re.sub(r"^[-*•●◦▪▸]\s+", "", raw.strip())
        if not line or ":" not in line:
            continue
        category, _, rest = line.partition(":")
        category = category.strip()
        # The category name itself is already rendered bold, through its
        # own dedicated path (SkillsContentBlock/SkillsSection in
        # frontend/src/resume/blocks.tsx), not through RichText/parseBold's
        # [bracket] convention -- so a category the keyword-marking pass
        # also wrapped in brackets (observed: "[Languages]:") would
        # otherwise show up with literal brackets in the PDF.
        if len(category) >= 2 and category[0] == "[" and category[-1] == "]":
            category = category[1:-1].strip()
        skills = [s.strip() for s in rest.split(",") if s.strip()]
        if category and skills:
            groups.append((category, skills))
    return groups


def _parse_revision_reply(
    reply: str, job1_count: int, job2_count: int, job1_company: str = "", job2_company: str = ""
) -> tuple[list[str], list[str], str, str, str, list[tuple[str, list[str]]], str, str, str] | None:
    """Split a revision reply into (job1 bullets, job2 bullets, job1 company
    summary, job2 company summary, summary, skill categories, resume title,
    job1 title, job2 title), or None when the reply has no structure to
    extract at all.

    Locates every labeled section independently, in whatever order they
    actually appear (see _split_labeled_sections) -- tolerant of the
    company's own name in place of "Job 1"/"Job 2" (see _label_variants).
    For each company, its bare-label span and its "Company Summary" span
    are combined before splitting into bullets vs. prose (see
    _split_bullets_and_prose), since which one actually holds the bullets
    varies. A title with no explicit "Title:" section falls back to a short
    first line under the bare label, if there is one (see
    _extract_role_title_candidate). Reuses the existing tolerant cleaners --
    _parse_bullets(), _clean_summary(), and _clean_title() -- rather than
    reimplementing that cleanup for a second time.

    Acceptance requires only that job1 or job2's bare label was found at
    all -- there's no minimum bullet count or "summary must be non-empty"
    bar on top of it. A reply with real structure is used as-is, however
    thin; there's no format request in the outgoing message anymore telling
    ChatGPT what shape or order to answer in (see _build_revision_message),
    so insisting on a specific count or sequence here would reject good
    revisions just as readily as bad ones. Missing pieces come back as
    empty values, and the caller (see _revise_with_chatgpt) already falls
    back to the pre-revision value for anything that comes back empty.
    """
    text = (reply or "").replace("**", "")
    sections = _split_labeled_sections(text, job1_company, job2_company)
    if "job1" not in sections and "job2" not in sections:
        return None

    job1_title_candidate, job1_bare = _extract_role_title_candidate(sections.get("job1", ""))
    job2_title_candidate, job2_bare = _extract_role_title_candidate(sections.get("job2", ""))

    job1_bullets, job1_company_summary = _split_bullets_and_prose(
        "\n".join(filter(None, [job1_bare, sections.get("job1_summary", "")])), job1_count
    )
    job2_bullets, job2_company_summary = _split_bullets_and_prose(
        "\n".join(filter(None, [job2_bare, sections.get("job2_summary", "")])), job2_count
    )
    summary = _clean_summary(sections.get("summary", ""))
    skill_groups = _parse_skill_categories(sections.get("skill_set", ""))
    resume_title = _clean_title(sections.get("resume_title", ""))
    job1_title = _clean_title(sections.get("job1_title", "")) or _clean_title(job1_title_candidate)
    job2_title = _clean_title(sections.get("job2_title", "")) or _clean_title(job2_title_candidate)

    return (
        job1_bullets, job2_bullets, job1_company_summary, job2_company_summary,
        summary, skill_groups, resume_title, job1_title, job2_title,
    )


_XML_BLOCK_RE = re.compile(r"<resume\b.*?</resume\s*>", re.IGNORECASE | re.DOTALL)

# A model asked for XML routinely writes a literal "&" -- in a skill
# category name ("Frameworks & Data Processing"), in prose ("R&D") -- rather
# than escaping it as "&amp;". That's invalid XML, and ElementTree rejects
# the WHOLE document over one stray character. Escapes any "&" that isn't
# already part of a recognized entity reference before parsing.
_BARE_AMPERSAND_RE = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")


def _xml_text(element: "ET.Element | None") -> str:
    return (element.text or "").strip() if element is not None else ""


def _normalize_company_name(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", name.strip().casefold())).strip()


def _find_company_element(root: "ET.Element", company: str) -> "ET.Element | None":
    """The <company name="..."> element matching `company`, tolerant of
    case and surrounding whitespace -- companies are named directly as an
    attribute here, so there's no "Job N vs. company name vs. placeholder"
    ambiguity to resolve the way the label-based parser has to (see
    _label_variants). ChatGPT sometimes expands or combines the name it was
    given (e.g. "Snowflake" comes back as "Snowflake / Snowflake Data
    Cloud"), so an exact match is tried first and a substring match (either
    direction) after, rather than losing the whole section over a name it
    embellished.
    """
    company_key = _normalize_company_name(company)
    if not company_key:
        return None
    experience = root.find("experience")
    if experience is None:
        return None
    candidates = experience.findall("company")
    for company_el in candidates:
        if _normalize_company_name(company_el.get("name") or "") == company_key:
            return company_el
    for company_el in candidates:
        name_key = _normalize_company_name(company_el.get("name") or "")
        if name_key and (company_key in name_key or name_key in company_key):
            return company_el
    return None


def _parse_resume_xml(
    reply: str, job1_count: int, job2_count: int, job1_company: str, job2_company: str
) -> tuple[list[str], list[str], str, str, str, list[tuple[str, list[str]]], str, str, str] | None:
    """Parse the <resume>...</resume> XML structure requested by the
    keywords prompt (see the Profile page's own keywordsPrompt -- this
    format is only produced when it's actually asked for there, not by
    DEFAULT_KEYWORDS_PROMPT, which is unrelated and untouched).

    Returns None on any parse failure -- no XML block found, malformed XML,
    or neither company present -- so the caller (_parse_final_reply) falls
    back to the tolerant label-based extraction instead (_parse_revision_reply).
    """
    match = _XML_BLOCK_RE.search(reply or "")
    if not match:
        return None
    try:
        root = ET.fromstring(_BARE_AMPERSAND_RE.sub("&amp;", match.group(0)))
    except ET.ParseError:
        return None

    job1_el = _find_company_element(root, job1_company)
    job2_el = _find_company_element(root, job2_company)
    if job1_el is None and job2_el is None:
        return None

    def bullets_of(company_el: "ET.Element | None", count: int) -> list[str]:
        if company_el is None:
            return []
        achievements = company_el.find("achievements")
        if achievements is None:
            return []
        return [
            (b.text or "").strip() for b in achievements.findall("bullet") if b.text and b.text.strip()
        ][:count]

    skill_groups: list[tuple[str, list[str]]] = []
    skill_set_el = root.find("skill_set")
    if skill_set_el is not None:
        for category_el in skill_set_el.findall("category"):
            name = (category_el.get("name") or "").strip()
            skills = [s.strip() for s in (category_el.text or "").split(",") if s.strip()]
            if name and skills:
                skill_groups.append((name, skills))

    return (
        bullets_of(job1_el, job1_count),
        bullets_of(job2_el, job2_count),
        _clean_summary(_xml_text(job1_el.find("company_summary")) if job1_el is not None else ""),
        _clean_summary(_xml_text(job2_el.find("company_summary")) if job2_el is not None else ""),
        _clean_summary(_xml_text(root.find("summary"))),
        skill_groups,
        _clean_title(_xml_text(root.find("resume_title"))),
        _clean_title(_xml_text(job1_el.find("title")) if job1_el is not None else ""),
        _clean_title(_xml_text(job2_el.find("title")) if job2_el is not None else ""),
    )


def _parse_final_reply(
    reply: str, job1_count: int, job2_count: int, job1_company: str = "", job2_company: str = ""
) -> tuple[list[str], list[str], str, str, str, list[tuple[str, list[str]]], str, str, str] | None:
    """Try the XML structure first (_parse_resume_xml) -- reliable once the
    keywords prompt has been set up to ask for it, since an explicit
    <company name="..."> attribute leaves nothing to guess -- falling back
    to the tolerant label-based extraction (_parse_revision_reply) for a
    reply that came back as plain labeled text instead, or from before the
    prompt asked for XML at all. Same return shape either way, so callers
    don't need to know or care which one actually matched.
    """
    xml_result = _parse_resume_xml(reply, job1_count, job2_count, job1_company, job2_company)
    if xml_result is not None:
        return xml_result
    return _parse_revision_reply(reply, job1_count, job2_count, job1_company, job2_company)


async def _revise_with_chatgpt(
    resume_content: str,
    job1_bullets: list[str],
    job2_bullets: list[str],
    job1_company_summary: str,
    job2_company_summary: str,
    summary: str,
    skill_set: list[str],
    job1_company: str,
    job2_company: str,
) -> tuple[list[str], list[str], str, str, str, list[tuple[str, list[str]]], str, str, str, bool]:
    """Step 8, the pipeline's last step: a fresh ChatGPT chat revises the
    bullets, company summaries, overall summary, and skill set -- DeepSeek's
    own step-7 assembly (resume_content, which also carries step 5's title
    draft along as unstructured text -- see extract_experience), sorting the
    flat skill list into categories and finalizing the titles into the same
    structured reply along the way -- then a second message in that SAME
    chat (step 8b) asks it to mark the main keywords by wrapping them in
    [square brackets] -- the PDF renders those bold (RichText/parseBold in
    frontend/src/resume/format.ts).

    Returns (job1_bullets, job2_bullets, job1_company_summary,
    job2_company_summary, summary, skill_groups, resume_title, job1_title,
    job2_title, applied) — applied=False only when ChatGPT isn't connected,
    the call fails outright, or the reply has no recognizable structure at
    all (see _parse_revision_reply). Once there's a structural match,
    applied=True and every field is taken from it independently -- any
    field that came back empty (the model found the heading but wrote
    nothing usable under it) falls back to the pre-revision value instead
    of overwriting good content with nothing, but that's a per-field
    substitution, not a reason to discard the run.

    There's no format request in the outgoing message telling ChatGPT what
    shape to answer in (see _build_revision_message), so this is
    deliberately permissive: a thin, partial, or oddly-labeled reply is
    still used rather than rejected, as long as SOMETHING matched. The
    keyword pass is applied the same way: if it fails or doesn't parse, the
    run keeps the (still successfully revised, still applied=True) un-marked
    text rather than reverting the whole revision over the keyword step
    alone.

    Must run after _chat_session()'s conversation has fully closed: ChatGPT
    and DeepSeek share one browser profile, and that block holds the
    profile's lock for its entire lifetime. Calling this from inside it would
    wait forever for a lock that only releases once the outer block exits.
    """
    if not job1_bullets or not job2_bullets or not summary:
        return (
            job1_bullets, job2_bullets, job1_company_summary, job2_company_summary,
            summary, [], "", "", "", False,
        )

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
        return (
            job1_bullets, job2_bullets, job1_company_summary, job2_company_summary,
            summary, [], "", "", "", False,
        )

    if not status.get("connected"):
        progress.emit(
            "revision",
            "ChatGPT is not connected — keeping DeepSeek's bullets and "
            "summary. Connect ChatGPT in Settings to enable the final "
            "revision pass.",
            level="info",
        )
        return (
            job1_bullets, job2_bullets, job1_company_summary, job2_company_summary,
            summary, [], "", "", "", False,
        )

    settings = settings_service.get_settings()

    template = (settings.get("revisionPrompt") or "").strip()
    if not template:
        template = settings_service.DEFAULT_REVISION_PROMPT

    message = _build_revision_message(resume_content, template)

    keywords_template = (settings.get("keywordsPrompt") or "").strip()
    if not keywords_template:
        keywords_template = settings_service.DEFAULT_KEYWORDS_PROMPT

    def build_keyword_followup(replies: list[str]) -> str | None:
        # Only worth asking to mark keywords in a reply that itself parsed
        # into something usable -- nothing sensible to mark otherwise, and
        # the outer parse below will already revert to DeepSeek's version.
        parsed = _parse_final_reply(
            replies[-1], len(job1_bullets), len(job2_bullets), job1_company, job2_company
        )
        if parsed is None:
            return None
        return _build_keyword_message(keywords_template)

    progress.emit(
        "revision",
        "Sending the resume to a new ChatGPT chat for final revision…",
        level="step",
    )

    try:
        replies = await chatgpt.ask_chained_turns(message, [build_keyword_followup])
        reply = replies[0]
        keyword_reply = replies[1] if len(replies) > 1 else ""

        progress.emit(
            "revision",
            "ChatGPT's revision reply:",
            level="info",
            preview=reply,
        )
        if keyword_reply:
            progress.emit(
                "revision",
                "ChatGPT's keyword-marking reply:",
                level="info",
                preview=keyword_reply,
            )

        parsed = _parse_final_reply(
            reply, len(job1_bullets), len(job2_bullets), job1_company, job2_company
        )
        if parsed is None:
            progress.emit(
                "revision",
                "ChatGPT's revision had no recognizable structure at all — "
                "keeping DeepSeek's version",
                level="warn",
            )
            return (
                job1_bullets, job2_bullets, job1_company_summary, job2_company_summary,
                summary, [], "", "", "", False,
            )

        (
            new_job1, new_job2, new_job1_summary, new_job2_summary, new_summary,
            skill_groups, resume_title, job1_title, job2_title,
        ) = parsed
        # A structural match with an empty section (the model found the
        # heading but wrote nothing bullet-shaped under it) falls back to
        # what was already there, same as every other field here -- there's
        # no format request telling ChatGPT what shape to answer in anymore
        # (see _build_revision_message), so a thin or malformed section is
        # expected sometimes, not a reason to lose real content over.
        new_job1 = new_job1 or job1_bullets
        new_job2 = new_job2 or job2_bullets
        new_job1_summary = new_job1_summary or job1_company_summary
        new_job2_summary = new_job2_summary or job2_company_summary
        new_summary = new_summary or summary

        keywords_marked = False
        if keyword_reply:
            keyword_parsed = _parse_final_reply(
                keyword_reply, len(new_job1), len(new_job2), job1_company, job2_company
            )
            if keyword_parsed is not None:
                (
                    marked_job1, marked_job2, marked_job1_summary, marked_job2_summary,
                    marked_summary, _, marked_resume_title, marked_job1_title, marked_job2_title,
                ) = keyword_parsed
                new_job1 = marked_job1 or new_job1
                new_job2 = marked_job2 or new_job2
                new_job1_summary = marked_job1_summary or new_job1_summary
                new_job2_summary = marked_job2_summary or new_job2_summary
                new_summary = marked_summary or new_summary
                resume_title = marked_resume_title or resume_title
                job1_title = marked_job1_title or job1_title
                job2_title = marked_job2_title or job2_title
                keywords_marked = True
            else:
                progress.emit(
                    "revision",
                    "Keyword marking did not parse — keeping the revision "
                    "without keywords marked",
                    level="warn",
                )

        progress.emit(
            "revision",
            f"ChatGPT revised {len(new_job1)} + {len(new_job2)} bullets, "
            "the company summaries, the summary"
            + (f", and sorted {sum(len(s) for _, s in skill_groups)} skills into "
               f"{len(skill_groups)} categories" if skill_groups else "")
            + (", finalized the titles" if resume_title else "")
            + (", with main keywords marked" if keywords_marked else ""),
            level="result",
        )
        return (
            new_job1, new_job2, new_job1_summary, new_job2_summary, new_summary,
            skill_groups, resume_title, job1_title, job2_title, True,
        )
    except Exception as exc:  # noqa: BLE001 - provider unavailable or reply timed out
        progress.emit(
            "revision",
            f"ChatGPT revision failed ({type(exc).__name__}) — keeping "
            "DeepSeek's version",
            level="warn",
        )

    return (
        job1_bullets, job2_bullets, job1_company_summary, job2_company_summary,
        summary, [], "", "", "", False,
    )


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

    # One chat for the whole job -- skills, both companies' bullets and
    # summaries, the overall summary, the titles, the skill set, and the
    # final whole-resume assembly (steps 1-7 below) all happen as turns in
    # the same conversation, so each prompt still has the earlier ones in
    # context. `chat` is None when DeepSeek is unreachable, and every step
    # falls back on its own rather than failing the extraction.
    async with _chat_session() as chat:
        # Step 1: derive skills, mission, and industry from the job
        # description when the caller hasn't supplied skills. This used to
        # be a separate button in the Jobs table; folding it in keeps the
        # pipeline traceable in one place.
        if tech_skills:
            fields: dict[str, str] = {"skills": ", ".join(tech_skills)}
            if job_mission:
                fields["mission"] = job_mission
        elif job_description.strip():
            fields = await _extract_job_fields(chat, job_description, job_mission or "")
        else:
            fields = {"mission": job_mission} if job_mission else {}
        if not fields.get("mission"):
            fields["mission"] = job_description[:600]

        skills = [s.strip() for s in fields.get("skills", "").split(",") if s.strip()]
        industry = fields.get("industry", "")

        from app.services import settings_service

        try:
            industry_weight = float(settings_service.get_settings().get("industryWeight") or "")
        except (TypeError, ValueError):
            industry_weight = INDUSTRY_SIMILARITY_WEIGHT

        query = vector_search.build_query(fields, job_title)
        progress.emit(
            "query",
            "Built hybrid search query",
            level="step",
            skills=skills,
            query=query,
        )

        # Off the event loop. Ranking calls sentence-transformers, which is
        # CPU-bound and loads a ~90MB model on first use — measured at 30s.
        # Run inline it froze the whole server for that long: every request,
        # including /health, waits behind it because nothing else can be
        # served while the loop is executing Python. `industry` blends an
        # industry-specific similarity into each selection's ranking, by
        # `industry_weight` -- the profile's own "Industry weight" slider on
        # the Profile page (falls back to INDUSTRY_SIMILARITY_WEIGHT when
        # nothing is stored yet).
        job1_sel, job1_picked = await asyncio.to_thread(
            _select_job1, db, first_company, query, industry, industry_weight
        )
        job2_sel, job2_picked = await asyncio.to_thread(
            _select_job2, db, first_company, query, industry, industry_weight
        )

        # Step 2: both companies' challenges, introduced together before
        # either one's bullets are asked for -- see _announce_companies.
        await _announce_companies(chat, job1_sel, job1_picked, job2_sel, job2_picked)

        # Step 3: each company's own bullets and section summary.
        job1_sel.bullets, gen1 = await _generate_bullets(
            chat, job1_picked, job1_sel, job_description, JOB1_BULLET_COUNT, "job1"
        )
        job1_sel.company_summary, _ = await _generate_company_summary(
            chat, job1_sel, job_description, job_title
        )
        job2_sel.bullets, gen2 = await _generate_bullets(
            chat, job2_picked, job2_sel, job_description, JOB2_BULLET_COUNT, "job2"
        )
        job2_sel.company_summary, _ = await _generate_company_summary(
            chat, job2_sel, job_description, job_title
        )

        # Step 4: the summary is written from the bullets that now exist.
        summary, summary_source = await _generate_summary(
            chat, job1_sel, job2_sel, job_description, job_title
        )

        # Step 5: a first draft of the headlines -- resume-wide and each
        # company's own, together in one turn (see _draft_titles) -- once
        # the summary is settled. Not parsed here; folded into what step 8
        # sends ChatGPT below, which is what actually finalizes them.
        titles_draft = await _draft_titles(
            chat, job1_sel, job2_sel, summary, current_title, job_description, job_title
        )

        # Step 6: the skill set, written in this chat, before it's all
        # assembled for handoff to ChatGPT.
        skill_set, skill_set_source = await _generate_skill_set(
            chat, job1_sel, job2_sel, job_description, job_title
        )

        # Step 7: DeepSeek assembles everything above into the complete
        # resume, still in this chat, before handoff to ChatGPT.
        whole_resume, whole_resume_source = await _generate_whole_resume(
            chat, job1_sel, job2_sel, summary, skill_set
        )

        turns = chat.turns if chat else 0

    # Falls back to the same content built programmatically when step 7
    # didn't produce something usable -- see _generate_whole_resume. The
    # title draft rides along as its own section regardless of which path
    # produced the rest -- see _draft_titles for why it's sent unparsed.
    resume_content = whole_resume or _assemble_resume_content(
        job1_sel.bullets, job2_sel.bullets, job1_sel.company_summary,
        job2_sel.company_summary, summary, skill_set,
    )
    if titles_draft:
        resume_content += (
            "\n\nDraft Titles (finalize these -- overall resume title "
            f"first, then each company's own):\n{titles_draft}"
        )

    # Step 8, run only now that DeepSeek's chat has fully closed and released
    # the shared browser profile — see the docstring on _revise_with_chatgpt.
    (
        job1_sel.bullets,
        job2_sel.bullets,
        job1_sel.company_summary,
        job2_sel.company_summary,
        summary,
        skill_groups,
        generated_title,
        job1_sel.title,
        job2_sel.title,
        revised,
    ) = await _revise_with_chatgpt(
        resume_content,
        job1_sel.bullets,
        job2_sel.bullets,
        job1_sel.company_summary,
        job2_sel.company_summary,
        summary,
        skill_set,
        job1_sel.company,
        job2_sel.company,
    )
    title_source = "chatgpt" if generated_title else "none"

    progress.emit(
        "done",
        f"Finished: {len(job1_sel.bullets)} + {len(job2_sel.bullets)} bullets "
        f"({job1_sel.company} → {job2_sel.company})"
        + (f", summary, {turns} DeepSeek turns in 1 session" if turns else "")
        + (", assembled by DeepSeek" if whole_resume else "")
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
        "skillSet": skill_set,
        "skillSetSource": skill_set_source,
        # ChatGPT's categorization of skill_set, or [] when it never ran or
        # didn't parse -- see build_tailored_data() in
        # tailored_resume_service.py, which falls back to the flat skillSet
        # (one uncategorized group) when this is empty.
        "skillGroups": [{"category": c, "skills": s} for c, s in skill_groups],
        "search": vector_search.backend(),
        # 'fallback' on either half means the AI provider wasn't used, which the
        # UI surfaces rather than passing template text off as generated.
        # 'chatgpt' overrides both: it means the text actually on the resume
        # was revised by ChatGPT in step 8, regardless of which tier produced
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
            # JSON, not plain comma-joined: needs to carry both the flat
            # DeepSeek list and ChatGPT's (possibly absent) categorization.
            skill_set=json.dumps(
                {
                    "flat": payload.get("skillSet") or [],
                    "groups": payload.get("skillGroups") or [],
                }
            ),
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
                title=selection.get("title") or "",
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

    try:
        skill_data = json.loads(run.skill_set) if run.skill_set else {}
    except ValueError:
        # Pre-dates the categorization feature: skill_set was a plain
        # comma-joined list rather than JSON.
        skill_data = {"flat": [s for s in run.skill_set.split(",") if s]} if run.skill_set else {}
    flat_skills = skill_data.get("flat") or []
    skill_groups = skill_data.get("groups") or []

    payload: dict[str, Any] = {
        "job1": {},
        "job2": {},
        "summary": run.summary,
        "summarySource": "deepseek" if run.summary else "none",
        "title": run.generated_title,
        "titleSource": "chatgpt" if run.generated_title else "none",
        "skillSet": flat_skills,
        "skillSetSource": "deepseek" if flat_skills else "none",
        "skillGroups": skill_groups,
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
            "title": role.title,
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
