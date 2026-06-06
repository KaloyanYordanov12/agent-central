# Evaluator Agent build log

An honest eval harness added to Agent Central as a new agent (the Evaluator). It
runs a fixed, honestly-grounded eval suite against the other agents and reports a
real scorecard.

Branch: `eval-agent` (off master). Do NOT merge to master in this run.

## The methodology honesty rule (the point of this feature)

Ground truth comes from one of two places, and the UI/README label each honestly:

1. Secretary groundedness: OBJECTIVE. The truth is computed directly from the
   SQLite activity data with code (e.g. "how many LLM calls did the Job Analyst
   make today?"). No model opinion. Provenance label: "computed from activity_log".

2. Job Analyst categorical cases: model-drafted at full effort by Opus 4.8, kept
   CLEAR-CUT (a plumbing job must score low for a software profile). The ground
   truth is the CATEGORY/band (high / low / filtered / deduped), never a precise
   model-picked number. Provenance label: "model-drafted (Opus 4.8), clear-cut",
   which flips to "human-reviewed" on any case Kolio has actually checked. Cases we
   are not confident are clear-cut get `needs_review: true` and are flagged for
   Kolio.

Never: a same-tier model's subjective fine-grained score treated as truth, or a
dishonest provenance label.

## Spend discipline

- Haiku only. Reuse the existing `SpendGuard` from job_analyst.py.
- Hard caps for a full run: ~$0.50 total, ~50 LLM calls, ~10 min wall-clock;
  whichever hits first stops the run.
- Building + all unit tests spend $0 (mocked clients / fixtures), exactly like the
  existing analyst tests. Verify the guard (including a zero-call case) before any
  unbounded run.
- Only Phase 7 (the real end-to-end verification) spends, once, under the caps.
- Auto-run is infrequent (about once per shift/day) and SKIPS if nothing changed
  (no new commit / no agent-config change / already ran today). On-demand is the
  primary path.

## Reused existing patterns

- `SpendGuard` hard-cap class (agent_central/job_analyst.py).
- The CDP screenshot technique (docs/stageN-build) for UI verification.
- The dark "console" popup tier (`.secretary-popup` family in static/index.html)
  for the scorecard UI.
- The office sprite/state system (AGENTS array, MAP, setBackendState, agent_states
  WS message) for the new Evaluator agent.
- Anthropic key read at client construction (request time), never at import.
- No em-dashes in any file.

## Where things live

- Eval fixtures + framework (version-controlled test assets): `agent_central/eval/`
  - `questions.py`   - fixed Secretary question set + DB-computed truth
  - `analyst_cases.py` - clear-cut categorical cases (the reviewable file, Opus header)
  - `grader.py`      - graders (Secretary groundedness + analyst band/behavior)
  - `runner.py`      - runs the suite under SpendGuard, builds the scorecard
- Scorecard persistence: `data/eval_scorecard.json` (data/ is gitignored; fixtures
  are NOT in data/).
- Backend endpoints: `GET /api/eval/scorecard`, `POST /api/eval/run` in api.py.
- Office agent + UI: AGENTS/MAP/eval-popup in static/index.html + static/eval.js.
- Sprite: static/assets/pixelspaces/npc/evaluator.png (160x96, mirrors the others).
- Human-reviewable analyst cases (for Kolio): `agent_central/eval/analyst_cases.py`.

## Roadmap (one commit per substep, tests green before each commit)

- [x] Phase 0: read code, write this roadmap, confirm branch.
- [x] Phase 1: eval framework + Secretary groundedness (objective). Grader unit-
      tested with mocked Secretary answers (right / wrong / hallucinated). Commit.
- [x] Phase 2: Job Analyst clear-cut categorical suite + runner under SpendGuard.
      Mocked-analyst unit tests. Commit.
- [x] Phase 3: scorecard backend (GET scorecard + POST run under caps), persist
      latest, provenance per check, endpoint tests (mocked). Commit.
- [x] Phase 4: Evaluator agent in the office (desk/zone, sprite, idle/running-evals
      state, WS + activity log, honest "no eval yet"). Commit.
- [x] Phase 5: scorecard UI (dark console tier): pass rate, per-agent, failing
      cases, honest provenance labels, Run-evals button. Screenshot-verify. Commit.
- [x] Phase 6: infrequent auto-run + skip-if-unchanged, under the caps. Commit.
- [x] Phase 7: real end-to-end run (the only spend), under caps. Record exact
      calls + dollars here. Screenshot the populated scorecard.
- [x] Phase 8: regression (full suite green; report new count vs 109) + README
      methodology note. Commit.

## Baselines

- Test count on master before this build: 109 passed.

## Phase 7 spend record

The full suite was run once for real, standalone (not via the server) so the only
money spent was this suite -- no background Job Analyst scoring. Haiku only, under
the SpendGuard caps (max $0.50 / 50 calls / 600s).

AUTHORITATIVE PHASE 7 RUN (the saved scorecard):
- LLM calls: 18  (6 Secretary groundedness asks + 12 Job Analyst scoring calls;
  the 5 filtered + 1 deduped behavior cases cost nothing, as designed)
- Estimated spend: $0.018358   (well under the $0.50 cap)
- Cap hit: none
- Overall: 23 checks, 18 passed -> 78.3% pass rate.

Per section:
- secretary / groundedness [computed from activity_log]: 2 / 6
    PASS errors_today (truth 0), PASS job_analyst_recent_state (truth "paused").
    WRONG agents_active_today (named 2 of 4 active agents),
    WRONG job_scout_recent_state (said "scanning", truth "idle"),
    WRONG most_recent_event_agent, ABSTAINED job_analyst_passes_today.
    A real, honest finding: the Secretary's RAG over chunked window summaries is
    weak at cross-window aggregation/recency. Truth was computed from the DB; the
    misses are genuine, not labelling tricks.
- job_analyst / categorical [model-drafted (Opus 4.8), clear-cut]: 16 / 17
    All 5 HIGH cases scored 92-95; all 5 LOW (wrong-field) cases scored 0-5; all 4
    FILTERED title cases rejected pre-LLM; the DEDUPED case deduped. The one FAIL
    is se2_mid_level_ambiguous (scored 45, expected the LOW band) -- which is
    exactly one of the two cases flagged needs_review for Kolio, so it is expected
    to be arguable. spanish_junior_python (also needs_review) scored 92 (HIGH).

Note on a fair Secretary test: the deployed data/chroma index was stale relative
to data/activity.db (older events had been archived to activity-archive-*.db on
2026-06-04), so the Secretary was retrieving real-but-archived windows that do not
verify against the current activity_log -- which would unfairly read as
"hallucinated". For a fair groundedness test the Phase 7 run indexes the SAME
current activity.db that provides the ground truth into a scratch index
(data/chroma_eval), so retrieval and truth share one system of record. The stale
deployed index is a separate ops issue worth fixing in the product, not a
Secretary failure. (An earlier Phase 7 attempt against the stale index scored the
groundedness section 0/6 as "hallucinated"; that was the artifact, now corrected.)

Honesty note on build spend: bringing Phase 7 to a fair result took a couple of
extra real runs (a path-bug crash after ~6 Secretary calls, then one run against
the stale index) before the final fair run above. Each run stayed well under the
caps; total real spend across all Phase 7 attempts was roughly $0.04. Only the
final run's numbers (18 calls / $0.018358) are the scorecard of record.

## Roadmap status: all phases complete (see checklist above, all checked in commits).
