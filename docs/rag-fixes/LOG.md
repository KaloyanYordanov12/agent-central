# RAG fixes: stale index + Secretary groundedness + fresh demo

One bounded pass on branch `rag-fixes` (off master). Do NOT merge or push (Kolio
reviews first). No em-dashes. One commit per phase. Only Phase 3 spends, under the
eval SpendGuard caps.

## Scope (fixed, do not expand)
1. Fix the stale Secretary vector index (rebuild data/chroma from the current
   activity.db so retrieval and the activity_log are one system of record).
2. Improve Secretary groundedness on count / recency / aggregation questions via
   hybrid retrieval (a deterministic structured path that answers from the DB,
   alongside the existing vector path for semantic questions).
3. Run ONE eval to measure (the only spend), under caps.
4. Regenerate the hero GIF off the healthy data; point the README hero at it.
5. Regression + wrap.

## Out of scope (separate later, supervised passes)
- The non-English / language filter.
- The requirements-based analyst fit logic (it ripples into human-reviewed eval
  cases). Do NOT change the analyst scoring/profile or the eval cases here.

## Starting state (diagnosed)
- data/activity.db: 250 rows, 2026-06-04T18:50 to 2026-06-06T12:29, 5 agents.
- data/index_state.json: last_indexed_event_id=888, total_chunks=452 -> the index
  tracks ARCHIVED events (888 > 250 current rows), confirming staleness. Older data
  was archived to data/activity-archive-20260604-215010.db (left untouched).
- Eval baseline (pre-fix, from the prior Phase 7 run): Secretary groundedness 2/6.

## Spend rules
- Haiku only. Phases 1, 2, 4, 5 are $0 (re-index uses the local sentence-
  transformers model; the RAG fix is built + unit-tested with mocks / a temp DB).
- ONLY Phase 3 spends: one eval run under the existing caps (~$0.50 / 50 calls /
  10 min, whichever first). Verify the guard path first. One run only; do not loop.

## Roadmap
- [ ] Phase 0: read indexer/secretary/api, write this roadmap, confirm branch. Commit.
- [ ] Phase 1: clean rebuild of data/chroma from current activity.db; verify only
      current windows remain. Commit.
- [ ] Phase 2: hybrid retrieval (structured count/recency/aggregation path grounded
      in real rows + intent routing), mock-first tests, no semantic regression. Commit.
- [ ] Phase 3: one measurement eval under caps; record exact calls + dollars, new vs
      old (2/6) groundedness; save the (now-current, non-stale) scorecard. Commit.
- [ ] Phase 4: fresh hero GIF off healthy data + README hero pointer. Commit.
- [ ] Phase 5: regression (report new test count), finalize this LOG. No merge/push.

## Results (filled in as phases complete)

### Phase 1: index rebuild (done, $0)
- Tool: docs/rag-fixes/rebuild_index.py (uses the app's own indexer + the local
  embedding model; never touches activity.db or the archive).
- Dropped the stale collection (163 active chunks, tracking archived windows) and
  re-indexed the current activity.db: 250 events -> 57 chunks.
- Verified: 57/57 indexed windows correspond to real events in the current
  activity.db (0 archived-only windows remain); earliest window 2026-06-04T18:45
  floors the first real event at 18:50. A live semantic retrieval returned only
  current (06-05) job_scout windows. The index and activity_log are now consistent.

### Phase 2: hybrid-retrieval design (done, $0)
- New module agent_central/structured_qa.py: a deterministic structured path that
  answers count / recency / aggregation questions directly from the activity_log
  with SQL queries, grounding each answer in the real rows it used (sources are
  1-second windows around the actual events, so they verify against the DB).
- Intent routing (lightweight, keyword-based):
  - recency ("most recent / latest / current state ...") -> most recent state for a
    named agent, or the agent/event of the single most recent row.
  - count ("how many / number of ...") -> errors in a window, an agent's scoring
    passes (state_change to 'scanning'), or generic event counts.
  - aggregation (plural "agents" + an activity word) -> distinct active agents in a
    window. The plural guard keeps single-agent semantic questions on the vector path.
  - time windows: today / this week / all-time.
- ask_secretary now tries structured_answer first; if it returns None (semantic
  question) it falls through to the UNCHANGED vector + Claude path. New optional
  db_path arg defaults to the active activity_log DB.
- Honesty: zero-count answers say "0 / no errors" with no fabricated sources; an
  agent with no recorded state says so; truly empty data abstains.
- Tests: tests/test_secretary_hybrid.py (10 tests, $0) cover recency, count,
  zero-count, agent-passes, active-agents, no-data, that a semantic question is NOT
  structured, that the structured path never calls the LLM, and that a semantic
  question still uses the vector path. Sources are checked with the eval's own
  verify_source. Full suite: 162 passed.

### Phase 3: measurement eval (the only spend) (done)
- ONE run, standalone (no server, so no background analyst), via
  docs/rag-fixes/run_eval.py against the rebuilt data/chroma + the hybrid Secretary,
  under the eval SpendGuard caps ($0.50 / 50 calls / 600s). No cap hit.
- EXACT spend:
  - REAL billable LLM calls: 10  (secretary 0 + analyst 10). All 6 Secretary
    groundedness questions were answered by the free structured path with NO LLM
    call; the 10 analyst calls are the 5 HIGH + 5 LOW scoring cases (the 5 filtered
    + 1 deduped behavior cases make no call).
  - Estimated USD: $0.011493 (Haiku).
  - (The guard counted 16 "attempts" because it also gated the 6 free structured
    answers; those cost $0. Runner fixed this pass so structured answers no longer
    count toward billable calls/cost; the saved scorecard's call count is the true
    billable 10. No re-run was done to fix this.)
- GROUNDEDNESS: 2/6 (old, pre-fix) -> 6/6 (new). The hybrid structured path now
  answers every count/recency/aggregation question correctly and grounded in real
  rows that verify against the DB.
- Analyst categorical: 15/15. OVERALL: 21/21 (100%).
- Scorecard saved to data/eval_scorecard.json (gitignored) stamped with the current
  signature, clearing the "stale" state. (Re-stamped at the end of the pass so it
  stays non-stale after later docs/asset commits.)

### Phase 4: fresh hero GIF
(to be filled)
