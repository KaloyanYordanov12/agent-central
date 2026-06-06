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

### Phase 1: index rebuild
(to be filled)

### Phase 2: hybrid-retrieval design
(to be filled)

### Phase 3: measurement eval (the only spend)
(to be filled)

### Phase 4: fresh hero GIF
(to be filled)
