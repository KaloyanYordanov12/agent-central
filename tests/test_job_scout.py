"""Tests for Job Scout (commit 1) — discovery + filtering.

No real network: fetchers are exercised by patching the module-internal
_fetch() seam (real feedparser parses in-memory RSS bytes). Storage tests use a
real temp SQLite DB created via activity_log.init_db().
"""
import sqlite3

import pytest

from agent_central import activity_log, job_scout
from agent_central.job_scout import Job
from unittest.mock import patch


class FakeResp:
    """Minimal stand-in for httpx.Response used by the fetchers."""

    def __init__(self, content: bytes = b"", json_data=None, status_code: int = 200):
        self.content = content
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._json is None:
            raise ValueError("no JSON body")
        return self._json


def _db(tmp_path):
    db_path = str(tmp_path / "activity.db")
    activity_log.init_db(db_path)
    return db_path


def _rows(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM discovered_jobs")]
    finally:
        conn.close()


# --- apply_title_filters ------------------------------------------------------

def test_apply_title_filters_passes_junior_titles():
    for title in ["Junior Python Engineer", "Software Engineer",
                  "Entry Level Backend Developer"]:
        assert job_scout.apply_title_filters(Job("u", "s", title)) is None


def test_apply_title_filters_rejects_senior_titles():
    for title in ["Senior Python Engineer", "Staff Software Engineer",
                  "Principal Engineer", "Engineering Manager", "Sr. Backend Developer"]:
        assert job_scout.apply_title_filters(Job("u", "s", title)) is not None


def test_apply_title_filters_rejects_years_experience():
    assert job_scout.apply_title_filters(Job("u", "s", "Software Engineer (5+ years)")) is not None
    assert job_scout.apply_title_filters(Job("u", "s", "Engineer with 10 years experience")) is not None
    assert job_scout.apply_title_filters(Job("u", "s", "Backend Dev, 5 yrs required")) is not None


def test_apply_title_filters_rejects_non_tech_roles():
    # "Senior Sales Engineer" is caught by the Senior rule; "Marketing Manager"
    # by Manager — the non-tech list is a backstop.
    assert job_scout.apply_title_filters(Job("u", "s", "Senior Sales Engineer")) is not None
    assert job_scout.apply_title_filters(Job("u", "s", "Marketing Manager")) is not None
    assert job_scout.apply_title_filters(Job("u", "s", "Sales Development Representative")) is not None


# --- store_jobs ---------------------------------------------------------------

def test_store_jobs_inserts_new_rows(tmp_path):
    db = _db(tmp_path)
    jobs = [
        Job("u1", "remotive", "Junior Developer"),
        Job("u2", "remoteok", "Backend Engineer"),
        Job("u3", "aijobs", "Senior Developer"),
    ]
    job_scout.store_jobs(jobs, db)
    by_url = {r["url"]: r["status"] for r in _rows(db)}
    assert len(by_url) == 3
    assert by_url["u1"] == "discovered"
    assert by_url["u2"] == "discovered"
    assert by_url["u3"] == "rejected_by_filter"


def test_store_jobs_dedups_by_url(tmp_path):
    db = _db(tmp_path)
    job_scout.store_jobs([Job("dup", "remotive", "Developer")], db)
    stats = job_scout.store_jobs([Job("dup", "remotive", "Developer")], db)
    assert len(_rows(db)) == 1
    assert stats["new"] == 0  # second insert was a dedup no-op


def test_store_jobs_filter_marks_status(tmp_path):
    db = _db(tmp_path)
    job_scout.store_jobs([Job("u1", "s", "Junior Dev"), Job("u2", "s", "Lead Engineer")], db)
    by_url = {r["url"]: r for r in _rows(db)}
    assert by_url["u1"]["status"] == "discovered"
    assert by_url["u1"]["filter_reason"] is None
    assert by_url["u2"]["status"] == "rejected_by_filter"
    assert by_url["u2"]["filter_reason"]  # non-empty reason


# --- fetchers (patched _fetch, real parsing) ----------------------------------

def test_fetch_aijobs_parses_minimal_rss():
    rss = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>aijobs</title>
      <item>
        <title>Junior ML Engineer</title>
        <link>https://aijobs.net/job/1</link>
        <description>A nice junior role.</description>
        <pubDate>Mon, 02 Jun 2026 10:00:00 GMT</pubDate>
      </item>
    </channel></rss>"""
    with patch.object(job_scout, "_fetch", return_value=FakeResp(content=rss)):
        jobs = job_scout.fetch_aijobs()
    assert len(jobs) == 1
    assert jobs[0].url == "https://aijobs.net/job/1"
    assert jobs[0].title == "Junior ML Engineer"
    assert jobs[0].source == "aijobs"


def test_fetch_remotive_parses_minimal_json():
    data = {"jobs": [{
        "id": 7, "url": "https://remotive.com/job/7", "title": "Backend Engineer",
        "company_name": "Acme", "candidate_required_location": "Worldwide",
        "description": "Build APIs.", "publication_date": "2026-06-02T10:00:00",
        "category": "software-dev", "job_type": "full_time",
    }]}
    with patch.object(job_scout, "_fetch", return_value=FakeResp(json_data=data)):
        jobs = job_scout.fetch_remotive()
    assert len(jobs) == 1
    assert jobs[0].url == "https://remotive.com/job/7"
    assert jobs[0].company == "Acme"
    assert jobs[0].location == "Worldwide"
    assert jobs[0].source == "remotive"


def test_fetch_remoteok_skips_metadata_header():
    data = [
        {"legal": "See remoteok.com/api for terms"},  # metadata header — must be skipped
        {"id": "abc", "position": "Backend Developer", "company": "Globex",
         "location": "Remote", "url": "https://remoteok.com/l/abc",
         "date": "2026-06-02T10:00:00+00:00", "tags": ["python", "backend"]},
    ]
    with patch.object(job_scout, "_fetch", return_value=FakeResp(json_data=data)):
        jobs = job_scout.fetch_remoteok()
    assert len(jobs) == 1
    assert jobs[0].title == "Backend Developer"
    assert jobs[0].url == "https://remoteok.com/l/abc"
    assert jobs[0].source == "remoteok"


# --- run_scout_pass -----------------------------------------------------------

def test_run_scout_pass_continues_on_source_failure(tmp_path):
    db = _db(tmp_path)
    with patch.object(job_scout, "fetch_aijobs", side_effect=RuntimeError("boom")), \
         patch.object(job_scout, "fetch_remotive", return_value=[Job("u1", "remotive", "Junior Dev")]), \
         patch.object(job_scout, "fetch_remoteok", return_value=[Job("u2", "remoteok", "Backend Dev")]):
        stats = job_scout.run_scout_pass(db)
    assert stats["fetched"] == 2  # only the two sources that worked
    assert stats["new"] == 2
    assert len(_rows(db)) == 2


def test_run_scout_pass_records_stats(tmp_path):
    db = _db(tmp_path)
    with patch.object(job_scout, "fetch_aijobs", return_value=[Job("u1", "aijobs", "Junior Dev")]), \
         patch.object(job_scout, "fetch_remotive", return_value=[Job("u2", "remotive", "Senior Dev")]), \
         patch.object(job_scout, "fetch_remoteok", return_value=[Job("u3", "remoteok", "Backend Dev")]):
        stats = job_scout.run_scout_pass(db)
    assert set(stats.keys()) == {"fetched", "new", "filtered", "stored", "by_source"}
    assert stats["fetched"] == 3
    assert stats["new"] == 3
    assert stats["filtered"] == 1   # the "Senior Dev" one
    assert stats["stored"] == 2
    assert stats["by_source"] == {"aijobs": 1, "remotive": 1, "remoteok": 1}
