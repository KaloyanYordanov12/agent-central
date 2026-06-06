"""
=============================================================================
JOB ANALYST EVAL CASES  --  HUMAN-REVIEWABLE FIXTURE FILE
=============================================================================
Drafted by: Claude Code on Opus 4.8, at full effort.
Status: kept CLEAR-CUT. The correct CATEGORY of every case below is meant to be
        self-evident to any human given the candidate profile, so who drafted it
        stops mattering: its correctness is obvious on inspection.

WHY THIS IS HONEST (read before trusting the scorecard)
-------------------------------------------------------
The agents being graded (Job Analyst) run on Haiku; these cases were drafted on
Opus 4.8 (a stronger model judging a weaker one -- a legitimate technique). Two
rules keep it defensible:
  1. The ground truth is the CATEGORY / expected BAND, never a precise model-picked
     number. We never claim a job "is exactly a 78". We claim only that a plumbing
     job must score LOW for a software profile, and a junior remote Python/AI role
     must score HIGH. Those are obvious.
  2. Any case whose category is NOT obviously clear-cut is marked
     `needs_review=True` and listed below so a human (Kolio) reviews only those.
     A case a human has actually checked gets `human_reviewed=True`, which flips
     its provenance label from "model-drafted (Opus 4.8), clear-cut" to
     "human-reviewed".

CANDIDATE PROFILE these cases are clear-cut against (data/profile.yaml):
  Entry / Junior (0-2 yrs), self-taught software engineer focused on AI systems.
  Strong Python + JavaScript; FastAPI / pytest; AI agents, LLM integration, RAG,
  observability. Remote, AI-focused startups. EU citizen (no EU sponsorship need).
  Hard no-gos: senior+ roles, 3+ years required, B2B-contractor-only, unpaid
  trials, impossible relocation visas.

THE FOUR EXPECTED CATEGORIES
  'high'     -> LLM should score in [75, 100]. Clear strong match.
  'low'      -> LLM should score in [0, 24] (rejected_by_llm). Wrong field entirely.
  'filtered' -> Job Scout's title filter must reject it BEFORE the LLM (no spend).
  'deduped'  -> a duplicate URL must be deduped on store (no spend).
NOTE on behavior cases: 'filtered' and 'deduped' assert the system's ACTUAL,
existing behavior -- the title-pattern filter in job_scout.apply_title_filters
and the URL dedup in job_scout.store_jobs. We deliberately do NOT assert behaviors
the system does not have (e.g. there is no non-English language filter today), so
no check here can pass for a reason that is not really implemented.

CASES CURRENTLY FLAGGED FOR HUMAN REVIEW (needs_review=True):
  - se2_mid_level_ambiguous : "Software Engineer II" sits between junior and
       senior; the right band is genuinely arguable. Flagged.
  - spanish_junior_python   : a junior Python role posted in Spanish. On merit it
       matches, but there is no decided policy for non-English posts, so the
       expected category is not self-evident. Flagged.
Everything else is intended to be clear-cut. If you disagree with any "clear-cut"
case, set human_reviewed=True (and adjust) and it will relabel itself in the UI.
=============================================================================
"""
from dataclasses import dataclass, field


