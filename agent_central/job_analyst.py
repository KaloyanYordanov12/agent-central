"""
Job Analyst (commit 2a) — LLM scoring + Discord notifications (backend only).

Takes jobs discovered by Job Scout (status 'discovered'), scores them against a
personal profile using Claude Haiku (with prompt caching on the profile system
prompt), records each call's token usage/cost, and posts Discord webhook
notifications for high-scoring matches. No UI (that's commit 2b).
"""
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx
import yaml

from agent_central import activity_log

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5"
MAX_TOKENS = 1024
DESCRIPTION_LIMIT = 4000   # bound JD text before sending to Claude (cost discipline)
REJECT_FLOOR = 25          # scores below this -> status 'rejected_by_llm'
DEFAULT_THRESHOLD = 75     # Discord-notify threshold


@dataclass
class Profile:
    name: str = ""
    background: str = ""
    languages: list = field(default_factory=list)
    frameworks: list = field(default_factory=list)
    domains: list = field(default_factory=list)
    level: str = ""
    looking_for: str = ""
    visa: str = ""
    strict_no: list = field(default_factory=list)


def load_profile(path: str) -> Profile:
    """Parse a profile YAML file into a Profile. Raises if the file is missing."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Profile(
        name=data.get("name", ""),
        background=data.get("background", ""),
        languages=data.get("languages") or [],
        frameworks=data.get("frameworks") or [],
        domains=data.get("domains") or [],
        level=data.get("level", ""),
        looking_for=data.get("looking_for", ""),
        visa=data.get("visa", ""),
        strict_no=data.get("strict_no") or [],
    )


def build_system_prompt(profile: Profile) -> str:
    """Build the (cached) system prompt that scores jobs against this profile."""
    def fmt(items):
        return ", ".join(str(i) for i in items) if items else "(none)"

    strict = "\n".join(f"  - {item}" for item in profile.strict_no) or "  (none)"
    return f"""You are a job-fit evaluator for one specific candidate. Score how well each job listing fits THIS person.

CANDIDATE PROFILE
Name: {profile.name}
Background: {profile.background}
Level: {profile.level}
Languages: {fmt(profile.languages)}
Frameworks: {fmt(profile.frameworks)}
Domains: {fmt(profile.domains)}
Looking for: {profile.looking_for}
Visa / work authorization: {profile.visa}
Hard no-gos (auto-low score if the role matches any of these):
{strict}

SCORING RULES
- Output a fit score from 0 to 100 (100 = perfect fit).
- Be STRICT on seniority and experience: this candidate is "{profile.level}". If the
  role clearly requires more experience or seniority than they have, score it under 25.
- Score under 25 if the role matches any hard no-go above.
- Reward strong overlap with the candidate's languages, frameworks, and domains.
- Factor in visa / work-authorization fit.

Return ONLY valid JSON, no prose, in exactly this shape:
{{
  "score": <integer 0-100>,
  "reasoning": "<one or two sentences>",
  "fit_notes": {{"stack": "<note>", "level": "<note>", "location": "<note>"}},
  "red_flags": ["<short flag>", "..."]
}}"""


def _parse_score_json(raw: str) -> dict:
    """Parse the model's JSON reply, tolerating ```-fenced output."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    data = json.loads(text)
    return {
        "score": int(data.get("score", 0)),
        "reasoning": str(data.get("reasoning", "")),
        "fit_notes": data.get("fit_notes") or {},
        "red_flags": data.get("red_flags") or [],
    }


