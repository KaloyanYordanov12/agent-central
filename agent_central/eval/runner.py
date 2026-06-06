"""Eval suite runner — executes the graded suite under hard SpendGuard caps.

Phase 1 wires the Secretary groundedness portion. The analyst categorical portion
and the combined scorecard are added in later phases. The SpendGuard reused here
is the exact hard-cap class from job_analyst.py: the loop checks allow() BEFORE
every model call, so no call is ever made past a cap.

Spending only ever happens here, and only when a real ask_fn / analyst client is
injected. Unit tests inject fakes and spend $0.
"""
from agent_central import activity_log
from agent_central.job_analyst import SpendGuard
from agent_central.eval import grader
from agent_central.eval.questions import GROUNDEDNESS_QUESTIONS

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
