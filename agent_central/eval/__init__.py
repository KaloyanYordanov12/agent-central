"""Evaluator agent — an honest eval harness for Agent Central.

Two ground-truth regimes, kept methodologically honest:

1. Secretary groundedness (questions.py): OBJECTIVE. The true answer is computed
   directly from the SQLite activity_log with code. The database is the ground
   truth, never a model's opinion. Provenance: "computed from activity_log".

2. Job Analyst categorical cases (analyst_cases.py): model-drafted at full effort
   by Opus 4.8, kept CLEAR-CUT, and human-reviewable. The ground truth is the
   expected CATEGORY/band (high / low / filtered / deduped), never a precise
   model-picked number. Provenance: "model-drafted (Opus 4.8), clear-cut", which
   flips to "human-reviewed" on any case a human has actually checked.

All graders live in grader.py; the suite runner (under the SpendGuard hard caps)
lives in runner.py. These fixtures are version-controlled test assets and are
committed (NOT under the gitignored data/).
"""
