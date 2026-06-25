"use strict";
/*
 * ProofCheck SPA — framework-free, offline. Hash-routed views over the /api/* contract.
 * Structure: helpers -> api client -> app state -> views -> router -> boot.
 * No business logic lives here; all matching/normalization/OCR happens server-side.
 */

// ---- helpers ----------------------------------------------------------------
const el = (tag, attrs = {}, ...kids) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null) continue;
    node.appendChild(typeof kid === "string" ? document.createTextNode(kid) : kid);
  }
  return node;
};
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const view = () => document.getElementById("view");
const clearView = () => { view().innerHTML = ""; };

function diffHtml(diff, best) {
  if (!diff || !diff.length) return esc(best || "");
  return diff.map(([op, text]) => {
    const t = esc(text);
    if (op === "equal") return t;
    if (op === "delete") return `<del>${t}</del>`;
    if (op === "insert") return `<ins>${t}</ins>`;
    return `<del>${t}</del>`;
  }).join("");
}

// ---- api client -------------------------------------------------------------
const api = {
  async json(method, url, body) {
    const opts = { method, credentials: "same-origin", headers: {} };
    if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    const res = await fetch(url, opts);
    let data = null;
    try { data = await res.json(); } catch (_) { /* empty body */ }
    if (!res.ok) { const e = new Error((data && (data.error || data.detail)) || res.statusText); e.status = res.status; throw e; }
    return data;
  },
  async form(url, formData) {
    const res = await fetch(url, { method: "POST", body: formData, credentials: "same-origin" });
    let data = null;
    try { data = await res.json(); } catch (_) { /* empty */ }
    if (!res.ok) { const e = new Error((data && (data.error || data.detail)) || res.statusText); e.status = res.status; throw e; }
    return data;
  },
  health: () => api.json("GET", "/api/health"),
  me: () => api.json("GET", "/api/auth/me"),
  login: (username, password) => api.json("POST", "/api/auth/login", { username, password }),
  logout: () => api.json("POST", "/api/auth/logout"),
  history: () => api.json("GET", "/api/history"),
  historyItem: (id) => api.json("GET", `/api/history/${id}`),
  deleteHistory: (id) => api.json("DELETE", `/api/history/${id}`),
};

// ---- app state --------------------------------------------------------------
const state = { health: null, user: null, inspectData: null, lastResult: null };

function banner(kind, msg) { return el("div", { class: `banner ${kind}`, html: msg }); }

// ---- Check view -------------------------------------------------------------
function checkView() {
  clearView();
  const ocrNote = state.health && state.health.ocr_available
    ? '<span class="pill">OCR ready</span>'
    : '<span class="pill" title="Install proofcheck[ocr] + the Tesseract binary to enable">OCR not installed</span>';

  const root = el("div", {},
    el("div", { class: "panel", html: `
      <div class="row">
        <div class="field"><label for="excel">Excel file (.xlsx / .xlsm)</label>
          <input type="file" id="excel" accept=".xlsx,.xlsm"></div>
        <div class="field"><label for="pdf">PDF file (.pdf)</label>
          <input type="file" id="pdf" accept=".pdf"></div>
      </div>
      <div class="row">
        <div class="field" style="max-width:240px;"><label for="sheet">Sheet</label>
          <select id="sheet"></select></div>
        <div class="field"><label for="columns">Columns to check (one or more)</label>
          <select id="columns" multiple></select>
          <span class="muted">Loaded from the Excel file. Hold Ctrl/Cmd for multiple.</span></div>
      </div>
      <div class="field" style="max-width:360px;">
        <label for="threshold">Fuzzy threshold: <span id="thresholdVal">90</span></label>
        <input type="range" id="threshold" min="0" max="100" value="90"></div>
      <div class="checks">
        <label><input type="checkbox" id="normalize_digits"> Normalize digits</label>
        <label><input type="checkbox" id="strip_punctuation"> Strip punctuation</label>
        <label><input type="checkbox" id="fold_diacritics"> Fold diacritics</label>
        <label><input type="checkbox" id="reverse"> Reverse word order</label>
        <label><input type="checkbox" id="all_columns"> Check all columns</label>
        <label><input type="checkbox" id="ocr"> OCR scanned pages ${ocrNote}</label>
      </div>
      <div id="ocrOpts" class="row hidden" style="margin-top:.5rem;">
        <div class="field" style="max-width:160px;"><label for="ocr_lang">OCR language(s)</label>
          <input type="text" id="ocr_lang" value="eng" placeholder="eng+ara"></div>
        <div class="field" style="max-width:140px;"><label for="ocr_dpi">OCR DPI</label>
          <input type="number" id="ocr_dpi" value="300" min="72" max="1200" step="50"></div>
      </div>
      <div style="margin-top:1rem;">
        <button class="primary" id="run" disabled>Run check</button>
        <span id="hint" class="muted">Select an Excel and a PDF file to begin.</span>
      </div>`}),
    el("div", { id: "msgs" }),
    el("div", { id: "results", class: "hidden" })
  );
  view().appendChild(root);
  wireCheck();
}

