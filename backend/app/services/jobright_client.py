import asyncio
import hashlib
import os
from pathlib import Path
from typing import Any, Callable, List, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from dotenv import load_dotenv

from app.schemas.job import JobListing

# load_dotenv() with no path searches upward from the process's *working
# directory*, not this file's location — it silently finds nothing when the
# app is launched with a different cwd (e.g. `--app-dir backend` from the
# project root). Anchor explicitly to backend/.env instead.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# This is an internal/undocumented endpoint reverse-engineered from browser
# devtools, not a published Jobright API. It authenticates via a session
# cookie (see JOBRIGHT_COOKIE below), not an API key, so it can break at any
# time if Jobright changes their frontend or session/anti-bot handling.
JOBRIGHT_BASE_URL = "https://jobright.ai"
JOBRIGHT_JOBS_PATH = "/swan/recommend/list/jobs"
JOBRIGHT_REFERER = "https://jobright.ai/jobs/recommend"

PAGE_SIZE = 10
MAX_FETCH_ATTEMPTS = 10
# A role filter throws most of a page away, so the pages needed to reach a
# limit are several times limit/PAGE_SIZE. The budget scales with what was
# asked for and stops there: without a ceiling a role that matches nothing
# would walk the whole feed.
PAGE_BUDGET_MULTIPLIER = 4
MAX_FETCH_ATTEMPTS_CEILING = 60
PAGE_DELAY_SECONDS = 2.0
RATE_LIMIT_BACKOFF_SECONDS = 10.0

# TODO: temporary cap for faster testing -- remove (or raise) once ready to
# pull the full recommendation feed.
# Default when a caller does not say. The import dialog always does.
MAX_JOBS_LIMIT = 10

# (scanned, matched, listing_or_None) — called as the feed is walked, so the UI
# can count progress and show rows as they arrive rather than after the lot.
ProgressCallback = Callable[[int, int, "JobListing | None"], None]
CancelCheck = Callable[[], bool]


def _title_matches(title: str, roles: Sequence[str] | None) -> bool:
    """Whether a job title matches any requested role.

    Substring, case-insensitive, on any of the roles: "Data Engineer" is meant
    to catch "Senior Data Engineer II" without anyone writing a pattern. No
    roles means everything matches.
    """
    wanted = [r.strip().casefold() for r in (roles or []) if r.strip()]
    if not wanted:
        return True
    haystack = (title or "").casefold()
    return any(role in haystack for role in wanted)


def _matches(
    listing: "JobListing",
    roles: Sequence[str] | None,
    exclude_companies: Sequence[str] | None,
) -> bool:
    excluded = {c.strip().casefold() for c in (exclude_companies or []) if c.strip()}
    if (listing.company or "").strip().casefold() in excluded:
        return False
    return _title_matches(listing.title, roles)


# Tracking/source params stripped from job apply links.
_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "source",
    "iis",
    "iisn",
    "trid",
    "gh_jid",
    "gh_src",
    "lang",
    "jobSite",
    "rb",
    "src",
}

