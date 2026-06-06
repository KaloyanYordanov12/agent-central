"""Phase 3: ONE measurement eval (the only spend), under the eval SpendGuard caps.

Runs the full eval suite once against the now-fixed deployed index (data/chroma,
rebuilt in Phase 1) and the improved hybrid Secretary (Phase 2), standalone (no
server, so no background analyst scoring). Saves the scorecard with the current
signature (clearing the "stale" state) and reports exact REAL billable calls +
dollars. Real API calls are counted directly (the structured Secretary path makes
no LLM call, so groundedness now costs $0). One run only; do not loop.
"""
import os

from agent_central import activity_log
from agent_central.eval import scorecard, runner, autorun
from agent_central import secretary, job_analyst, indexer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(ROOT, "data", "activity.db")
CHROMA = os.path.join(ROOT, "data", "chroma")       # the rebuilt, current index
PROFILE = os.path.join(ROOT, "data", "profile.yaml")
OUT = os.path.join(ROOT, "data", "eval_scorecard.json")

activity_log.init_db(DB)

emb = indexer.EmbeddingService()
vindex = indexer.VectorIndex(CHROMA)

# Count REAL billable API calls (structured Secretary answers make none).
counts = {"secretary_llm": 0, "analyst_llm": 0}

_sec = secretary.SecretaryClient()
_sec_ask = _sec.ask
def _counted_ask(*a, **k):
    counts["secretary_llm"] += 1
    return _sec_ask(*a, **k)
_sec.ask = _counted_ask

_an = job_analyst.JobAnalystClient()
_an_score = _an.score_job
def _counted_score(*a, **k):
    counts["analyst_llm"] += 1
    return _an_score(*a, **k)
_an.score_job = _counted_score


def ask_fn(question):
    return secretary.ask_secretary(question, vindex, emb, _sec, top_k=5, db_path=DB)


guard = runner.make_guard()
print("caps:", {"max_calls": runner.EVAL_MAX_CALLS,
                "max_cost_usd": runner.EVAL_MAX_COST_USD,
                "max_seconds": runner.EVAL_MAX_SECONDS})

card = scorecard.run_full_suite(PROFILE, DB, ask_fn, _an, guard=guard)
card["signature"] = autorun.compute_signature(PROFILE)
scorecard.save_scorecard(card, OUT)

real_calls = counts["secretary_llm"] + counts["analyst_llm"]
print("\n==== SPEND ====")
print("REAL billable LLM calls:", real_calls,
      f"(secretary {counts['secretary_llm']}, analyst {counts['analyst_llm']})")
print("estimated USD: %.6f" % guard.cost)
print("guard attempts (incl. $0 structured no-ops):", guard.calls)
print("capped:", card["capped"])

g = [s for s in card["sections"] if s["check"] == "groundedness"][0]
a = [s for s in card["sections"] if s["check"] == "categorical"][0]
print("\n==== RESULTS ====")
print(f"OVERALL: {card['overall']['passed']}/{card['overall']['total']} "
      f"({round(card['overall']['pass_rate']*100,1)}%)")
print(f"secretary groundedness: {g['summary']['passed']}/{g['summary']['total']}")
for r in g["results"]:
    print(f"   [{'PASS' if r['passed'] else r.get('outcome','FAIL')}] {r['id']}")
print(f"job_analyst categorical: {a['summary']['passed']}/{a['summary']['total']}")
for r in a["results"]:
    if not r["passed"]:
        print(f"   [FAIL] {r['id']} (expected {r.get('expected')}, score {r.get('score')})")
print("\nsaved scorecard to", OUT)
