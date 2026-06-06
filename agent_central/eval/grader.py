"""Graders for the eval suite.

Secretary groundedness grader (objective): given a question, its DB-computed
truth, and the Secretary's actual answer, decide one of:
  - correct    : the answer matches the computed truth AND every cited source is a
                 real window with real events in the activity_log.
  - wrong      : an answer was given but it does not match the computed truth.
  - hallucinated: the answer cites a source (window) that does NOT verify against
                 the database (fabricated grounding).
  - abstained  : the Secretary honestly said it has no information.
Only 'correct' counts as a pass. None of this needs human labeling: the database
is the ground truth, and source verification is a direct DB lookup.

The Job Analyst categorical grader lives below (Phase 2): it grades a numeric
score against an expected clear-cut band, or a behavior against the expected one.
"""
import re
import sqlite3

# Phrases that signal the Secretary honestly declined to answer (no fabrication).
_ABSTENTION_MARKERS = (
    "don't have", "do not have", "dont have", "no information", "no data",
    "not have information", "cannot answer", "can't answer", "unable to",
    "no activity log data", "nothing in the",
)

# Negation phrases accepted as a correct answer to a count question whose truth
# is 0 (e.g. "no errors were logged" instead of literally writing "0").
_ZERO_NEGATIONS = (
    "no ", "none", "zero", "not ", "without any", "no errors", "haven't",
    "hasn't", "didn't", "did not", "0",
)


def _int_tokens(text: str) -> set:
    """Standalone integer tokens in a string (so '25' does not match '250')."""
    return set(re.findall(r"\b\d+\b", text or ""))


def is_abstention(answer: str) -> bool:
    low = (answer or "").lower()
    return any(marker in low for marker in _ABSTENTION_MARKERS)


def answer_matches_truth(kind: str, truth, answer: str) -> bool:
    """True if the free-text answer agrees with the computed truth.

    'count'    -> the integer appears as a standalone token (truth 0 also accepts
                  an honest negation).
    'contains' -> every synonym-group has at least one synonym present (an empty
                  truth means the honest answer is a negation / 'none').
    """
    low = (answer or "").lower()
    if kind == "count":
        n = int(truth)
        if n == 0:
            return "0" in _int_tokens(low) or any(neg in low for neg in _ZERO_NEGATIONS)
        return str(n) in _int_tokens(low)
    if kind == "contains":
        groups = truth or []
        if not groups:
            # No matching data -> the honest answer is a negation / "none".
            return any(neg in low for neg in _ZERO_NEGATIONS)
        return all(any(syn.lower() in low for syn in group) for group in groups)
    raise ValueError(f"unknown question kind: {kind}")


def verify_source(db_path: str, source: dict) -> bool:
    """True if a cited source corresponds to a real window with real events.

    A source is {chunk_id, agent_id, window_start, window_end, ...}. We check the
    activity_log directly: are there events for that agent inside [start, end)?
    A source that does not verify is fabricated grounding (a hallucination).
    """
    agent_id = source.get("agent_id")
    if not agent_id:
        return False
    ws, we = source.get("window_start"), source.get("window_end")
    sql = "SELECT COUNT(*) FROM activity_log WHERE agent_id = ?"
    params = [agent_id]
    if ws:
        sql += " AND timestamp >= ?"
        params.append(ws)
    if we:
        sql += " AND timestamp < ?"   # window_end is exclusive (chunk = [start, start+window))
        params.append(we)
    conn = sqlite3.connect(db_path)
    try:
        n = conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()
    return int(n) > 0


def grade_groundedness(question, truth, secretary_result: dict, db_path: str) -> dict:
    """Grade one Secretary answer against its DB-computed truth. See module docs."""
    answer = (secretary_result or {}).get("answer", "")
    sources = (secretary_result or {}).get("sources") or []

    hallucinated_sources = [
        s.get("chunk_id") for s in sources if not verify_source(db_path, s)
    ]
    matched = answer_matches_truth(question.kind, truth, answer)
    abstained = is_abstention(answer)

    if abstained:
        outcome = "abstained"
    elif hallucinated_sources:
        outcome = "hallucinated"
    elif matched:
        outcome = "correct"
    else:
        outcome = "wrong"

    return {
        "id": question.id,
        "question": question.text,
        "kind": question.kind,
        "truth": truth,
        "answer": answer,
        "sources": sources,
        "outcome": outcome,
        "passed": outcome == "correct",
        "matched_truth": matched,
        "hallucinated_sources": hallucinated_sources,
        "provenance": question.provenance,
    }


# ----------------------------------------------------------------------------
# Job Analyst categorical grader (Phase 2)
# ----------------------------------------------------------------------------
# Expected bands map a clear-cut category to the score range that must contain
# the analyst's score for the case to pass. These mirror job_analyst.py's own
# thresholds: REJECT_FLOOR = 25, DEFAULT_THRESHOLD = 75.
SCORE_BANDS = {
    "high": (75, 100),   # clear strong match -> should be notify-worthy
    "low": (0, 24),      # clear non-match / hard no-go -> should be rejected_by_llm
}


def grade_categorical(case, observed: dict) -> dict:
    """Grade one analyst case.

    case.expected is one of: 'high', 'low' (score-band cases) or a behavior token
    'filtered' / 'deduped' (handled by the runner, not a score). observed carries
    {score} for band cases. Returns a result dict with passed + a human-readable
    reason. Provenance is carried from the case (model-drafted vs human-reviewed).
    """
    expected = case.expected
    band = SCORE_BANDS.get(expected)
    score = observed.get("score")
    if band is None:
        # Behavior cases are graded by the runner; keep this grader band-only.
        return {
            "id": case.id, "expected": expected, "observed": observed,
            "passed": False, "reason": f"non-band expected '{expected}' not gradable here",
            "provenance": case.provenance(), "needs_review": case.needs_review,
        }
    lo, hi = band
    passed = score is not None and lo <= int(score) <= hi
    reason = (
        f"score {score} in expected {expected} band [{lo}, {hi}]" if passed
        else f"score {score} outside expected {expected} band [{lo}, {hi}]"
    )
    return {
        "id": case.id,
        "title": case.title,
        "expected": expected,
        "expected_band": [lo, hi],
        "observed": observed,
        "score": score,
        "passed": passed,
        "reason": reason,
        "provenance": case.provenance(),
        "needs_review": case.needs_review,
    }


def summarize(results: list) -> dict:
    """Aggregate a list of per-check result dicts into pass-rate + outcome tallies."""
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    outcomes = {}
    for r in results:
        key = r.get("outcome")
        if key:
            outcomes[key] = outcomes.get(key, 0) + 1
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "outcomes": outcomes,
    }
