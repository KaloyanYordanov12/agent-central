"""Eval suite runner — executes the graded suite under hard SpendGuard caps.

Phase 1 wires the Secretary groundedness portion. The analyst categorical portion
and the combined scorecard are added in later phases. The SpendGuard reused here
is the exact hard-cap class from job_analyst.py: the loop checks allow() BEFORE
every model call, so no call is ever made past a cap.

Spending only ever happens here, and only when a real ask_fn / analyst client is
injected. Unit tests inject fakes and spend $0.
"""
import os
import sqlite3
import tempfile

from agent_central import activity_log
from agent_central.job_analyst import SpendGuard
from agent_central.eval import grader
from agent_central.eval.questions import GROUNDEDNESS_QUESTIONS
from agent_central.eval.analyst_cases import ANALYST_CASES, SCORING_EXPECTED

# Hard caps for a full eval run (whichever is hit first stops the run). These are
# deliberately well under the build budget: ~$0.50, ~50 calls, ~10 min.
EVAL_MAX_COST_USD = 0.50
EVAL_MAX_CALLS = 50
EVAL_MAX_SECONDS = 600.0

DEFAULT_MODEL = "claude-haiku-4-5"


def make_guard() -> SpendGuard:
    """A SpendGuard pre-loaded with the eval suite's hard caps."""
    return SpendGuard(
        max_calls=EVAL_MAX_CALLS,
        max_cost_usd=EVAL_MAX_COST_USD,
        max_seconds=EVAL_MAX_SECONDS,
    )


def _record_cost(guard, model, sec_result):
    """Estimate this ask's USD cost from token usage and record it on the guard."""
    cost = activity_log._estimate_cost_usd(
        model,
        sec_result.get("input_tokens", 0) or 0,
        sec_result.get("output_tokens", 0) or 0,
        0, 0,
    ) or 0.0
    guard.record(cost)


def run_secretary_groundedness(db_path: str, ask_fn, guard=None,
                               model: str = DEFAULT_MODEL) -> dict:
    """Run the objective Secretary groundedness suite.

    ask_fn(question_text) -> {answer, sources, model, input_tokens, output_tokens}
    is injected so tests pass a fake (no spend) and the real run passes a closure
    over the live Secretary. The truth for each question is computed from db_path.

    If a guard is given, allow() is checked BEFORE each ask, so the run stops the
    moment any cap is reached; the cap that stopped it is returned as 'capped'.
    """
    results = []
    capped = None
    for q in GROUNDEDNESS_QUESTIONS:
        if guard is not None and not guard.allow():
            capped = guard.stopped
            break
        truth = q.truth_fn(db_path)
        try:
            sec = ask_fn(q.text)
        except Exception as e:  # an ask failure is a real (non-passing) result
            if guard is not None:
                guard.record(0.0)  # a failed attempt still counts toward the call cap
            results.append({
                "id": q.id, "question": q.text, "kind": q.kind, "truth": truth,
                "answer": "", "sources": [], "outcome": "error", "passed": False,
                "error": str(e)[:200], "hallucinated_sources": [],
                "provenance": q.provenance,
            })
            continue
        if guard is not None:
            _record_cost(guard, model, sec)
        results.append(grader.grade_groundedness(q, truth, sec, db_path))

    return {
        "agent": "secretary",
        "check": "groundedness",
        "provenance": "computed from activity_log",
        "results": results,
        "summary": grader.summarize(results),
        "capped": capped,
    }


def _check_filtered(case) -> dict:
    """A 'filtered' case passes if Job Scout's title filter rejects it (no LLM)."""
    from agent_central import job_scout

    reason = job_scout.apply_title_filters(job_scout.Job(
        url=case.job_url(), source=case.source, title=case.title,
        description=case.description,
    ))
    passed = reason is not None
    return {
        "id": case.id, "title": case.title, "expected": case.expected,
        "observed": {"filter_reason": reason}, "score": None, "passed": passed,
        "reason": (f"title filtered: {reason}" if passed
                   else "title was NOT filtered (expected it to be)"),
        "provenance": case.provenance(), "needs_review": case.needs_review,
    }


def _check_deduped(case) -> dict:
    """A 'deduped' case passes if storing the same URL twice yields one row (no LLM).

    Runs against a throwaway temp DB (schema only) so it never touches the live
    activity_log path -- store_jobs is called twice with the same URL.
    """
    from agent_central import job_scout

    fd, path = tempfile.mkstemp(suffix="_eval_dedup.db")
    os.close(fd)
    try:
        conn = sqlite3.connect(path)
        try:
            conn.executescript(activity_log._SCHEMA)
        finally:
            conn.close()
        job = job_scout.Job(url=case.job_url(), source=case.source, title=case.title,
                            description=case.description)
        first = job_scout.store_jobs([job], path)
        second = job_scout.store_jobs([job], path)  # same URL -> must be a no-op
        passed = first["new"] == 1 and second["new"] == 0
        observed = {"first_new": first["new"], "second_new": second["new"]}
    finally:
        os.remove(path)
    return {
        "id": case.id, "title": case.title, "expected": case.expected,
        "observed": observed, "score": None, "passed": passed,
        "reason": ("duplicate URL deduped (1 stored, 2nd ignored)" if passed
                   else f"dedup failed: {observed}"),
        "provenance": case.provenance(), "needs_review": case.needs_review,
    }


def run_analyst_cases(profile_path: str, client, guard=None,
                      model: str = DEFAULT_MODEL) -> dict:
    """Run the Job Analyst clear-cut categorical suite.

    Behavior cases ('filtered' / 'deduped') are checked with no LLM call (they
    can never spend). Band cases ('high' / 'low') are scored by the injected
    analyst client under the SpendGuard: allow() is checked BEFORE each scoring
    call, so the run stops the moment any cap is reached. Tests inject a fake
    client and spend $0.
    """
    from agent_central import job_analyst

    profile = job_analyst.load_profile(profile_path)
    system_prompt = job_analyst.build_system_prompt(profile)

    results = []
    capped = None
    for case in ANALYST_CASES:
        if case.expected == "filtered":
            results.append(_check_filtered(case))
            continue
        if case.expected == "deduped":
            results.append(_check_deduped(case))
            continue
        # Scoring case: real LLM call (guarded).
        if guard is not None and not guard.allow():
            capped = guard.stopped
            break
        try:
            scored = client.score_job(system_prompt, case.as_job())
        except Exception as e:
            if guard is not None:
                guard.record(0.0)
            results.append({
                "id": case.id, "title": case.title, "expected": case.expected,
                "observed": {"error": str(e)[:200]}, "score": None, "passed": False,
                "reason": f"scoring failed: {str(e)[:120]}",
                "provenance": case.provenance(), "needs_review": case.needs_review,
            })
            continue
        if guard is not None:
            usage = scored.get("usage", {}) or {}
            cost = activity_log._estimate_cost_usd(
                model, usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                usage.get("cache_creation_tokens", 0), usage.get("cache_read_tokens", 0),
            ) or 0.0
            guard.record(cost)
        results.append(grader.grade_categorical(case, {
            "score": scored.get("score"),
            "reasoning": scored.get("reasoning", ""),
        }))

    return {
        "agent": "job_analyst",
        "check": "categorical",
        "provenance": "model-drafted (Opus 4.8), clear-cut",
        "results": results,
        "summary": grader.summarize(results),
        "capped": capped,
    }


def scoring_case_count() -> int:
    """How many cases require a real LLM call (for cap planning / reporting)."""
    return sum(1 for c in ANALYST_CASES if c.expected in SCORING_EXPECTED)
