"""Read-only observability metrics over the existing tables (llm_calls +
activity_log). No writes, no network, no LLM calls. Powers the in-world metrics
dashboard (Stage 3, item B).

compute_metrics(db_path, days) returns a single JSON-able summary:
  - llm: totals, success rate, tokens, cost, avg latency, per-model and per-agent
    breakdowns, and per-day series (ok/error calls, input/output tokens).
  - activity: total events, counts by type and by agent, per-day event volume, and
    per-agent state durations (time spent in each state, from consecutive
    state_change events).
Everything is windowed to the last `days` calendar days (UTC).
"""
import sqlite3
from datetime import datetime, timedelta, timezone


def _day_list(days: int):
    today = datetime.now(timezone.utc).date()
    return [(today - timedelta(days=days - 1 - i)).isoformat() for i in range(days)]


def _round(x, n=6):
    return round(x, n) if x else 0


def compute_metrics(db_path: str, days: int = 14) -> dict:
    days = max(1, min(int(days), 90))
    day_keys = _day_list(days)
    cutoff = day_keys[0] + "T00:00:00"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        llm_rows = conn.execute(
            "SELECT timestamp, agent_id, model, input_tokens, output_tokens, "
            "estimated_cost_usd, duration_ms, ok FROM llm_calls WHERE timestamp >= ?",
            (cutoff,),
        ).fetchall()
        act_rows = conn.execute(
            "SELECT timestamp, agent_id, event_type, state FROM activity_log "
            "WHERE timestamp >= ? ORDER BY agent_id, id",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()

    # ---- LLM metrics ----
    total = ok = err = 0
    tin = tout = 0
    cost = 0.0
    lat_sum = lat_n = 0
    by_model, by_agent = {}, {}
    calls_per_day = {d: {"ok": 0, "error": 0} for d in day_keys}
    tokens_per_day = {d: {"input": 0, "output": 0} for d in day_keys}

    def _bucket(d, key):
        if key not in d:
            d[key] = {"calls": 0, "ok": 0, "error": 0, "input_tokens": 0,
                      "output_tokens": 0, "cost_usd": 0.0}
        return d[key]

    for r in llm_rows:
        total += 1
        is_ok = bool(r["ok"])
        day = r["timestamp"][:10]
        m = _bucket(by_model, r["model"] or "unknown")
        a = _bucket(by_agent, r["agent_id"] or "unknown")
        m["calls"] += 1; a["calls"] += 1
        if is_ok:
            ok += 1; m["ok"] += 1; a["ok"] += 1
            ti = r["input_tokens"] or 0; to = r["output_tokens"] or 0
            tin += ti; tout += to
            m["input_tokens"] += ti; m["output_tokens"] += to
            a["input_tokens"] += ti; a["output_tokens"] += to
            c = r["estimated_cost_usd"] or 0.0
            cost += c; m["cost_usd"] += c; a["cost_usd"] += c
            if r["duration_ms"] is not None:
                lat_sum += r["duration_ms"]; lat_n += 1
            if day in calls_per_day:
                calls_per_day[day]["ok"] += 1
                tokens_per_day[day]["input"] += ti
                tokens_per_day[day]["output"] += to
        else:
            err += 1; m["error"] += 1; a["error"] += 1
            if day in calls_per_day:
                calls_per_day[day]["error"] += 1

    def _list(d):
        out = []
        for k, v in d.items():
            v = dict(v); v["cost_usd"] = _round(v["cost_usd"])
            out.append({"name": k, **v})
        out.sort(key=lambda x: x["calls"], reverse=True)
        return out

    llm = {
        "total": total, "ok": ok, "error": err,
        "success_rate": _round(ok / total, 4) if total else 0,
        "tokens": {"input": tin, "output": tout},
        "cost_usd": _round(cost),
        "avg_latency_ms": int(lat_sum / lat_n) if lat_n else 0,
        "by_model": _list(by_model),
        "by_agent": _list(by_agent),
        "calls_per_day": [{"date": d, **calls_per_day[d]} for d in day_keys],
        "tokens_per_day": [{"date": d, **tokens_per_day[d]} for d in day_keys],
    }

    # ---- activity metrics ----
    by_type, act_by_agent = {}, {}
    events_per_day = {d: 0 for d in day_keys}
    # state durations: walk each agent's ordered events, attribute the gap to the
    # state we were in until the next change.
    durations = {}     # (agent, state) -> seconds
    prev = {}          # agent -> (ts_datetime, state)

    def _parse(ts):
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            return None

    for r in act_rows:
        et = r["event_type"] or "unknown"
        ag = r["agent_id"] or "unknown"
        by_type[et] = by_type.get(et, 0) + 1
        act_by_agent[ag] = act_by_agent.get(ag, 0) + 1
        day = r["timestamp"][:10]
        if day in events_per_day:
            events_per_day[day] += 1
        if et == "state_change" and r["state"]:
            ts = _parse(r["timestamp"])
            if ag in prev and prev[ag][0] and ts:
                gap = (ts - prev[ag][0]).total_seconds()
                if 0 <= gap < 86400 * 2:   # ignore absurd gaps
                    key = (ag, prev[ag][1])
                    durations[key] = durations.get(key, 0.0) + gap
            prev[ag] = (ts, r["state"])

    state_durations = [
        {"agent": ag, "state": st, "seconds": int(sec)}
        for (ag, st), sec in durations.items() if sec >= 1
    ]
    state_durations.sort(key=lambda x: x["seconds"], reverse=True)

    activity = {
        "total_events": len(act_rows),
        "by_type": by_type,
        "by_agent": [{"name": k, "events": v} for k, v in
                     sorted(act_by_agent.items(), key=lambda kv: kv[1], reverse=True)],
        "events_per_day": [{"date": d, "count": events_per_day[d]} for d in day_keys],
        "state_durations": state_durations[:12],
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "llm": llm,
        "activity": activity,
    }
