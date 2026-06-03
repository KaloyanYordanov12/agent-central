"""
Job Scout (commit 1) — discovery + filtering.

Polls three public bulk job sources, applies hardcoded title-level filters to
drop obvious mismatches, and stores survivors (and filtered rows) in the
discovered_jobs table for a downstream agent (Job Analyst, commit 2) to score.

Discovery + filtering only: pure HTTP fetches + regex filters. No LLM calls, no
notifications. Network errors per source are caught so one bad source can't
break a pass.
"""
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "AgentCentralJobScout/1.0"
HEADERS = {"User-Agent": USER_AGENT}
HTTP_TIMEOUT = 30.0

AIJOBS_URL = "https://aijobs.net/feed/"
REMOTIVE_URL = "https://remotive.com/api/remote-jobs?category=software-dev"
REMOTEOK_URL = "https://remoteok.com/api"

# --- Title filters (hardcoded; see commit message smell about config-ifying) ---
# Explicit role words → reject (substring match on the lowercased title).
ROLE_PATTERNS = [
    "senior", "sr.", "sr ", "staff", "principal", "lead", "architect",
    "manager", "director", "head of", "vp", "chief",
]
# Non-tech roles that leak into tech aggregators (substring match).
NON_TECH_PATTERNS = ["sales", "marketing"]
# Experience requirements like "5 years", "5+ years", "5 yrs", "minimum 5 years".
YEARS_RE = re.compile(r"\d+\+?\s*(?:years?|yrs?)", re.IGNORECASE)


@dataclass
class Job:
    url: str
    source: str
    title: str
    company: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    posted_at: Optional[str] = None
    payload: dict = field(default_factory=dict)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch(url: str) -> httpx.Response:
    """Single HTTP GET. Isolated so tests can patch it (no real network calls)."""
    return httpx.get(url, headers=HEADERS, timeout=HTTP_TIMEOUT, follow_redirects=True)


# ----------------------------------------------------------------------------
# Fetchers — each returns [] on any failure (logged), never raises.
# ----------------------------------------------------------------------------
def fetch_aijobs() -> list[Job]:
    try:
        resp = _fetch(AIJOBS_URL)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as e:
        logger.warning(f"[job_scout] aijobs fetch failed: {e}")
        return []

    jobs = []
    for entry in feed.entries:
        url = entry.get("link")
        if not url:
            continue
        tags = [t.get("term") for t in entry.get("tags", []) if t.get("term")]
        jobs.append(Job(
            url=url,
            source="aijobs",
            title=entry.get("title", ""),
            company=entry.get("author") or None,
            location=None,
            description=entry.get("summary") or entry.get("description"),
            posted_at=entry.get("published") or entry.get("updated"),
            payload={"id": entry.get("id"), "tags": tags},
        ))
    return jobs


def fetch_remotive() -> list[Job]:
    try:
        resp = _fetch(REMOTIVE_URL)  # already scoped to ?category=software-dev
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"[job_scout] remotive fetch failed: {e}")
        return []

    jobs = []
    for item in data.get("jobs", []):
        url = item.get("url")
        if not url:
            continue
        jobs.append(Job(
            url=url,
            source="remotive",
            title=item.get("title", ""),
            company=item.get("company_name"),
            location=item.get("candidate_required_location"),
            description=item.get("description"),
            posted_at=item.get("publication_date"),
            payload={
                "id": item.get("id"),
                "category": item.get("category"),
                "job_type": item.get("job_type"),
            },
        ))
    return jobs


def fetch_remoteok() -> list[Job]:
    try:
        resp = _fetch(REMOTEOK_URL)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"[job_scout] remoteok fetch failed: {e}")
        return []

    if not isinstance(data, list):
        logger.warning("[job_scout] remoteok returned non-list payload; skipping")
        return []

    jobs = []
    for item in data[1:]:  # first element is a legal/metadata notice — skip it
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("apply_url")
        if not url:
            continue
        jobs.append(Job(
            url=url,
            source="remoteok",
            title=item.get("position") or item.get("title", ""),
            company=item.get("company"),
            location=item.get("location"),
            description=item.get("description"),
            posted_at=item.get("date"),
            payload={"id": item.get("id"), "tags": item.get("tags", [])},
        ))
    return jobs


# ----------------------------------------------------------------------------
# Filtering + storage
# ----------------------------------------------------------------------------
def apply_title_filters(job: Job) -> Optional[str]:
    """Return None if the job passes, else a short rejection reason string."""
    title = (job.title or "").lower()
    for pattern in ROLE_PATTERNS:
        if pattern in title:
            return f"title contains '{pattern.strip()}'"
    if YEARS_RE.search(title):
        return "title states a years-of-experience requirement"
    for pattern in NON_TECH_PATTERNS:
        if pattern in title:
            return f"title contains '{pattern}'"
    return None


def store_jobs(jobs: list[Job], db_path: str) -> dict:
    """Insert jobs into discovered_jobs (dedup by URL via INSERT OR IGNORE).

    Each new row gets status 'discovered' (passed filters) or
    'rejected_by_filter' (with filter_reason). Returns pass stats.
    """
    stats = {"fetched": len(jobs), "new": 0, "filtered": 0, "stored": 0, "by_source": {}}
    conn = sqlite3.connect(db_path)
    try:
        for job in jobs:
            reason = apply_title_filters(job)
            status = "rejected_by_filter" if reason else "discovered"
            cur = conn.execute(
                "INSERT OR IGNORE INTO discovered_jobs "
                "(url, source, title, company, location, description, posted_at, "
                " discovered_at, status, filter_reason, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.url, job.source, job.title, job.company, job.location,
                    job.description, job.posted_at, _now_iso(), status, reason,
                    json.dumps(job.payload or {}),
                ),
            )
            if cur.rowcount == 1:  # newly inserted (not a dedup conflict)
                stats["new"] += 1
                stats["by_source"][job.source] = stats["by_source"].get(job.source, 0) + 1
                if reason:
                    stats["filtered"] += 1
                else:
                    stats["stored"] += 1
        conn.commit()
    finally:
        conn.close()
    return stats


def run_scout_pass(db_path: str) -> dict:
    """Run all three fetchers (isolated per source), combine, and store."""
    jobs: list[Job] = []
    for name, fetcher in (
        ("aijobs", fetch_aijobs),
        ("remotive", fetch_remotive),
        ("remoteok", fetch_remoteok),
    ):
        try:
            jobs.extend(fetcher())
        except Exception:
            logger.exception(f"[job_scout] source '{name}' raised; continuing")

    stats = store_jobs(jobs, db_path)
    return stats
