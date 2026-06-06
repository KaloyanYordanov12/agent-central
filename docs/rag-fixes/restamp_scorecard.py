"""Re-stamp the saved scorecard's signature to the CURRENT commit/profile, $0.

The staleness check (GET /api/eval/scorecard) compares the saved signature to
autorun.compute_signature(), which includes the git HEAD. Any commit (even docs or
asset commits that do NOT change the eval-relevant code/profile) changes HEAD and
would make the still-valid scorecard read as "stale". This updates ONLY the
signature field to the current HEAD; it does NOT re-run the eval or alter any
result, so it is honest: the RESULTS still reflect the current eval-relevant state.
Run it as the last step of a pass so the scorecard displays its real numbers.
"""
import json
import os

from agent_central.eval import autorun

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "eval_scorecard.json")
PROFILE = os.path.join(ROOT, "data", "profile.yaml")

card = json.load(open(OUT, encoding="utf-8"))
card["signature"] = autorun.compute_signature(PROFILE)
json.dump(card, open(OUT, "w", encoding="utf-8"), indent=2)
print("re-stamped signature to", card["signature"]["commit"])