function wireCheck() {
  const $ = (id) => document.getElementById(id);
  const updateRun = () => { $("run").disabled = !($("excel").files.length && $("pdf").files.length); };

  $("threshold").addEventListener("input", () => { $("thresholdVal").textContent = $("threshold").value; });
  $("pdf").addEventListener("change", updateRun);
  $("ocr").addEventListener("change", () => $("ocrOpts").classList.toggle("hidden", !$("ocr").checked));

  $("excel").addEventListener("change", async () => {
    updateRun();
    if (!$("excel").files.length) return;
    $("msgs").innerHTML = "";
    const fd = new FormData(); fd.append("excel", $("excel").files[0]);
    try {
      state.inspectData = await api.form("/api/inspect", fd);
      populatePickers(state.inspectData);
    } catch (e) {
      if (e.status === 401) return redirectLogin();
      $("msgs").appendChild(banner("err", "Inspect failed: " + esc(e.message)));
    }
  });

  $("run").addEventListener("click", runCheck);

  function populatePickers(data) {
    const sheetSel = $("sheet"); sheetSel.innerHTML = "";
    data.sheets.forEach((s) => sheetSel.appendChild(el("option", { value: s }, s)));
    const fill = () => {
      const cols = (data.headers[sheetSel.value] || []).filter(Boolean);
      const colSel = $("columns"); colSel.innerHTML = "";
      cols.forEach((c) => colSel.appendChild(el("option", { value: c }, c)));
    };
    sheetSel.onchange = fill; fill();
  }

  async function runCheck() {
    $("msgs").innerHTML = "";
    const fd = new FormData();
    fd.append("excel", $("excel").files[0]);
    fd.append("pdf", $("pdf").files[0]);
    fd.append("columns", Array.from($("columns").selectedOptions).map((o) => o.value).join(","));
    fd.append("all_columns", $("all_columns").checked);
    fd.append("sheet", $("sheet").value);
    fd.append("header_row", "1");
    fd.append("fuzzy_threshold", $("threshold").value);
    fd.append("normalize_digits", $("normalize_digits").checked);
    fd.append("strip_punctuation", $("strip_punctuation").checked);
    fd.append("fold_diacritics", $("fold_diacritics").checked);
    fd.append("reverse", $("reverse").checked);
    fd.append("ocr", $("ocr").checked);
    fd.append("ocr_lang", $("ocr_lang").value || "eng");
    fd.append("ocr_dpi", $("ocr_dpi").value || "300");

    const btn = $("run");
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>Running…';
    try {
      state.lastResult = await api.form("/api/check", fd);
      renderResults(state.lastResult);
    } catch (e) {
      if (e.status === 401) return redirectLogin();
      $("msgs").appendChild(banner("err", "Check failed: " + esc(e.message)));
    } finally {
      btn.disabled = false; btn.textContent = "Run check"; updateRun();
    }
  }
}

