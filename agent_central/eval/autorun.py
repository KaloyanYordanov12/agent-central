"""Auto-run decision logic for the Evaluator: run infrequently, and SKIP if
nothing that could change the result has changed since the last run.

Re-spending real money to reconfirm an unchanged, fixed eval suite is exactly the
waste we want to avoid, so the auto-run runs at most about once per day and only
when something relevant changed: a new commit (the fixtures + agent code are
version-controlled, so the git HEAD captures them) or an edited candidate profile
(data/profile.yaml, which is gitignored, so it is hashed separately). On-demand
runs via POST /api/eval/run are always available and are the primary path.

These functions are pure / cheap and unit-tested with no spend.
"""
import hashlib
import os
import subprocess

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _git_head_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=_PROJECT_ROOT,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def _profile_hash(profile_path: str) -> str:
    try:
        with open(profile_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def compute_signature(profile_path: str) -> dict:
    """A small fingerprint of everything that could change the eval result.

    commit -> the version-controlled fixtures + agent code; profile_hash -> the
    gitignored candidate profile. If either changes, the suite is worth re-running.
    """
    return {"commit": _git_head_sha(), "profile_hash": _profile_hash(profile_path)}


def should_autorun(scorecard, signature: dict, today: str):
    """Decide whether the infrequent auto-run should run now.

    Returns (run: bool, reason: str). Rules, in order:
      - never run before                  -> run
      - already ran today                 -> skip (at most once/day)
      - signature unchanged since last run -> skip (nothing relevant changed)
      - otherwise (new commit / profile)   -> run
    """
    if (not scorecard or scorecard.get("status") == "never_run"
            or not scorecard.get("generated_at")):
        return True, "never run"
    if scorecard.get("generated_at", "")[:10] == today:
        return False, "already ran today"
    if scorecard.get("signature") == signature:
        return False, "nothing changed since last run (same commit + profile)"
    return True, "new commit or profile change"
