/* Secretary popup (Step 4) — History + Ask tabs over /api/secretary/*.
 *
 * Vanilla JS, no framework. Exposes window.openSecretaryPopup /
 * window.closeSecretaryPopup. Calls window.setSecretaryGlow(bool) — defined by
 * the Phaser scene in index.html — to highlight the Secretary sprite while the
 * popup is open. Fetch URLs are same-origin relative paths.
 */
(function () {
  "use strict";

  const knownAgents = new Set();

  function $(id) { return document.getElementById(id); }
  function popupEl() { return $("secretary-popup"); }
  function isOpen() {
    const p = popupEl();
    return p && !p.classList.contains("hidden");
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // ---- open / close ----
  function openSecretaryPopup() {
    const p = popupEl();
    if (!p) return;
    p.classList.remove("hidden");
    activateTab("history");
    fetchHistory();
    if (window.setSecretaryGlow) window.setSecretaryGlow(true);
  }

  function closeSecretaryPopup() {
    const p = popupEl();
    if (!p) return;
    p.classList.add("hidden");
    if (window.setSecretaryGlow) window.setSecretaryGlow(false);
  }

  // ---- tabs ----
  function activateTab(name) {
    document.querySelectorAll("#secretary-popup .tab-button").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === name);
    });
    document.querySelectorAll("#secretary-popup .tab-panel").forEach((panel) => {
      panel.classList.toggle("hidden", panel.dataset.panel !== name);
    });
  }

  // ---- history ----
  function timeFilterBounds(value) {
    const now = new Date();
    const y = now.getUTCFullYear(), m = now.getUTCMonth(), d = now.getUTCDate();
    if (value === "today") {
      return { since: new Date(Date.UTC(y, m, d)).toISOString() };
    }
    if (value === "yesterday") {
      return {
        since: new Date(Date.UTC(y, m, d - 1)).toISOString(),
        until: new Date(Date.UTC(y, m, d)).toISOString(),
      };
    }
    if (value === "week") {
      return { since: new Date(now.getTime() - 7 * 24 * 3600 * 1000).toISOString() };
    }
    return {};
  }

  function buildHistoryUrl() {
    const params = new URLSearchParams();
    params.set("limit", "100");
    const agent = $("history-agent-filter").value;
    const type = $("history-type-filter").value;
    const bounds = timeFilterBounds($("history-time-filter").value);
    if (agent) params.set("agent_id", agent);
    if (type) params.set("event_type", type);
    if (bounds.since) params.set("since", bounds.since);
    if (bounds.until) params.set("until", bounds.until);
    return "/api/secretary/history?" + params.toString();
  }

  function fmtTs(ts) {
    try { return new Date(ts).toLocaleString(); } catch (e) { return ts; }
  }

  function refreshAgentOptions(events) {
    const sel = $("history-agent-filter");
    events.forEach((e) => {
      if (e.agent_id && !knownAgents.has(e.agent_id)) {
        knownAgents.add(e.agent_id);
        const opt = document.createElement("option");
        opt.value = e.agent_id;
        opt.textContent = e.agent_id;
        sel.appendChild(opt);
      }
    });
  }

  function renderHistory(events) {
    const list = $("history-list");
    if (!events || events.length === 0) {
      list.innerHTML = '<div class="sec-muted">No events yet.</div>';
      return;
    }
    list.innerHTML = events.map((e) => {
      const state = e.state
        ? ' &middot; <span class="sec-state">' + escapeHtml(e.state) + "</span>" : "";
      let detail = "";
      if (e.metadata && e.metadata.previous_state) {
        detail = "from " + escapeHtml(e.metadata.previous_state);
      } else if (e.payload && e.payload.current_action) {
        detail = escapeHtml(String(e.payload.current_action));
      }
      if (detail.length > 80) detail = detail.slice(0, 80) + "…";
      return (
        '<div class="history-item">' +
        '<span class="hi-ts">' + escapeHtml(fmtTs(e.timestamp)) + "</span>" +
        '<span class="hi-agent">' + escapeHtml(e.agent_id || "?") + "</span>" +
        '<span class="hi-type">' + escapeHtml(e.event_type || "?") + "</span>" + state +
        (detail ? '<div class="hi-detail">' + detail + "</div>" : "") +
        "</div>"
      );
    }).join("");
  }

  function fetchHistory() {
    const list = $("history-list");
    list.innerHTML = '<div class="sec-muted">Loading…</div>';
    fetch(buildHistoryUrl())
      .then((r) => { if (!r.ok) throw new Error("http " + r.status); return r.json(); })
      .then((data) => {
        const events = (data && data.events) || [];
        refreshAgentOptions(events);
        renderHistory(events);
      })
      .catch((err) => {
        console.error("[secretary] history fetch failed:", err);
        list.innerHTML = '<div class="sec-error">Couldn\'t load history.</div>';
      });
  }

  // ---- ask ----
  function renderSources(sources) {
    if (!sources || sources.length === 0) return "";
    const rows = sources.map((s) => {
      const score = (s.score === null || s.score === undefined) ? "—" : s.score;
      return "<li><code>" + escapeHtml(s.chunk_id || "?") + "</code> — " +
        escapeHtml(s.agent_id || "?") + ", " +
        escapeHtml(s.window_start || "?") + " → " + escapeHtml(s.window_end || "?") +
        " (score " + escapeHtml(String(score)) + ")</li>";
    }).join("");
    return '<details class="ask-sources"><summary>Show sources (' +
      sources.length + ")</summary><ul>" + rows + "</ul></details>";
  }

  function submitQuestion() {
    const input = $("ask-input");
    const btn = $("ask-submit");
    const question = input.value.trim();
    if (!question) return;

    input.disabled = true;
    btn.disabled = true;

    const box = $("ask-history");
    const pending = document.createElement("div");
    pending.className = "ask-qa";
    pending.innerHTML =
      '<div class="ask-q">' + escapeHtml(question) + "</div>" +
      '<div class="ask-a sec-muted">Thinking…</div>';
    box.appendChild(pending);
    box.scrollTop = box.scrollHeight;

    fetch("/api/secretary/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question, top_k: 5 }),
    })
      .then(async (r) => {
        const data = await r.json().catch(() => ({}));
        if (r.status === 503) throw { kind: "key" };
        if (!r.ok) throw { kind: "server" };
        return data;
      })
      .then((data) => {
        const sources = renderSources(data.sources);
        const meta = data.model
          ? '<div class="ask-meta">' + escapeHtml(data.model) + " · " +
            (data.input_tokens || 0) + "+" + (data.output_tokens || 0) + " tok</div>"
          : "";
        pending.querySelector(".ask-a").outerHTML =
          '<div class="ask-a">' + escapeHtml(data.answer || "") + "</div>" + sources + meta;
      })
      .catch((err) => {
        console.error("[secretary] ask failed:", err);
        const msg = (err && err.kind === "key")
          ? "API key not configured (ANTHROPIC_API_KEY)."
          : "Failed to get an answer. Try again.";
        pending.querySelector(".ask-a").outerHTML =
          '<div class="ask-a sec-error">' + msg + "</div>";
      })
      .finally(() => {
        input.disabled = false;
        btn.disabled = false;
        input.value = "";
        input.focus();
      });
  }

  // ---- wiring ----
  function init() {
    const p = popupEl();
    if (!p) return;
    p.querySelector(".secretary-popup-close").addEventListener("click", closeSecretaryPopup);
    p.querySelector(".secretary-popup-backdrop").addEventListener("click", closeSecretaryPopup);
    p.querySelectorAll(".tab-button").forEach((b) => {
      b.addEventListener("click", () => activateTab(b.dataset.tab));
    });
    ["history-agent-filter", "history-time-filter", "history-type-filter"].forEach((id) => {
      const el = $(id);
      if (el) el.addEventListener("change", fetchHistory);
    });
    $("ask-submit").addEventListener("click", submitQuestion);
    $("ask-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); submitQuestion(); }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && isOpen()) closeSecretaryPopup();
    });

    window.openSecretaryPopup = openSecretaryPopup;
    window.closeSecretaryPopup = closeSecretaryPopup;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