function renderResults(data) {
  const card = (l, v) => `<div class="card"><div class="n">${v}</div><div class="l">${l}</div></div>`;
  const s = data.summary;
  const results = document.getElementById("results");
  results.classList.remove("hidden");
  results.innerHTML = `
    <div class="panel">
      <div class="cards">
        ${card("Total", s.total)}${card("Exact", s.exact)}${card("Fuzzy", s.fuzzy)}
        ${card("Missing", s.missing)}${card("Skipped", s.skipped)}
        ${card("Pass rate", (s.pass_rate * 100).toFixed(1) + "%")}
      </div>
      ${data.warnings && data.warnings.length
        ? `<div class="banner" style="margin-top:1rem;"><b>Warnings</b><ul>${data.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>`
        : ""}
      <div style="margin-top:1rem;">
        <a class="report" href="${esc(data.report_urls.html)}" target="_blank">Download HTML report</a> &nbsp;
        <a class="report" href="${esc(data.report_urls.xlsx)}">Download xlsx report</a>
      </div>
    </div>
    <div class="panel">
      <div class="toolbar">
        <label>Filter:
          <select id="statusFilter">
            <option value="">All</option><option value="EXACT">Exact</option>
            <option value="FUZZY">Fuzzy</option><option value="MISSING">Missing</option>
            <option value="SKIPPED">Skipped</option>
          </select>
        </label>
        <input type="search" id="search" placeholder="Search expected / match…">
      </div>
      <div id="tables"></div>
    </div>`;
  document.getElementById("statusFilter").addEventListener("change", renderTables);
  document.getElementById("search").addEventListener("input", renderTables);
  renderTables();
}

function renderTables() {
  const data = state.lastResult;
  if (!data) return;
  const filter = document.getElementById("statusFilter").value;
  const query = document.getElementById("search").value.trim().toLowerCase();
  const container = document.getElementById("tables"); container.innerHTML = "";

  data.columns.forEach((col) => {
    const rows = col.results.filter((r) => {
      if (filter && r.status !== filter) return false;
      if (query && !((r.expected + " " + (r.best_match || "")).toLowerCase().includes(query))) return false;
      return true;
    });
    if (!rows.length) return;
    container.appendChild(el("h3", {}, col.name));
    const table = el("table", { html:
      "<thead><tr><th>Row</th><th>Status</th><th>Expected</th><th>Best match / diff</th><th>Page</th><th>Score</th></tr></thead><tbody>" +
      rows.map((r) =>
        `<tr><td>${r.row}</td><td><span class="badge b-${r.status}">${r.status}</span></td>` +
        `<td>${esc(r.expected)}</td><td>${diffHtml(r.diff, r.best_match)}</td>` +
        `<td>${r.page == null ? "" : r.page}</td><td>${r.score}</td></tr>`
      ).join("") + "</tbody>" });
    container.appendChild(table);
  });
  if (!container.innerHTML) container.innerHTML = '<p class="muted">No rows match the current filter.</p>';
}

// ---- History views ----------------------------------------------------------
async function historyView() {
  clearView();
  view().appendChild(el("div", { class: "panel", id: "histPanel", html: '<p class="muted">Loading history…</p>' }));
  try {
    const data = await api.history();
    renderHistory(data.runs);
  } catch (e) {
    if (e.status === 401) return redirectLogin();
    document.getElementById("histPanel").innerHTML = "";
    document.getElementById("histPanel").appendChild(banner("err", "Could not load history: " + esc(e.message)));
  }
}

function renderHistory(runs) {
  const panel = document.getElementById("histPanel");
  panel.innerHTML = "<h2>Run history</h2>";
  if (!runs.length) { panel.appendChild(el("p", { class: "muted" }, "No runs yet. Run a check to see it here.")); return; }
  const table = el("table", { html:
    "<thead><tr><th>When</th><th>Excel</th><th>PDF</th><th>Pass</th><th>Exact</th><th>Fuzzy</th><th>Missing</th><th></th></tr></thead><tbody>" +
    runs.map((r) =>
      `<tr class="history-row" data-id="${esc(r.run_id)}">
        <td>${esc(r.created_at)}</td><td>${esc(r.excel)}</td><td>${esc(r.pdf)}</td>
        <td>${(r.summary.pass_rate * 100).toFixed(0)}%</td>
        <td>${r.summary.exact}</td><td>${r.summary.fuzzy}</td><td>${r.summary.missing}</td>
        <td><button class="danger" data-del="${esc(r.run_id)}">Delete</button></td>
      </tr>`).join("") + "</tbody>" });
  panel.appendChild(table);

  table.querySelectorAll(".history-row").forEach((tr) => {
    tr.addEventListener("click", (ev) => {
      if (ev.target.matches("[data-del]")) return;
      location.hash = "#/history/" + tr.getAttribute("data-id");
    });
  });
  table.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const id = btn.getAttribute("data-del");
      try { await api.deleteHistory(id); historyView(); }
      catch (e) { alert("Delete failed: " + e.message); }
    });
  });
}

