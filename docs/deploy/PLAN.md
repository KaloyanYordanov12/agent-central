# Agent Central: read-only public deployment plan

Goal: a public, read-only demo of Agent Central on Kolio's Hetzner VPS, at a real
HTTPS URL with a working WebSocket, running on the RECORDED data and NEVER spending
money. Branch `deploy` (off master); do NOT merge until Kolio confirms the live URL.

THE GOLDEN RULE: the public app runs with ANTHROPIC_API_KEY unset, and every code
path that could call the Anthropic API is disabled or hidden in public mode. A
read-only visitor cannot make it spend.

This is Phase 0 (diagnose + plan). Nothing on the server is touched yet. The end of
this file lists exactly what is needed from Kolio before Phase 2.

---

## 1. Diagnosis: what runs on startup, and every spend path

### Background tasks started in `lifespan` (agent_central/api.py)
1. `StatusPoller` - polls Deal Hunter at http://127.0.0.1:8000/status and broadcasts
   `agent_states` over the WebSocket, deriving the stationary agents' state from the
   recorded activity_log. NO Anthropic spend (localhost HTTP only). On the VPS Deal
   Hunter will be absent, so it shows as offline, which is the honest recorded state.
   KEEP this in public mode (it drives the live office + ticker from recorded data).
2. `IndexerTask` - every 5 min, reads new activity_log events and writes embeddings
   to data/chroma using the LOCAL sentence-transformers model. NO Anthropic spend.
   In public mode there are no new events, so it is a no-op; we will NOT start it
   (nothing to index, and we avoid touching the recorded chroma).
3. `JobScoutTask` - every 3h, fetches public job boards (external HTTP) and writes
   rows to data/discovered_jobs. NO Anthropic spend, but it mutates the recorded
   data and makes outbound requests. Do NOT start in public mode.
4. `JobAnalystTask` - every 5 min, scores discovered jobs via Claude Haiku.
   SPENDS. (With no key it pauses via the F4 backoff, but we will not start it at
   all in public mode.)
5. `EvaluatorTask` (auto-eval) - every 6h, may run the full eval suite (Secretary +
   analyst), which SPENDS. It already self-skips when ANTHROPIC_API_KEY is unset,
   but we will not start it at all in public mode.

### Every code path that can call the Anthropic API
- `JobAnalystTask._run_pass` -> `job_analyst.run_analyst_pass` ->
  `JobAnalystClient.score_job`. (background)
- `EvaluatorTask._maybe_run` -> `_build_eval_scorecard` -> `run_full_suite`
  (Secretary asks + analyst scoring). (background, key-gated)
- `POST /api/eval/run` -> `_build_eval_scorecard`. (endpoint) Currently returns 503
  without a key (RuntimeError from constructing the clients).
- `POST /api/secretary/ask` -> `_get_secretary_deps()` (constructs `SecretaryClient`,
  which raises without a key) then `ask_secretary`. The hybrid Secretary's STRUCTURED
  path (agent_central/structured_qa.py) is pure SQL over activity.db and needs NO key
  and NO network; only the VECTOR fallback calls the LLM.

There is no other Anthropic call site in this repo. Deal Hunter is a separate
service (port 8000), not part of this process.

### Current key-unset behavior (already safe-ish, but not enough)
- JobAnalyst pauses (F4) and the office shows "Job Analyst paused (misconfigured)".
- EvaluatorTask auto-eval self-skips (no key).
- The two spend endpoints return 503 (RuntimeError -> 503), not a friendly refusal.
- A 503 is "accidentally safe"; public mode makes the refusal EXPLICIT and removes
  even the attempt, plus hides the UI affordances that imply spend.

### How the recorded data is read (read-only, no spend)
- `data/activity.db` (SQLite) via `activity_log` (DEFAULT_DB_PATH). Drives the
  WebSocket agent_states, the Secretary History tab, the metrics dashboard, the
  jobs funnel, and the structured Secretary answers.
- `data/chroma` (vector index) only used by the Secretary VECTOR path (disabled in
  public mode) and the indexer (not started in public mode).
- `data/eval_scorecard.json` read by `GET /api/eval/scorecard` (read-only, $0).
- All three live under data/ and are GITIGNORED, so they must be copied to the VPS
  separately (see Phase 2). `.env` is also gitignored.

---

## 2. Plan: a read-only / public mode in the app (Phase 1, code, $0)

Add `PUBLIC_MODE = os.environ.get("AGENT_CENTRAL_PUBLIC", "") in ("1","true","yes")`
in api.py. Everything below is behind this flag, so local dev (key set) is unchanged.

- Startup: when PUBLIC_MODE, start ONLY the `StatusPoller`. Do not start the
  Indexer, JobScout, JobAnalyst, or Evaluator tasks. (No task can spend or mutate
  recorded data.) The office, HUD, ticker, funnel, and WebSocket still work from the
  recorded activity_log.
