"""Phase 6 tests: infrequent auto-run + skip-if-unchanged (all $0).

Pure decision logic plus the EvaluatorTask SKIP paths. The run path is never
exercised here (that would spend) -- these tests prove the auto-run does NOT run
when it should not, so no money is wasted reconfirming an unchanged suite.
"""
from datetime import datetime, timezone, timedelta

import pytest

from agent_central import api
from agent_central.eval import autorun, scorecard


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def _yesterday_iso():
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


# --- should_autorun decision logic -------------------------------------------

def test_should_autorun_when_never_run():
    sig = {"commit": "abc", "profile_hash": "x"}
    assert autorun.should_autorun(None, sig, _today())[0] is True
    assert autorun.should_autorun({"status": "never_run"}, sig, _today())[0] is True
    assert autorun.should_autorun({}, sig, _today())[0] is True


def test_should_skip_when_already_ran_today():
    sig = {"commit": "abc", "profile_hash": "x"}
    card = {"generated_at": datetime.now(timezone.utc).isoformat(), "signature": sig}
    run, reason = autorun.should_autorun(card, sig, _today())
    assert run is False and "today" in reason


def test_should_skip_when_nothing_changed():
    sig = {"commit": "abc", "profile_hash": "x"}
    card = {"generated_at": _yesterday_iso(), "signature": sig}
    run, reason = autorun.should_autorun(card, sig, _today())
    assert run is False and "nothing changed" in reason


def test_should_run_when_signature_changed():
    old = {"commit": "abc", "profile_hash": "x"}
    new = {"commit": "def", "profile_hash": "x"}  # new commit
    card = {"generated_at": _yesterday_iso(), "signature": old}
    run, reason = autorun.should_autorun(card, new, _today())
    assert run is True and "change" in reason


# --- compute_signature -------------------------------------------------------

def test_compute_signature_shape_and_profile_hash(tmp_path):
    missing = str(tmp_path / "nope.yaml")
    sig = autorun.compute_signature(missing)
    assert set(sig.keys()) == {"commit", "profile_hash"}
    assert sig["profile_hash"] is None  # missing file -> no hash

    p = tmp_path / "profile.yaml"
    p.write_text("name: A\n", encoding="utf-8")
    sig1 = autorun.compute_signature(str(p))
    assert isinstance(sig1["profile_hash"], str) and len(sig1["profile_hash"]) == 64
    p.write_text("name: B\n", encoding="utf-8")
    sig2 = autorun.compute_signature(str(p))
    assert sig1["profile_hash"] != sig2["profile_hash"]  # content change -> new hash


# --- EvaluatorTask SKIP paths (never spend) ----------------------------------

def _spy_build(monkeypatch):
    calls = []
    monkeypatch.setattr(api, "_build_eval_scorecard",
                        lambda: calls.append(1) or {"x": 1})
    return calls


def test_autorun_skips_without_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    calls = _spy_build(monkeypatch)
    task = api.EvaluatorTask(str(tmp_path / "profile.yaml"), str(tmp_path / "sc.json"))
    task._maybe_run()
    assert calls == []  # no key -> cannot spend -> never builds


def test_autorun_skips_when_already_ran_today(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    calls = _spy_build(monkeypatch)
    path = str(tmp_path / "sc.json")
    profile = str(tmp_path / "profile.yaml")
    sig = autorun.compute_signature(profile)
    scorecard.save_scorecard(
        {"generated_at": datetime.now(timezone.utc).isoformat(), "signature": sig}, path)
    task = api.EvaluatorTask(profile, path)
    task._maybe_run()
    assert calls == []  # already ran today -> skip (no re-spend)


def test_autorun_skips_when_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    calls = _spy_build(monkeypatch)
    path = str(tmp_path / "sc.json")
    profile = str(tmp_path / "profile.yaml")
    sig = autorun.compute_signature(profile)  # deterministic (same commit + profile)
    scorecard.save_scorecard({"generated_at": _yesterday_iso(), "signature": sig}, path)
    task = api.EvaluatorTask(profile, path)
    task._maybe_run()
    assert calls == []  # nothing changed since last run -> skip