async function historyDetailView(id) {
  clearView();
  view().appendChild(el("div", { class: "panel", id: "detail", html: '<p class="muted">Loading…</p>' }));
  try {
    const r = await api.historyItem(id);
    const card = (l, v) => `<div class="card"><div class="n">${v}</div><div class="l">${l}</div></div>`;
    const flags = Object.entries(r.meta.flags || {}).filter(([, v]) => v).map(([k]) => k);
    document.getElementById("detail").innerHTML = `
      <p><a class="rowlink" href="#/history">← Back to history</a></p>
      <h2>${esc(r.excel)} vs ${esc(r.pdf)}</h2>
      <p class="muted">${esc(r.created_at)} · threshold ${r.meta.fuzzy_threshold}
        ${flags.length ? "· flags: " + flags.map(esc).join(", ") : ""}</p>
      <div class="cards">
        ${card("Total", r.summary.total)}${card("Exact", r.summary.exact)}${card("Fuzzy", r.summary.fuzzy)}
        ${card("Missing", r.summary.missing)}${card("Skipped", r.summary.skipped)}
        ${card("Pass rate", (r.summary.pass_rate * 100).toFixed(1) + "%")}
      </div>
      <div style="margin-top:1rem;">
        <a class="report" href="/reports/${esc(r.run_id)}.html" target="_blank">HTML report</a> &nbsp;
        <a class="report" href="/reports/${esc(r.run_id)}.xlsx">xlsx report</a>
        <span class="muted">(reports expire ~1h after the run; the summary above persists)</span>
      </div>`;
  } catch (e) {
    if (e.status === 401) return redirectLogin();
    document.getElementById("detail").innerHTML = "";
    document.getElementById("detail").appendChild(banner("err", "Could not load run: " + esc(e.message)));
  }
}

// ---- Login view -------------------------------------------------------------
function loginView() {
  clearView();
  const root = el("div", { class: "auth-wrap" },
    el("div", { class: "panel", html: `
      <h2>Sign in</h2>
      <div class="field"><label for="u">Username</label><input type="text" id="u" autocomplete="username"></div>
      <div class="field"><label for="p">Password</label><input type="password" id="p" autocomplete="current-password"></div>
      <div id="loginMsg"></div>
      <button class="primary" id="loginBtn">Sign in</button>` })
  );
  view().appendChild(root);
  const submit = async () => {
    const u = document.getElementById("u").value.trim();
    const p = document.getElementById("p").value;
    document.getElementById("loginMsg").innerHTML = "";
    try {
      const res = await api.login(u, p);
      state.user = res;
      refreshUserBox();
      location.hash = "#/check";
    } catch (e) {
      document.getElementById("loginMsg").appendChild(banner("err", esc(e.message)));
    }
  };
  document.getElementById("loginBtn").addEventListener("click", submit);
  document.getElementById("p").addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
}

// ---- chrome / router --------------------------------------------------------
function refreshUserBox() {
  const box = document.getElementById("userBox");
  const authOn = state.health && state.health.auth_enabled;
  if (authOn && state.user && state.user.authenticated) {
    document.getElementById("userName").textContent = state.user.username;
    box.classList.remove("hidden");
  } else {
    box.classList.add("hidden");
  }
}

function setActiveNav(route) {
  document.querySelectorAll("#nav a[data-route]").forEach((a) =>
    a.classList.toggle("active", a.getAttribute("data-route") === route));
}

function redirectLogin() { location.hash = "#/login"; }

async function router() {
  const hash = location.hash || "#/check";
  const parts = hash.replace(/^#\//, "").split("/");
  const route = parts[0] || "check";
  const authOn = state.health && state.health.auth_enabled;

  // Gate everything except the login screen when auth is enabled and we're not signed in.
  if (authOn && !(state.user && state.user.authenticated) && route !== "login") {
    return redirectLogin();
  }

  setActiveNav(route === "history" ? "history" : route === "check" ? "check" : "");
  if (route === "login") return loginView();
  if (route === "history") return parts[1] ? historyDetailView(parts[1]) : historyView();
  return checkView();
}

async function boot() {
  document.getElementById("logoutBtn").addEventListener("click", async () => {
    try { await api.logout(); } catch (_) { /* ignore */ }
    state.user = { username: "", authenticated: false };
    refreshUserBox();
    redirectLogin();
  });

  try { state.health = await api.health(); } catch (_) { state.health = { auth_enabled: false, ocr_available: false, version: "?" }; }
  document.getElementById("footer").textContent =
    `ProofCheck v${state.health.version} · deterministic, offline` +
    (state.health.auth_enabled ? " · auth enabled" : "");

  if (state.health.auth_enabled) {
    try { state.user = await api.me(); } catch (_) { state.user = { username: "", authenticated: false }; }
  } else {
    state.user = { username: "anonymous", authenticated: false };
  }
  refreshUserBox();

  window.addEventListener("hashchange", router);
  router();
}

boot();