- `POST /api/eval/run`: in PUBLIC_MODE return 403 with a friendly body
  ("Running the eval suite is disabled in the public demo.") BEFORE doing anything.
- `POST /api/secretary/ask`: in PUBLIC_MODE answer from the STRUCTURED path only
  (recorded data, $0, no key, no network). If the structured path returns None
  (a semantic question), return a friendly 200 answer like "The public demo answers
  from recorded data (counts, recency, which agents were active). Live semantic Q&A
  is disabled here; try the History tab." It NEVER calls `_get_secretary_deps`, the
  embedding model, or the LLM. (Honest option that still demos the hybrid retrieval.
  Alternative if preferred: hide the Ask input entirely and keep History only.)
- New `GET /api/config` -> `{"public_mode": bool}` so the frontend can adapt.
- Frontend (index.html + eval.js + secretary.js): on load, fetch /api/config; when
  public_mode:
  - hide the Evaluator "Run evals" button (`#eval-run-btn`); the scorecard still
    SHOWS the recorded results.
  - show a small tasteful banner: "Public demo: running on recorded data, no live
    API calls." (on-theme, dark console style).
  - set the Ask tab's empty-state hint to the public-mode message (and keep History
    fully working).
- Tests (mock patterns, $0): PUBLIC_MODE -> POST /api/eval/run is 403; POST
  /api/secretary/ask uses the structured path and never constructs the LLM client;
  GET /api/config reports the flag; a helper confirms the spending tasks are not
  started in public mode. Local (non-public) behavior unchanged. Full suite green.

---

## 3. Plan: serve it on the VPS (Phase 2, collaborative)

Reuse Kolio's existing Hetzner + Cloudflare-tunnel + systemd pattern.

- Code: `git clone`/`git pull` the repo (branch `deploy`) to the VPS repo path.
- Recorded data: copy data/activity.db, data/chroma/, and data/eval_scorecard.json
  to the VPS data/ dir (they are gitignored). Method TBD with Kolio (scp from this
  machine, or he copies). Do NOT commit them.
- Python env on the VPS: venv + `pip install -r requirements.txt`.
- systemd service `agentcentral.service`: runs
  `venv/bin/python -m uvicorn agent_central.api:app --host 127.0.0.1 --port 8001`
  with `Environment=AGENT_CENTRAL_PUBLIC=1` and NO ANTHROPIC_API_KEY (explicitly
  unset). `Restart=always`. Binds to 127.0.0.1 only (never expose the raw port).
- Cloudflare named tunnel (Kolio's account): an ingress rule mapping the chosen
  hostname -> http://127.0.0.1:8001, run as its own systemd service (cloudflared).
  The ingress must pass WebSocket for `/ws/status` (cloudflared passes WS by default
  for http ingress; we will test it explicitly, since WS-over-tunnel is the most
  likely thing to break).
- DNS: a CNAME for the chosen subdomain -> the tunnel (Cloudflare dashboard).

I cannot do the Cloudflare/DNS/VPS-shell steps myself; see the STOP list below.

---

## 4. Plan: verify the live URL (Phase 3, collaborative)
- From OUTSIDE the VPS (a real browser, ideally on another network/phone): URL
  loads, office renders, WebSocket connects (agents show recorded state, ticker
  updates), metrics dashboard opens, Evaluator scorecard shows the recorded numbers
  with NO "Run evals" button, public-demo banner visible.
- Zero-spend checks: `POST /api/eval/run` is refused (403); confirm no spending task
  is running; confirm ANTHROPIC_API_KEY is unset in the service environment.
- Resilience: `systemctl restart agentcentral`, and ideally a full reboot, then
  re-check.

---

## 5. STOP: what is needed from Kolio before Phase 2

I will build Phase 1 (the read-only mode + tests) on the branch now. Before any
server work, I need from Kolio:

A. VPS access model: do you want me to drive the VPS over an SSH connection that is
   already configured on this machine (give me the host alias), OR will you run the
   exact commands I provide? I will not invent credentials or SSH access.
B. Domain / subdomain to use for the public URL (e.g. agentcentral.yourdomain.com).
C. The Cloudflare tunnel: is there an existing named tunnel to reuse, or should we
   create a new one? (The token / credentials are yours to paste on the VPS; do not
   send them to me in chat. I will give you the exact `cloudflared` config + the one
   DNS record to add.)
D. The VPS repo path (where the code should live) and the Python version available.
E. Is the old service still running on the VPS (anything on the port/tunnel we would
   reuse)? Should it be stopped first?
F. How to get the recorded data (data/activity.db, data/chroma/,
   data/eval_scorecard.json) onto the VPS: scp from this machine, or you copy them?
G. Ask-tab decision: structured-only public Ask (recommended; demos the hybrid
   retrieval, $0) vs. hiding the Ask input entirely (History only). Default chosen:
   structured-only.

Nothing destructive will be done on the server until these are settled.
