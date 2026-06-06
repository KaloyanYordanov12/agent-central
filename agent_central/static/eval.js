/* Evaluator scorecard popup (console tier) over /api/eval/*.
 *
 * Mirrors secretary.js / job_analyst.js: wires the static #eval-popup markup,
 * exposes window.openEvaluatorPopup / closeEvaluatorPopup, and calls
 * window.setEvaluatorGlow(bool) while open. Shows the honest scorecard: overall
 * pass rate, per-agent results with a ground-truth provenance label on every
 * check, the actual failing cases, and a guarded "Run evals" button.
 */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }
  function popupEl() { return $("eval-popup"); }
  function isOpen() {
    const p = popupEl();
    return p && !p.classList.contains("hidden");
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // ---- provenance label (the honesty marker) ----
  function provBadge(prov) {
    const p = String(prov || "");
    let cls = "prov-model";
    if (p.indexOf("computed from") === 0) cls = "prov-objective";
    else if (p.indexOf("human-reviewed") === 0) cls = "prov-human";
    return '<span class="prov-badge ' + cls + '">' + escapeHtml(p) + "</span>";
  }

  function passPill(passed) {
    return passed
      ? '<span class="pass-pill">PASS</span>'
      : '<span class="fail-pill">FAIL</span>';
  }

  function nrFlag(needsReview) {
    return needsReview ? ' <span class="nr-flag">needs review</span>' : "";
  }

  // ---- open / close ----
  function openEvaluatorPopup() {
    const p = popupEl();
    if (!p) return;
    p.classList.remove("hidden");
    activateTab("scorecard");
    fetchScorecard();
    if (window.setEvaluatorGlow) window.setEvaluatorGlow(true);
  }

  function closeEvaluatorPopup() {
    const p = popupEl();
    if (!p) return;
    p.classList.add("hidden");
    if (window.setEvaluatorGlow) window.setEvaluatorGlow(false);
  }

  function activateTab(name) {
    document.querySelectorAll("#eval-popup .tab-button").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === name);
    });
    document.querySelectorAll("#eval-popup .tab-panel").forEach((panel) => {
      panel.classList.toggle("hidden", panel.dataset.panel !== name);
    });
  }

  // ---- render ----
  function fmtTs(ts) {
    if (!ts) return "never";
    try { return new Date(ts).toLocaleString(); } catch (e) { return ts; }
  }

  function renderNeverRun() {
    $("eval-scorecard").innerHTML =
      '<div class="ask-empty">No eval has run yet. Click <b>Run evals</b> to ' +
      'generate a scorecard.<br><span class="ae-note">A run scores a fixed suite ' +
      'with Claude Haiku under hard caps (about $0.50 / 50 calls / 10 min max). ' +
      'It needs <code>ANTHROPIC_API_KEY</code> on the server.</span></div>';
    $("eval-failing").innerHTML = '<div class="sec-muted">No results yet.</div>';
  }

  function renderScorecard(card) {
    const o = card.overall || {};
    const spend = card.spend || {};
    const pct = Math.round((o.pass_rate || 0) * 100);
    const cost = (spend.estimated_cost_usd == null)
      ? "n/a" : "$" + Number(spend.estimated_cost_usd).toFixed(4);
    const calls = (spend.calls == null) ? "n/a" : spend.calls;

    let html =
      '<div class="eval-overall">' +
        '<span class="eval-rate">' + pct + "%</span>" +
        '<span class="eval-rate-sub">' + (o.passed || 0) + " / " + (o.total || 0) +
          " checks passed</span>" +
        '<span class="eval-spend">' + calls + " LLM calls &middot; " + cost +
          " &middot; run " + escapeHtml(fmtTs(card.generated_at)) + "</span>" +
      "</div>";

    if (card.capped) {
      html += '<div class="ja-paused"><b>Run hit a cap.</b> Stopped by the <code>' +
        escapeHtml(card.capped) + "</code> cap; some checks may not have run.</div>";
    }
    if (card.needs_review && card.needs_review.length) {
      html += '<div class="sec-muted">' + card.needs_review.length +
        " case(s) flagged for human review (see the badges below).</div>";
    }

    (card.sections || []).forEach((s) => {
      const sum = s.summary || {};
      html +=
        '<div class="eval-section-head">' +
          escapeHtml(s.agent) + " &middot; " + escapeHtml(s.check) + " " +
          provBadge(s.provenance) +
          ' <span class="eval-rate-sub">' + (sum.passed || 0) + "/" + (sum.total || 0) +
          "</span></div>";
      (s.results || []).forEach((r) => {
        const label = r.title || r.question || r.id || "?";
        html +=
          '<div class="history-item eval-row">' + passPill(r.passed) +
          '<span class="hi-agent">' + escapeHtml(label) + "</span>" +
          provBadge(r.provenance || s.provenance) + nrFlag(r.needs_review) +
          "</div>";
      });
    });
    $("eval-scorecard").innerHTML = html;
  }

  function renderFailing(card) {
    const fails = card.failing || [];
    if (!fails.length) {
      $("eval-failing").innerHTML =
        '<div class="sec-muted">No failing checks. Every check passed.</div>';
      return;
    }
    $("eval-failing").innerHTML = fails.map((f) => {
      const label = f.title || f.question || f.id || "?";
      // Honest "expected truth" + "what the agent said" + "why it failed".
      let expected;
      if (f.expected_band) expected = f.expected + " band " + JSON.stringify(f.expected_band);
      else if (f.expected != null) expected = String(f.expected);
      else if (f.truth != null) expected = JSON.stringify(f.truth);
      else expected = "(see check)";
      let said;
      if (f.score != null) said = "score " + f.score;
      else if (f.answer) said = f.answer;
      else if (f.observed) said = JSON.stringify(f.observed);
      else said = "(no answer)";
      const why = f.reason || f.outcome || "did not match expected";
      const hall = (f.hallucinated_sources && f.hallucinated_sources.length)
        ? '<div class="efc-line"><span class="efc-k">hallucinated sources:</span> ' +
          escapeHtml(f.hallucinated_sources.join(", ")) + "</div>"
        : "";
      return (
        '<div class="eval-fail-card">' +
          '<div class="efc-title">' + escapeHtml(f.agent) + " &middot; " +
            escapeHtml(f.check) + " " + provBadge(f.provenance) + nrFlag(f.needs_review) +
          "</div>" +
          '<div class="efc-line">' + escapeHtml(label) + "</div>" +
          '<div class="efc-line"><span class="efc-k">expected:</span> ' +
            escapeHtml(expected) + "</div>" +
          '<div class="efc-line"><span class="efc-k">agent said:</span> ' +
            escapeHtml(String(said).slice(0, 400)) + "</div>" +
          '<div class="efc-line"><span class="efc-k">why it failed:</span> ' +
            escapeHtml(why) + "</div>" + hall +
        "</div>"
      );
    }).join("");
  }

  function renderStale(card) {
    const msg = (card && card.message)
      ? card.message
      : "The eval suite changed since this scorecard was generated.";
    const last = (card && card.generated_at)
      ? '<br><span class="ae-note">Last run: ' + escapeHtml(fmtTs(card.generated_at)) +
        "</span>"
      : "";
    $("eval-scorecard").innerHTML =
      '<div class="ask-empty"><b>This scorecard is out of date.</b><br>' +
      escapeHtml(msg) + last +
      '<br><span class="ae-note">Click Run evals to refresh.</span></div>';
    $("eval-failing").innerHTML = '<div class="sec-muted">No current results.</div>';
  }

  function render(card) {
    if (!card || card.status === "never_run") {
      renderNeverRun();
      return;
    }
    if (card.status === "stale") {
      renderStale(card);
      return;
    }
    renderScorecard(card);
    renderFailing(card);
  }

  function fetchScorecard() {
    $("eval-scorecard").innerHTML = '<div class="sec-muted">Loading…</div>';
    fetch("/api/eval/scorecard")
      .then((r) => { if (!r.ok) throw new Error("http " + r.status); return r.json(); })
      .then(render)
      .catch((err) => {
        console.error("[eval] scorecard fetch failed:", err);
        $("eval-scorecard").innerHTML =
          '<div class="sec-error">Couldn\'t load the scorecard.</div>';
      });
  }

  function runEvals() {
    const btn = $("eval-run-btn");
    const note = $("eval-run-note");
    btn.disabled = true;
    note.textContent = "Running the suite under hard caps (this spends a little)…";
    fetch("/api/eval/run", { method: "POST" })
      .then(async (r) => {
        const data = await r.json().catch(() => ({}));
        if (r.status === 503) throw { kind: "key" };
        if (r.status === 409) throw { kind: "busy" };
        if (!r.ok) throw { kind: "server" };
        return data;
      })
      .then((card) => {
        note.textContent = "Done.";
        render(card);
      })
      .catch((err) => {
        const msg = err && err.kind === "key"
          ? "Needs ANTHROPIC_API_KEY on the server to spend/score."
          : err && err.kind === "busy"
            ? "An eval run is already in progress."
            : "Run failed. See server logs.";
        note.innerHTML = '<span class="sec-error">' + msg + "</span>";
      })
      .finally(() => { btn.disabled = false; });
  }

  function init() {
    const p = popupEl();
    if (!p) return;
    p.querySelector(".secretary-popup-close").addEventListener("click", closeEvaluatorPopup);
    p.querySelector(".secretary-popup-backdrop").addEventListener("click", closeEvaluatorPopup);
    p.querySelectorAll(".tab-button").forEach((b) => {
      b.addEventListener("click", () => activateTab(b.dataset.tab));
    });
    $("eval-run-btn").addEventListener("click", runEvals);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && isOpen()) closeEvaluatorPopup();
    });

    window.openEvaluatorPopup = openEvaluatorPopup;
    window.closeEvaluatorPopup = closeEvaluatorPopup;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
