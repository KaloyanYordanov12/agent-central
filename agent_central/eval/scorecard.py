"""Assemble the two eval suites into one persisted scorecard with honest
per-check provenance, and run the full suite under a single shared SpendGuard.

The scorecard records, per check, where its ground truth came from:
  - "computed from activity_log"            (Secretary groundedness, objective)
  - "model-drafted (Opus 4.8), clear-cut"   (Job Analyst cases, or "human-reviewed"
                                             once a human has checked a case)
It also records the real spend (calls + estimated USD) and which cap, if any,
stopped the run. Persistence is a small JSON file under data/ (gitignored); the
fixtures themselves stay version-controlled under agent_central/eval/.
"""
import json
import os
from datetime import datetime, timezone

from agent_central.eval import runner

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_SCORECARD_PATH = os.path.join(_PROJECT_ROOT, "data", "eval_scorecard.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_scorecard(sections: list, guard=None, generated_at=None) -> dict:
    """Combine suite sections into the persisted scorecard shape.

    Each section is a run_* result: {agent, check, provenance, results, summary,
    capped}. Spend comes from the shared guard. Failing cases are flattened with
    their section context so the UI can show exactly what failed and why.
    """
    all_results = [r for s in sections for r in s.get("results", [])]
    overall = runner.grader.summarize(all_results)

    failing = []
    for s in sections:
        for r in s.get("results", []):
            if not r.get("passed"):
                failing.append({
                    "agent": s.get("agent"),
                    "check": s.get("check"),
                    "provenance": r.get("provenance", s.get("provenance")),
                    **r,
                })

    needs_review = [
        {"agent": s.get("agent"), "id": r.get("id"), "title": r.get("title"),
         "expected": r.get("expected")}
        for s in sections for r in s.get("results", []) if r.get("needs_review")
    ]

    capped = next((s.get("capped") for s in sections if s.get("capped")), None)

    return {
        "generated_at": generated_at or _now_iso(),
        "overall": overall,
        "spend": {
            "calls": guard.calls if guard is not None else None,
            "estimated_cost_usd": round(guard.cost, 6) if guard is not None else None,
        },
        "caps": {
            "max_calls": runner.EVAL_MAX_CALLS,
            "max_cost_usd": runner.EVAL_MAX_COST_USD,
            "max_seconds": runner.EVAL_MAX_SECONDS,
        },
        "capped": capped,
        "sections": sections,
        "failing": failing,
        "needs_review": needs_review,
    }


def run_full_suite(profile_path: str, db_path: str, ask_fn, analyst_client,
                   guard=None, generated_at=None) -> dict:
    """Run both suites under ONE shared SpendGuard, then build the scorecard.

    The shared guard means the hard caps (~$0.50, ~50 calls, ~10 min) apply across
    the whole run, not per suite. ask_fn / analyst_client are injected so tests use
    fakes ($0) and the real run wires the live Secretary + analyst.
    """
    g = guard if guard is not None else runner.make_guard()
    ground = runner.run_secretary_groundedness(db_path, ask_fn, guard=g)
    analyst = runner.run_analyst_cases(profile_path, analyst_client, guard=g)
    return build_scorecard([ground, analyst], guard=g, generated_at=generated_at)


def save_scorecard(card: dict, path: str = DEFAULT_SCORECARD_PATH) -> None:
    """Atomically persist the latest scorecard JSON."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(card, f, indent=2)
    os.replace(tmp, path)


def load_scorecard(path: str = DEFAULT_SCORECARD_PATH):
    """Load the latest scorecard, or None if no eval has ever run."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
