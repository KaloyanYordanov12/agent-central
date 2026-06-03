/* Job Analyst popup (commit 2b) — Recent Scores + Today's Summary tabs over
 * /api/jobs/analyst-activity. Mirrors secretary.js: wires the static
 * #job-analyst-popup markup, exposes window.openJobAnalystPopup /
 * closeJobAnalystPopup, and calls window.setJobAnalystGlow(bool) while open.
 */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }
  function popupEl() { return $("job-analyst-popup"); }
  function isOpen() {
    const p = popupEl();
    return p && !p.classList.contains("hidden");
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function openJobAnalystPopup() {
    const p = popupEl();
    if (!p) return;
    p.classList.remove("hidden");
    activateTab("scores");
    fetchActivity();
    if (window.setJobAnalystGlow) window.setJobAnalystGlow(true);
  }

  function closeJobAnalystPopup() {
    const p = popupEl();
    if (!p) return;
    p.classList.add("hidden");
    if (window.setJobAnalystGlow) window.setJobAnalystGlow(false);
  }

  function activateTab(name) {
    document.querySelectorAll("#job-analyst-popup .tab-button").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === name);
    });
    document.querySelectorAll("#job-analyst-popup .tab-panel").forEach((panel) => {
      panel.classList.toggle("hidden", panel.dataset.panel !== name);
    });
  }

  function scoreClass(score) {
    if (score >= 75) return "job-score-high";
    if (score >= 50) return "job-score-mid";
    return "job-score-low";
  }

  function safeLink(url, label) {
    const u = String(url || "");
    if (/^https?:\/\//i.test(u)) {
      return '<a href="' + escapeHtml(u) + '" target="_blank" rel="noopener">' +
        escapeHtml(label) + "</a>";
    }
    return escapeHtml(label);  // refuse non-http(s) schemes (e.g. javascript:)
  }

  function renderScores(scores) {
    const list = $("ja-scores-list");
    if (!scores || scores.length === 0) {
      list.innerHTML = '<div class="sec-muted">No jobs scored yet.</div>';
      return;
    }
    list.innerHTML = scores.map((s) => {
      const badge = '<span class="job-score-badge ' + scoreClass(s.score) + '">' +
        escapeHtml(s.score) + "</span>";
      const notified = s.notified ? ' &middot; <span class="sec-state">notified</span>' : "";
      return '<div class="history-item">' + badge +
        '<span class="hi-agent">' + safeLink(s.url, s.title) + "</span>" +
        '<span class="hi-type">' + escapeHtml(s.company || "Unknown") + "</span>" + notified +
        (s.reasoning_preview
          ? '<div class="hi-detail">' + escapeHtml(s.reasoning_preview) + "</div>" : "") +
        "</div>";
    }).join("");
  }

  function renderSummary(summary) {
    const el = $("ja-summary");
    const s = summary || {};
    const row = (label, value) =>
      '<div class="history-item"><span class="hi-agent">' + label +
      '</span><span class="hi-type">' + escapeHtml(value) + "</span></div>";
    el.innerHTML =
      row("Scored today", s.scored_today != null ? s.scored_today : 0) +
      row("Notified today", s.notified_today != null ? s.notified_today : 0) +
      row("Avg score today", s.avg_score_today != null ? s.avg_score_today : 0) +
      row("Top score today", s.top_score_today != null ? s.top_score_today : 0);
  }

  function fetchActivity() {
    const list = $("ja-scores-list");
    list.innerHTML = '<div class="sec-muted">Loading…</div>';
    fetch("/api/jobs/analyst-activity?limit=50")
      .then((r) => { if (!r.ok) throw new Error("http " + r.status); return r.json(); })
      .then((data) => {
        renderScores(data.recent_scores || []);
        renderSummary(data.summary || {});
      })
      .catch((err) => {
        console.error("[job_analyst] fetch failed:", err);
        list.innerHTML = '<div class="sec-error">Couldn\'t load analyst activity.</div>';
      });
  }

  function init() {
    const p = popupEl();
    if (!p) return;
    p.querySelector(".secretary-popup-close").addEventListener("click", closeJobAnalystPopup);
    p.querySelector(".secretary-popup-backdrop").addEventListener("click", closeJobAnalystPopup);
    p.querySelectorAll(".tab-button").forEach((b) => {
      b.addEventListener("click", () => activateTab(b.dataset.tab));
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && isOpen()) closeJobAnalystPopup();
    });

    window.openJobAnalystPopup = openJobAnalystPopup;
    window.closeJobAnalystPopup = closeJobAnalystPopup;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
