"""Phase 7: the one real end-to-end eval run (the ONLY spend in this build).

Runs the full eval suite against the live data under the SpendGuard hard caps,
using the real Secretary (RAG over the chroma index) and the real Job Analyst
client. Saves the scorecard to data/eval_scorecard.json and prints the exact
calls + dollars spent so they can be recorded in the LOG. Run standalone (not via
the server) so the only money spent is this suite -- no background analyst scoring.
"""
import os

from agent_central import activity_log
from agent_central.eval import scorecard, runner, autorun
from agent_central import secretary, job_analyst, indexer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(ROOT, "data", "activity.db")
# Fair groundedness test: index the SAME activity.db that provides the ground
# truth into a scratch index, so the Secretary's retrieval and the truth come from
# one consistent system of record. (The deployed data/chroma was stale relative to
# activity.db after a DB archival, which would unfairly read as hallucination -- a
# separate ops issue, not a Secretary failure.) Non-destructive: a new directory.
CHROMA = os.path.join(ROOT, "data", "chroma_eval")
STATE = os.path.join(ROOT, "data", "chroma_eval_state.json")
PROFILE = os.path.join(ROOT, "data", "profile.yaml")
OUT = os.path.join(ROOT, "data", "eval_scorecard.json")

activity_log.init_db(DB)

embedding = indexer.EmbeddingService()
# Build the scratch index from the current activity.db if not already present.
if not os.path.isdir(CHROMA) or indexer.VectorIndex(CHROMA).count() == 0:
    st = indexer.IndexState(path=STATE)
    rs = indexer.run_index_pass(DB, CHROMA, embedding, st)
    print("scratch index build:", rs, "chunks:", indexer.VectorIndex(CHROMA).count())

client = secretary.SecretaryClient()
vindex = indexer.VectorIndex(CHROMA)
analyst_client = job_analyst.JobAnalystClient()


def ask_fn(question):
    return secretary.ask_secretary(question, vindex, embedding, client, top_k=5)


guard = runner.make_guard()
print("caps:", {"max_calls": runner.EVAL_MAX_CALLS,
                "max_cost_usd": runner.EVAL_MAX_COST_USD,
                "max_seconds": runner.EVAL_MAX_SECONDS})

card = scorecard.run_full_suite(PROFILE, DB, ask_fn, analyst_client, guard=guard)
card["signature"] = autorun.compute_signature(PROFILE)
scorecard.save_scorecard(card, OUT)

print("\n==== SPEND (authoritative, from the guard) ====")
print("LLM calls:", guard.calls)
print("estimated USD: %.6f" % guard.cost)
print("capped:", card["capped"])
print("\n==== OVERALL ====")
print(card["overall"])
for s in card["sections"]:
    print(f"\n-- {s['agent']} / {s['check']} [{s['provenance']}] : "
          f"{s['summary']['passed']}/{s['summary']['total']}")
    for r in s["results"]:
        label = r.get("title") or r.get("question") or r.get("id")
        if s["check"] == "groundedness":
            print(f"   [{ 'PASS' if r['passed'] else r.get('outcome','FAIL') }] {r['id']}: "
                  f"truth={r.get('truth')!r}")
        else:
            print(f"   [{'PASS' if r['passed'] else 'FAIL'}] {r['id']}: "
                  f"expected={r.get('expected')} score={r.get('score')}"
                  f"{' [needs_review]' if r.get('needs_review') else ''}")
print("\nsaved scorecard to", OUT)
