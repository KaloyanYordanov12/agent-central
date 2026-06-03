/* Job Scout popup (commit 2b) — Recent Discoveries + Stats tabs over
 * /api/jobs/discovered. Mirrors secretary.js: wires the static #job-scout-popup
 * markup, exposes window.openJobScoutPopup / closeJobScoutPopup, and calls
 * window.setJobScoutGlow(bool) (defined by the Phaser scene) while open.
 * External job text is escaped before insertion.
 */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }
  function popupEl() { return $("job-scout-popup"); }
  function isOpen() {
    const p = popupEl();
    return p && !p.classList.contains("hidden");
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function openJobScoutPopup() {
    const p = popupEl();
    if (!p) return;
    p.classList.remove("hidden");
    activateTab("discoveries");
    fetchDiscoveries();
    if (window.setJobScoutGlow) window.setJobScoutGlow(true);
  }

  function closeJobScoutPopup() {
    const p = popupEl();
    if (!p) return;
    p.classList.add("hidden");
    if (window.setJobScoutGlow) window.setJobScoutGlow(false);
  }

  function activateTab(name) {
    document.querySelectorAll("#job-scout-popup .tab-button").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === name);
    });
    document.querySelectorAll("#job-scout-popup .tab-panel").forEach((panel) => {
      panel.classList.toggle("hidden", panel.dataset.panel !== name);
    });
  }

  function renderDiscoveries(jobs) {
    const list = $("js-discoveries-list");
    if (!jobs || jobs.length === 0) {
      list.innerHTML = '<div class="sec-muted">No jobs discovered yet.</div>';
      return;
    }
    list.innerHTML = jobs.map((j) => (
      '<div class="history-item">' +
      '<span class="hi-agent">' + escapeHtml(j.title) + "</span>" +
      '<span class="hi-type">' + escapeHtml(j.company || "Unknown") + "</span>" +
      ' &middot; <span class="hi-ts">' + escapeHtml(j.source) + "</span>" +
      ' &middot; <span class="sec-state">' + escapeHtml(j.status) + "</span>" +
      (j.location ? '<div class="hi-detail">' + escapeHtml(j.location) + "</div>" : "") +
      "</div>"
    )).join("");
  }

  function renderStats(byStatus, bySource) {
    const el = $("js-stats");
    const block = (title, obj) => {
      const keys = Object.keys(obj || {});
      const rows = keys.length
        ? keys.map((k) => '<div class="history-item"><span class="hi-agent">' +
            escapeHtml(k) + '</span><span class="hi-type">' + escapeHtml(obj[k]) +
            "</span></div>").join("")
        : '<div class="sec-muted">none</div>';
      return '<div class="hi-detail" style="margin:6px 0 2px;font-weight:700;">' +
        title + "</div>" + rows;
    };
    el.innerHTML = block("By status", byStatus) + block("By source", bySource);
  }

  function fetchDiscoveries() {
    const list = $("js-discoveries-list");
    list.innerHTML = '<div class="sec-muted">Loading…</div>';
    const params = new URLSearchParams({ limit: "100" });
    const source = $("js-source-filter").value;
    if (source) params.set("source", source);
    fetch("/api/jobs/discovered?" + params.toString())
      .then((r) => { if (!r.ok) throw new Error("http " + r.status); return r.json(); })
      .then((data) => {
        renderDiscoveries(data.jobs || []);
        renderStats(data.stats_by_status || {}, data.stats_by_source || {});
      })
      .catch((err) => {
        console.error("[job_scout] fetch failed:", err);
        list.innerHTML = '<div class="sec-error">Couldn\'t load discovered jobs.</div>';
      });
  }

  function init() {
    const p = popupEl();
    if (!p) return;
    p.querySelector(".secretary-popup-close").addEventListener("click", closeJobScoutPopup);
    p.querySelector(".secretary-popup-backdrop").addEventListener("click", closeJobScoutPopup);
    p.querySelectorAll(".tab-button").forEach((b) => {
      b.addEventListener("click", () => activateTab(b.dataset.tab));
    });
    const filter = $("js-source-filter");
    if (filter) filter.addEventListener("change", fetchDiscoveries);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && isOpen()) closeJobScoutPopup();
    });

    window.openJobScoutPopup = openJobScoutPopup;
    window.closeJobScoutPopup = closeJobScoutPopup;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