@dataclass
class AnalystCase:
    id: str
    title: str
    expected: str                 # 'high' | 'low' | 'filtered' | 'deduped'
    rationale: str                # why this category is clear-cut (for the reviewer)
    company: str = "Example Co"
    location: str = "Remote (EU)"
    source: str = "eval_fixture"
    description: str = ""
    needs_review: bool = False
    human_reviewed: bool = False
    url: str = ""

    def provenance(self) -> str:
        """Honest ground-truth label for this case (see file header)."""
        if self.human_reviewed:
            return "human-reviewed"
        return "model-drafted (Opus 4.8), clear-cut"

    def job_url(self) -> str:
        return self.url or f"https://example.com/eval/{self.id}"

    def as_job(self) -> dict:
        """Shape expected by JobAnalystClient.score_job."""
        return {
            "url": self.job_url(),
            "source": self.source,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# HIGH band: clear strong matches (junior, remote, Python/JS, AI). >= 75.
# ---------------------------------------------------------------------------
_HIGH = [
    AnalystCase(
        id="junior_python_ai_agents",
        title="Junior Python Engineer - AI Agents",
        expected="high",
        rationale="Junior, remote, Python + FastAPI, building AI agents/LLM apps: "
                  "hits the profile's level, stack, and domain dead-on.",
        description=(
            "We are an AI startup building autonomous agents. Looking for a JUNIOR "
            "Python engineer (0-2 years) to help build LLM-powered agent workflows "
            "with FastAPI. Fully remote across the EU. You will work on retrieval "
            "(RAG), tool use, and observability. No senior experience required; we "
            "mentor. Strong Python and some JavaScript a plus."
        ),
    ),
    AnalystCase(
        id="entry_backend_fastapi",
        title="Entry-Level Backend Developer (Python, FastAPI)",
        expected="high",
        rationale="Explicitly entry-level, Python + FastAPI, remote: core stack and "
                  "level match.",
        description=(
            "Entry-level backend role for a remote-first product team. Build REST "
            "APIs in Python with FastAPI, write tests with pytest. 0-2 years of "
            "experience welcome. Remote within Europe. We value eagerness to learn "
            "over years on a CV."
        ),
    ),
    AnalystCase(
        id="junior_llm_rag_engineer",
        title="Junior LLM / RAG Engineer",
        expected="high",
        rationale="Junior LLM/RAG engineering is the exact domain + level in the "
                  "profile.",
        description=(
            "Join a small team shipping LLM features. As a junior engineer you will "
            "build retrieval-augmented generation pipelines, integrate Claude/OpenAI "
            "models, and add observability. Python required, JavaScript helpful. "
            "Remote, full-time, suitable for someone early in their career."
        ),
    ),
    AnalystCase(
        id="associate_software_engineer_ai",
        title="Associate Software Engineer - Python (Remote AI Startup)",
        expected="high",
        rationale="Associate (junior) Python role at a remote AI startup: matches "
                  "level, stack, domain, and the 'AI startups preferred' preference.",
        description=(
            "Associate Software Engineer at a venture-backed AI startup. Python-first "
            "codebase, LLM integrations, distributed systems. Fully remote (EU "
            "friendly). Great fit for a self-taught engineer with 1-2 years of "
            "project experience. We sponsor learning, not seniority."
        ),
    ),
    AnalystCase(
        id="graduate_python_js_developer",
        title="Graduate Software Engineer - Python & JavaScript",
        expected="high",
        rationale="Graduate/junior, Python + JavaScript, remote EU: direct stack and "
                  "level match.",
        description=(
            "Graduate software engineer position, fully remote within the EU. Work "
            "across a Python (FastAPI) backend and a JavaScript frontend. Ideal for "
            "recent grads or self-taught developers with 0-2 years experience. "
            "Interest in AI/LLM tooling is a bonus."
        ),
    ),
]

# ---------------------------------------------------------------------------
# LOW band: wrong field entirely. Must reach the LLM and score < 25. Titles are
# deliberately NOT caught by the title filter, so the LOW score is the LLM's call.
# ---------------------------------------------------------------------------
_LOW = [
    AnalystCase(
        id="residential_plumber",
        title="Residential Plumber",
        expected="low",
        rationale="Plumbing is a different field entirely from junior AI software "
                  "engineering. Obvious low.",
        company="City Plumbing Services",
        location="Manchester, UK (on-site)",
        description=(
            "Hands-on residential plumber to install and repair piping, fixtures, "
            "and water systems in homes. Must hold a plumbing certification and have "
            "your own tools and vehicle. On-site work across the region."
        ),
    ),
    AnalystCase(
        id="registered_nurse",
        title="Registered Nurse - Pediatrics",
        expected="low",
        rationale="Healthcare/nursing has zero overlap with a software profile. "
                  "Obvious low.",
        company="Children's Hospital",
        location="Dublin, IE (on-site)",
        description=(
            "Registered nurse for our pediatric ward. Provide patient care, "
            "administer medication, and support families. Nursing degree and active "
            "license required. Shift work on-site."
        ),
    ),
    AnalystCase(
        id="long_haul_truck_driver",
        title="Long-Haul Truck Driver (CDL)",
        expected="low",
        rationale="Logistics/driving is wholly unrelated to software. Obvious low.",
        company="FreightLine Logistics",
        location="Poland (on the road)",
        description=(
            "Experienced long-haul driver with a valid CDL to transport goods across "
            "Europe. Long periods away from home. Clean driving record required. No "
            "office or computer work involved."
        ),
    ),
    AnalystCase(
        id="line_cook",
        title="Line Cook - Italian Restaurant",
        expected="low",
        rationale="Culinary work is a different field entirely. Obvious low.",
        company="Trattoria Bella",
        location="Rome, IT (on-site)",
        description=(
            "Line cook for a busy Italian kitchen. Prepare dishes to spec, maintain "
            "station cleanliness, work evenings and weekends. Culinary experience "
            "preferred. Fast-paced on-site role."
        ),
    ),
    AnalystCase(
        id="retail_store_associate",
        title="Retail Store Associate",
        expected="low",
        rationale="Retail floor work has no overlap with junior AI software. "
                  "Obvious low.",
        company="HighStreet Retail",
        location="Berlin, DE (on-site)",
        description=(
            "Friendly retail associate to greet customers, run the till, restock "
            "shelves, and keep the shop floor tidy. No technical skills needed. "
            "Weekend availability required."
        ),
    ),
]

# ---------------------------------------------------------------------------
# FILTERED behavior: Job Scout's title-pattern filter must reject these BEFORE
# any LLM call (so they cost nothing). Each title contains a documented pattern.
# ---------------------------------------------------------------------------
_FILTERED = [
    AnalystCase(
        id="filtered_senior_swe",
        title="Senior Software Engineer",
        expected="filtered",
        rationale="Title contains 'senior' -> a hard no-go that the title filter "
                  "rejects before scoring.",
        description="Senior backend role requiring deep experience.",
    ),
    AnalystCase(
        id="filtered_staff_platform",
        title="Staff Platform Engineer",
        expected="filtered",
        rationale="Title contains 'staff' -> filtered before scoring.",
        description="Staff-level platform engineering role.",
    ),
    AnalystCase(
        id="filtered_years_required",
        title="Backend Engineer - 5+ years experience",
        expected="filtered",
        rationale="Title states a years-of-experience requirement (matches the "
                  "years regex) -> filtered before scoring.",
        description="Backend engineer; the title itself demands 5+ years.",
    ),
    AnalystCase(
        id="filtered_sales_role",
        title="Sales Development Representative",
        expected="filtered",
        rationale="Title contains 'sales' (non-tech role that leaks into tech "
                  "aggregators) -> filtered before scoring.",
        description="Outbound sales role; not a software position.",
    ),
]

# ---------------------------------------------------------------------------
# DEDUPED behavior: a duplicate URL must be deduped on store (no second row).
# ---------------------------------------------------------------------------
_DEDUPED = [
    AnalystCase(
        id="deduped_same_url",
        title="Junior Python Engineer (duplicate posting)",
        expected="deduped",
        rationale="Storing the same URL twice must insert exactly one row; the "
                  "second store is a no-op dedup.",
        url="https://example.com/eval/deduped-fixed-url",
        description="A normal junior posting used to prove URL-based dedup.",
    ),
]

# ---------------------------------------------------------------------------
# NEEDS REVIEW: genuinely not-obviously-clear-cut. Flagged for a human (Kolio).
# Best-guess expected band is recorded, but it is explicitly uncertain.
# ---------------------------------------------------------------------------
_NEEDS_REVIEW = [
    AnalystCase(
        id="se2_mid_level_ambiguous",
        title="Software Engineer II",
        expected="low",
        rationale="'Engineer II' usually implies ~2-4 years, sitting between the "
                  "profile's junior level and the senior no-go. The right band is "
                  "arguable, so this is flagged for human review rather than guessed.",
        description=(
            "Software Engineer II on a Python backend team. Typically suits someone "
            "with a couple of years of professional experience. Remote within the EU."
        ),
        needs_review=True,
    ),
    AnalystCase(
        id="spanish_junior_python",
        title="Ingeniero Junior de Python (Remoto)",
        expected="high",
        rationale="On merit this is a junior remote Python role (a HIGH match), but "
                  "it is written in Spanish and there is no decided policy for "
                  "non-English posts, so the expected category is not self-evident. "
                  "Flagged for human review.",
        company="Startup de IA",
        location="Remoto (UE)",
        description=(
            "Buscamos un ingeniero JUNIOR de Python (0-2 anos) para construir "
            "aplicaciones con modelos de lenguaje (LLM) y FastAPI. Totalmente "
            "remoto en la UE. No se requiere experiencia senior."
        ),
        needs_review=True,
    ),
]


# The fixed, version-controlled case set. Order is stable for reproducibility.
ANALYST_CASES = _HIGH + _LOW + _FILTERED + _DEDUPED + _NEEDS_REVIEW

# Bands that require a real LLM scoring call (the only cases that can spend).
SCORING_EXPECTED = ("high", "low")
BEHAVIOR_EXPECTED = ("filtered", "deduped")


def needs_review_cases() -> list:
    """The subset a human should review (not confidently clear-cut)."""
    return [c for c in ANALYST_CASES if c.needs_review]