_MOCK_LISTINGS = [
    JobListing(
        id="mock-1",
        title="Backend Engineer",
        company="Jobright Mock Co",
        location="Remote",
        url="https://jobright.ai/jobs/mock-1",
        salary="$120K - $150K",
        work_model="Remote",
        publish_time_desc="2 days ago",
        match_score="92",
        description=(
            "Build and maintain backend services powering our core platform, working closely with "
            "product and design to ship reliable APIs.\n\n"
            "Responsibilities:\n- Design and implement scalable backend services\n"
            "- Collaborate with product and design teams\n\n"
            "Must-Have Qualifications:\n- 3+ years of backend experience\n- Strong Python or Go skills\n\n"
            "Benefits:\n- Company paid medical, dental, and vision\n- Unlimited PTO"
        ),
    ),
    JobListing(
        id="mock-2",
        title="Frontend Developer",
        company="Sample Systems",
        location="San Francisco, CA",
        url="https://jobright.ai/jobs/mock-2",
        salary="$110K - $140K",
        work_model="Hybrid",
        publish_time_desc="1 day ago",
        match_score="88",
        description="Own the frontend experience for our flagship product, collaborating with designers to build accessible, performant UI.",
    ),
    JobListing(
        id="mock-3",
        title="Data Engineer",
        company="Fixture Analytics",
        location="Remote",
        url="https://jobright.ai/jobs/mock-3",
        salary="$130K - $160K",
        work_model="Remote",
        publish_time_desc="5 days ago",
        match_score="81",
        description="Design and operate data pipelines feeding our analytics and ML platforms at scale.",
    ),
    JobListing(
        id="mock-4",
        title="DevOps Engineer",
        company="Placeholder Cloud",
        location="Austin, TX",
        url="https://jobright.ai/jobs/mock-4",
        salary="$125K - $155K",
        work_model="Onsite",
        publish_time_desc="3 days ago",
        match_score="76",
        description="Manage CI/CD pipelines and cloud infrastructure, improving reliability and deployment speed across teams.",
    ),
    JobListing(
        id="mock-5",
        title="Product Manager",
        company="Stub Software",
        location="New York, NY",
        url="https://jobright.ai/jobs/mock-5",
        salary="$140K - $170K",
        work_model="Hybrid",
        publish_time_desc="6 hours ago",
        match_score="95",
        description="Drive product strategy and roadmap for our core platform, partnering with engineering and design.",
    ),
]


def _clean_job_url(url: str) -> str:
    """Strip tracking/source query params from a job apply link."""
    try:
        parts = urlsplit(url)
        kept_params = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key not in _TRACKING_PARAMS
        ]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept_params), parts.fragment))
    except ValueError:
        return url


def _compose_description(job_result: dict[str, Any]) -> str | None:
    """Assemble a full-length description from every text section Jobright's
    list/recommend endpoint provides.

    That endpoint doesn't return the original job posting's raw text (no such
    field exists in the payload — see jobResult's key list) — it's parsed
    into a short AI summary plus separate structured sections. This stitches
    those sections back together into one readable description instead of
    showing just the one-paragraph summary.
    """
    sections: list[str] = []

    summary = job_result.get("jobSummary")
    if summary:
        sections.append(summary)

    responsibilities = job_result.get("coreResponsibilities") or []
    if responsibilities:
        sections.append("Responsibilities:\n" + "\n".join(f"- {item}" for item in responsibilities))

    qualifications = job_result.get("qualifications") or {}

    must_have = qualifications.get("mustHave") or []
    if must_have:
        sections.append("Must-Have Qualifications:\n" + "\n".join(f"- {item}" for item in must_have))

    preferred_have = qualifications.get("preferredHave") or []
    if preferred_have:
        sections.append("Preferred Qualifications:\n" + "\n".join(f"- {item}" for item in preferred_have))

    why_join_us = job_result.get("whyJoinUs")
    if why_join_us:
        sections.append(f"Why Join Us:\n{why_join_us}")

    benefits = job_result.get("benefitsSummaries") or []
    if benefits:
        sections.append("Benefits:\n" + "\n".join(f"- {item}" for item in benefits))

    return "\n\n".join(sections) if sections else None


def _session_cookie() -> str | None:
    """The cookie harvested by the sign-in panel, if the user has used it.

    Imported lazily: jobright_session imports this module for its probe, and a
    module-level import would close the circle.
    """
    from app.services.jobright_session import stored_cookie

    return stored_cookie()


def _build_headers(cookie: str) -> dict[str, str]:
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9",
        "x-client-type": "web",
        "referer": JOBRIGHT_REFERER,
        "cookie": cookie,
        # httpx's default User-Agent ("python-httpx/x.y") is an easy bot
        # signal — send a browser-like one instead.
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
        ),
    }


