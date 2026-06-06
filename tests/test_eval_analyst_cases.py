"""Phase 2 tests: Job Analyst clear-cut categorical suite (mocked, $0 spend).

A scripted fake analyst client stands in for the LLM, so no Anthropic calls and
no money. The point under test: clear-cut cases are well-formed (band cases reach
the LLM, filtered cases are caught by the title filter), the runner grades by
band/behavior, the SpendGuard stops scoring at its cap (incl. a zero-call case),
and the human-review flagging + provenance labels behave honestly.
"""
import pytest

from agent_central import job_scout
from agent_central.eval import analyst_cases, grader, runner
from agent_central.eval.analyst_cases import ANALYST_CASES, AnalystCase
from agent_central.job_analyst import SpendGuard


# --- fake analyst client ------------------------------------------------------
class ScriptedAnalyst:
    """Returns a per-title score; never hits the network."""

    def __init__(self, score_by_title):
        self.model = "claude-haiku-4-5"
        self._scores = score_by_title
        self.calls = []

    def score_job(self, system_prompt, job):
        self.calls.append(job)
        score = self._scores.get(job["title"], 50)
        return {
            "score": score, "reasoning": f"scored {score}", "fit_notes": {},
            "red_flags": [],
            "usage": {"input_tokens": 200, "output_tokens": 30,
                      "cache_creation_tokens": 0, "cache_read_tokens": 100},
        }


def _perfect_scores():
    """Map each band case title to a score squarely inside its expected band."""
    out = {}
    for c in ANALYST_CASES:
        if c.expected == "high":
            out[c.title] = 90
        elif c.expected == "low":
            out[c.title] = 10
    return out


def _profile(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text("name: T\nlevel: Junior\nlanguages:\n  - Python\n", encoding="utf-8")
    return str(p)


# --- fixtures are well-formed and clear-cut ----------------------------------

def test_all_cases_have_valid_expected():
    valid = {"high", "low", "filtered", "deduped"}
    assert all(c.expected in valid for c in ANALYST_CASES)
    assert len(ANALYST_CASES) >= 12  # spec aims for ~12-20


def test_band_case_titles_are_not_title_filtered():
    """high/low cases MUST reach the LLM, so the title filter must NOT catch them.

    Otherwise a LOW case would 'pass' for the wrong reason (filtered, not scored).
    """
    for c in ANALYST_CASES:
        if c.expected in ("high", "low"):
            job = job_scout.Job(url=c.job_url(), source=c.source, title=c.title)
            assert job_scout.apply_title_filters(job) is None, c.id


def test_filtered_cases_are_actually_filtered_by_title():
    for c in ANALYST_CASES:
        if c.expected == "filtered":
            job = job_scout.Job(url=c.job_url(), source=c.source, title=c.title)
            assert job_scout.apply_title_filters(job) is not None, c.id


def test_needs_review_cases_are_flagged_and_listed():
    flagged = analyst_cases.needs_review_cases()
    ids = {c.id for c in flagged}
    assert ids == {"se2_mid_level_ambiguous", "spanish_junior_python"}
    assert all(c.needs_review for c in flagged)


def test_provenance_label_is_honest():
    drafted = AnalystCase(id="x", title="t", expected="high", rationale="r")
    assert drafted.provenance() == "model-drafted (Opus 4.8), clear-cut"
    reviewed = AnalystCase(id="x", title="t", expected="high", rationale="r",
                           human_reviewed=True)
    assert reviewed.provenance() == "human-reviewed"


# --- grader (band) -----------------------------------------------------------

def test_grade_categorical_band():
    case = AnalystCase(id="c", title="t", expected="high", rationale="r")
    assert grader.grade_categorical(case, {"score": 88})["passed"] is True
    assert grader.grade_categorical(case, {"score": 40})["passed"] is False
    low = AnalystCase(id="c", title="t", expected="low", rationale="r")
    assert grader.grade_categorical(low, {"score": 10})["passed"] is True
    assert grader.grade_categorical(low, {"score": 80})["passed"] is False


# --- runner end to end (mocked) ----------------------------------------------

def test_run_analyst_cases_perfect_analyst_passes_all(tmp_path):
    client = ScriptedAnalyst(_perfect_scores())
    guard = runner.make_guard()
    out = runner.run_analyst_cases(_profile(tmp_path), client=client, guard=guard)
    # Every check passes when the analyst scores perfectly + behaviors hold.
    assert out["summary"]["total"] == len(ANALYST_CASES)
    assert out["summary"]["passed"] == len(ANALYST_CASES)
    assert out["summary"]["pass_rate"] == 1.0
    # Only band cases hit the (mock) LLM; filtered/deduped did not.
    assert len(client.calls) == runner.scoring_case_count()
    assert out["capped"] is None
    assert out["provenance"] == "model-drafted (Opus 4.8), clear-cut"


def test_run_analyst_cases_detects_band_miss(tmp_path):
    scores = _perfect_scores()
    # Break one HIGH case: score it low -> that case must now fail.
    scores["Junior Python Engineer - AI Agents"] = 12
    client = ScriptedAnalyst(scores)
    out = runner.run_analyst_cases(_profile(tmp_path), client=client)
    by_id = {r["id"]: r for r in out["results"]}
    assert by_id["junior_python_ai_agents"]["passed"] is False
    assert out["summary"]["passed"] == len(ANALYST_CASES) - 1


def test_run_analyst_cases_zero_call_guard_spends_nothing(tmp_path):
    """Guard with 0 allowed calls makes zero scoring calls."""
    client = ScriptedAnalyst(_perfect_scores())
    guard = SpendGuard(max_calls=0, max_cost_usd=1.0, max_seconds=900)
    out = runner.run_analyst_cases(_profile(tmp_path), client=client, guard=guard)
    assert len(client.calls) == 0
    assert out["capped"] == "max_calls"


def test_run_analyst_cases_guard_records_cost(tmp_path):
    client = ScriptedAnalyst(_perfect_scores())
    guard = runner.make_guard()
    runner.run_analyst_cases(_profile(tmp_path), client=client, guard=guard)
    assert guard.calls == runner.scoring_case_count()
    assert guard.cost > 0  # estimated (mock tokens), no real money