class JobAnalystClient:
    """Anthropic SDK wrapper with prompt caching on the profile system prompt.

    Mirrors SecretaryClient's key handling: the API key is read from the
    environment at construction (request time), never at import.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL):
        import anthropic  # imported here so module import never needs a key

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set; Job Analyst cannot score jobs."
            )
        self.model = model
        self._client = anthropic.Anthropic(api_key=key)

    def score_job(self, profile_system_prompt: str, job: dict) -> dict:
        """Score one job. Returns {score, reasoning, fit_notes, red_flags, usage}."""
        user_text = (
            f"Job title: {job.get('title', '')}\n"
            f"Company: {job.get('company') or 'Unknown'}\n"
            f"Location: {job.get('location') or 'Unknown'}\n"
            f"Source: {job.get('source', '')}\n\n"
            f"Description:\n{(job.get('description') or '')[:DESCRIPTION_LIMIT]}"
        )
        # Cache the profile system prompt (GA in SDK 0.105.2; ttl '1h' is a typed
        # literal). If the live API needs an extra beta header for 1h TTL, this
        # call raises and the caller leaves the job 'discovered' to retry.
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=[{
                "type": "text",
                "text": profile_system_prompt,
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }],
            messages=[{"role": "user", "content": user_text}],
        )
        raw = resp.content[0].text if resp.content else ""
        parsed = _parse_score_json(raw)
        usage = getattr(resp, "usage", None)
        parsed["usage"] = {
            "input_tokens": getattr(usage, "input_tokens", 0) if usage else 0,
            "output_tokens": getattr(usage, "output_tokens", 0) if usage else 0,
            "cache_creation_tokens": (getattr(usage, "cache_creation_input_tokens", 0) or 0) if usage else 0,
            "cache_read_tokens": (getattr(usage, "cache_read_input_tokens", 0) or 0) if usage else 0,
        }
        return parsed


def process_pending_jobs(db_path: str, profile_system_prompt: str, client,
                         max_per_run: int = 20) -> dict:
    """Score up to max_per_run 'discovered' jobs; update status + log each call.

    Stats: {processed, scored, errors, high_score}. A scoring failure leaves the
    job 'discovered' (retried next pass) and is recorded as an llm_calls error.
    """
    stats = {"processed": 0, "scored": 0, "errors": 0, "high_score": 0}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT url, source, title, company, location, description "
            "FROM discovered_jobs WHERE status = 'discovered' "
            "ORDER BY discovered_at ASC LIMIT ?",
            (max_per_run,),
        ).fetchall()

        model = getattr(client, "model", DEFAULT_MODEL)
        for row in rows:
            job = {
                "url": row["url"],
                "source": row["source"],
                "title": row["title"],
                "company": row["company"],
                "location": row["location"],
                "description": (row["description"] or "")[:DESCRIPTION_LIMIT],
            }
            stats["processed"] += 1
            start = time.monotonic()
            try:
                result = client.score_job(profile_system_prompt, job)
            except Exception as e:
                stats["errors"] += 1
                activity_log.log_llm_call(
                    "job_analyst", model, "score_job", 0, 0,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    ok=False, error=str(e), metadata={"url": job["url"]},
                )
                logger.warning(f"[job_analyst] scoring failed for {job['url']}: {e}")
                continue  # leave status 'discovered' for the next pass

            usage = result.get("usage", {})
            activity_log.log_llm_call(
                "job_analyst", model, "score_job",
                usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                cache_creation_tokens=usage.get("cache_creation_tokens", 0),
                cache_read_tokens=usage.get("cache_read_tokens", 0),
                duration_ms=int((time.monotonic() - start) * 1000), ok=True,
                metadata={"url": job["url"], "score": result.get("score")},
            )

            score = int(result.get("score", 0))
            status = "rejected_by_llm" if score < REJECT_FLOOR else "scored"
            conn.execute(
                "UPDATE discovered_jobs SET status = ?, llm_score = ?, "
                "llm_reasoning = ?, llm_red_flags = ? WHERE url = ?",
                (status, score, result.get("reasoning", ""),
                 json.dumps(result.get("red_flags", [])), job["url"]),
            )
            conn.commit()
            stats["scored"] += 1
            if score >= DEFAULT_THRESHOLD:
                stats["high_score"] += 1
    finally:
        conn.close()
    return stats


def _post_discord(webhook_url: str, job: dict) -> None:
    reasoning = (job.get("llm_reasoning") or "")[:500]
    payload = {"embeds": [{
        "title": f"{job.get('title', '')} @ {job.get('company') or 'Unknown'}",
        "url": job.get("url"),
        "description": f"**Score: {job.get('llm_score')}/100**\n\n{reasoning}",
        "color": 0x00B8D4,
        "fields": [
            {"name": "Source", "value": job.get("source") or "?", "inline": True},
            {"name": "Location", "value": job.get("location") or "Unknown", "inline": True},
        ],
        "footer": {"text": "Agent Central — Job Analyst"},
        "timestamp": job.get("discovered_at"),
    }]}
    resp = httpx.post(webhook_url, json=payload, timeout=10.0)
    resp.raise_for_status()


def notify_high_scores(db_path: str, webhook_url: Optional[str],
                       threshold: int = DEFAULT_THRESHOLD) -> dict:
    """Post Discord notifications for scored jobs >= threshold not yet notified."""
    stats = {"notified": 0, "errors": 0}
    if not webhook_url:
        logger.warning("[job_analyst] no Discord webhook configured; skipping notifications")
        return stats

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM discovered_jobs WHERE status = 'scored' "
            "AND llm_score >= ? AND notified_at IS NULL ORDER BY llm_score DESC",
            (threshold,),
        ).fetchall()
        for row in rows:
            job = dict(row)
            try:
                _post_discord(webhook_url, job)
            except Exception as e:
                stats["errors"] += 1
                logger.warning(f"[job_analyst] discord post failed for {job['url']}: {e}")
                continue
            conn.execute(
                "UPDATE discovered_jobs SET notified_at = ?, status = 'notified' WHERE url = ?",
                (datetime.now(timezone.utc).isoformat(), job["url"]),
            )
            conn.commit()
            stats["notified"] += 1
    finally:
        conn.close()
    return stats


def run_analyst_pass(db_path: str, profile_path: str, webhook_url: Optional[str],
                     client, max_per_run: int = 20,
                     threshold: int = DEFAULT_THRESHOLD) -> dict:
    """Load profile -> score pending jobs -> notify high scores. Combined stats.

    The profile is reloaded each pass, so edits take effect on the next pass
    (no mtime tracking needed). Anthropic-side prompt caching (cache_control)
    is what saves cost across the per-job calls.
    """
    profile = load_profile(profile_path)
    system_prompt = build_system_prompt(profile)
    proc = process_pending_jobs(db_path, system_prompt, client, max_per_run=max_per_run)
    notif = notify_high_scores(db_path, webhook_url, threshold=threshold)
    return {
        "processed": proc["processed"],
        "scored": proc["scored"],
        "score_errors": proc["errors"],
        "high_score": proc["high_score"],
        "notified": notif["notified"],
        "notify_errors": notif["errors"],
    }