class JobrightClient:
    """Client for fetching job listings from Jobright's personalized
    recommendation feed.

    Real mode calls an internal, undocumented endpoint
    (jobright.ai/swan/recommend/list/jobs) using a session cookie captured
    from a logged-in browser — there is no public Jobright API. This means:

    - It authenticates as *you*, not via a stable API key. Set the
      JOBRIGHT_COOKIE env var (see .env.example) to the raw `Cookie` header
      value from a browser devtools request to jobright.ai while logged in.
    - The cookie will expire and need to be refreshed periodically — there's
      no refresh-token flow for an internal endpoint like this.
    - It's a recommendation feed, not a search API — Jobright decides what
      jobs come back. The `query` param is applied as a client-side filter
      on top of whatever it returns, not sent to Jobright itself.
    """

    def __init__(self, cookie: str | None = None, mock_mode: bool | None = None) -> None:
        # A sign-in through the Jobright panel wins over the hand-copied
        # JOBRIGHT_COOKIE, which stays as a fallback so an existing .env setup
        # keeps working. Read per instance, not at import, so signing in takes
        # effect on the next import rather than the next restart.
        self.cookie = cookie or _session_cookie() or os.getenv("JOBRIGHT_COOKIE")

        if mock_mode is None:
            env_override = os.getenv("JOBRIGHT_MOCK_MODE")
            if env_override is not None:
                mock_mode = env_override.lower() != "false"
            else:
                # Default to mock mode until a cookie is configured.
                mock_mode = not self.cookie

        self.mock_mode = mock_mode

    async def fetch_jobs(
        self,
        query: str = "",
        roles: Sequence[str] | None = None,
        limit: int = MAX_JOBS_LIMIT,
        exclude_companies: Sequence[str] | None = None,
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelCheck | None = None,
    ) -> List[JobListing]:
        """Pull matching jobs from the recommendation feed.

        `roles` filters titles as they arrive, so paging can stop as soon as
        `limit` matches are found rather than after fetching everything. This
        is a client-side filter by necessity: the endpoint is a personalised
        feed, and there is no way to ask it for a role.

        `on_progress` is called with (scanned, matched, listing_or_None) as the
        feed is walked, so a caller can show progress and stream rows.
        """
        if self.mock_mode:
            listings = self._mock_jobs(query)
            listings = [j for j in listings if _matches(j, roles, exclude_companies)][:limit]
            for index, listing in enumerate(listings, start=1):
                if on_progress:
                    on_progress(index, index, listing)
            return listings

        raw_jobs = await self._fetch_all_raw_jobs(
            roles=roles,
            limit=limit,
            exclude_companies=exclude_companies,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )
        listings = [self._to_job_listing(job) for job in raw_jobs]

        if query:
            query_lower = query.lower()
            listings = [
                job
                for job in listings
                if query_lower in job.title.lower() or query_lower in job.company.lower()
            ]

        return listings

    async def _fetch_all_raw_jobs(
        self,
        roles: Sequence[str] | None = None,
        limit: int = MAX_JOBS_LIMIT,
        exclude_companies: Sequence[str] | None = None,
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelCheck | None = None,
    ) -> list[dict[str, Any]]:
        if not self.cookie:
            raise RuntimeError(
                "Not signed in to Jobright. Open the Jobright panel from the "
                "sidebar and sign in, or set the JOBRIGHT_COOKIE env var to a "
                "Cookie header copied from a logged-in browser request."
            )

        pages_allowed = min(
            MAX_FETCH_ATTEMPTS_CEILING,
            max(MAX_FETCH_ATTEMPTS, -(-limit // PAGE_SIZE) * PAGE_BUDGET_MULTIPLIER),
        )

        all_jobs: list[dict[str, Any]] = []
        seen_companies: set[str] = set()
        excluded = {c.strip().casefold() for c in (exclude_companies or []) if c.strip()}
        scanned = 0
        position = 0
        refresh = True
        fetch_attempts = 0

        async with httpx.AsyncClient(base_url=JOBRIGHT_BASE_URL, timeout=15.0) as client:
            while fetch_attempts < pages_allowed:
                if should_cancel and should_cancel():
                    break
                fetch_attempts += 1

                try:
                    response = await client.get(
                        JOBRIGHT_JOBS_PATH,
                        params={
                            "refresh": str(refresh).lower(),
                            "sortCondition": 2,
                            "position": position,
                            "count": PAGE_SIZE,
                            "syncRerank": "false",
                        },
                        headers=_build_headers(self.cookie),
                    )
                    response.raise_for_status()
                    data = response.json()
                except httpx.HTTPError:
                    # Mirrors the original script: a network/HTTP failure stops pagination entirely.
                    break

                refresh = False
                result = data.get("result") if isinstance(data, dict) else None
                job_list = result.get("jobList") if isinstance(result, dict) else None

                if not isinstance(job_list, list):
                    error_msg = str(data.get("errorMsg", "")).lower() if isinstance(data, dict) else ""
                    if "limit" in error_msg:
                        await asyncio.sleep(RATE_LIMIT_BACKOFF_SECONDS)
                        continue
                    break

                if not job_list:
                    break

                limit_reached = False
                for job in job_list:
                    job_result = job.get("jobResult") or {}
                    company_result = job.get("companyResult") or {}
                    company_title = company_result.get("companyName", "N/A")
                    job_link = _clean_job_url(job_result.get("applyLink", "N/A"))

                    scanned += 1

                    # One job per company, as before, and LinkedIn reposts are
                    # not applyable from here.
                    if company_title in seen_companies or "linkedin.com" in job_link:
                        continue
                    seen_companies.add(company_title)

                    if company_title.strip().casefold() in excluded:
                        if on_progress:
                            on_progress(scanned, len(all_jobs), None)
                        continue

                    if not _title_matches(job_result.get("jobTitle", ""), roles):
                        if on_progress:
                            on_progress(scanned, len(all_jobs), None)
                        continue

                    all_jobs.append(
                        {
                            "jobLink": job_link,
                            "companyTitle": company_title,
                            "jobTitle": job_result.get("jobTitle", "N/A"),
                            "displayScore": job.get("displayScore"),
                            "publishTimeDesc": job_result.get("publishTimeDesc"),
                            "publishTime": job_result.get("publishTime"),
                            "workModel": job_result.get("workModel"),
                            "salary": job_result.get("salaryDesc"),
                            "jobId": job_result.get("jobId"),
                            "location": job_result.get("jobLocation"),
                            "description": _compose_description(job_result),
                        }
                    )

                    if on_progress:
                        on_progress(scanned, len(all_jobs), self._to_job_listing(all_jobs[-1]))

                    if len(all_jobs) >= limit:
                        limit_reached = True
                        break

                if limit_reached:
                    break

                await asyncio.sleep(PAGE_DELAY_SECONDS)
                position += PAGE_SIZE

        return all_jobs

    @staticmethod
    def _to_job_listing(raw: dict[str, Any]) -> JobListing:
        job_id = raw.get("jobId") or hashlib.sha1(raw["jobLink"].encode("utf-8")).hexdigest()[:12]
        display_score = raw.get("displayScore")

        return JobListing(
            id=str(job_id),
            title=raw.get("jobTitle") or "N/A",
            company=raw.get("companyTitle") or "N/A",
            location=raw.get("location") or "N/A",
            url=raw.get("jobLink") or "N/A",
            salary=raw.get("salary"),
            work_model=raw.get("workModel"),
            publish_time=raw.get("publishTime"),
            publish_time_desc=raw.get("publishTimeDesc"),
            match_score=str(display_score) if display_score is not None else None,
            description=raw.get("description"),
        )

    @staticmethod
    def _mock_jobs(query: str) -> List[JobListing]:
        if not query:
            return list(_MOCK_LISTINGS)

        query_lower = query.lower()
        matches = [
            job
            for job in _MOCK_LISTINGS
            if query_lower in job.title.lower() or query_lower in job.company.lower()
        ]
        return matches or list(_MOCK_LISTINGS)
