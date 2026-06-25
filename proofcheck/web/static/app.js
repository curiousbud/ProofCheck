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
  // The OCR pill (id="ocrPill") is filled by applyOcrStatus() from the live /api/health,
  // so restarting the server with OCR installed updates it without a hard page reload.
  const ocrNote = '<span id="ocrPill" class="pill"></span>';

  const root = el("div", {},
    el("div", { class: "panel", html: `
      <div class="row">
        <div class="field"><label for="excel">Excel file (.xlsx / .xlsm)</label>
          <input type="file" id="excel" accept=".xlsx,.xlsm"></div>
        <div class="field"><label for="pdf">PDF or image (.pdf / .png / .jpg …)</label>
          <input type="file" id="pdf" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.gif"></div>
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
        <div class="field" style="max-width:220px;"><label for="ocr_psm">Page layout (PSM)</label>
          <select id="ocr_psm">
            <option value="3" selected>Automatic (3)</option>
            <option value="6">Single block (6)</option>
            <option value="4">Columns (4)</option>
            <option value="11">Sparse text (11)</option>
          </select></div>
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
  applyOcrStatus();          // reflect current (cached) health immediately
  refreshHealthThenApply();  // then re-check the server in case it was just (re)started
}

// Update the OCR pill + checkbox from state.health. When OCR isn't available the checkbox
// is disabled with an explanatory tooltip, so it's clear *why* and how to enable it.
function applyOcrStatus() {
  const pill = document.getElementById("ocrPill");
  if (!pill) return;
  const ready = !!(state.health && state.health.ocr_available);
  pill.textContent = ready ? "OCR ready" : "OCR not installed";
  pill.title = ready
    ? "Tesseract OCR engine detected on the server."
    : "Server can't find OCR. Install with: pip install \"proofcheck[ocr]\" + the Tesseract " +
      "binary, then restart the server. (This pill reflects the server that serves this page.)";
  pill.style.color = ready ? "var(--exact)" : "var(--missing)";
  const box = document.getElementById("ocr");
  if (box) {
    box.disabled = !ready;
    if (!ready && box.checked) {
      box.checked = false;
      document.getElementById("ocrOpts").classList.add("hidden");
    }
  }
}

async function refreshHealthThenApply() {
  try { state.health = await api.health(); } catch (_) { /* keep cached health */ }
  applyOcrStatus();
}

function wireCheck() {
  const $ = (id) => document.getElementById(id);
  const updateRun = () => { $("run").disabled = !($("excel").files.length && $("pdf").files.length); };

  $("threshold").addEventListener("input", () => { $("thresholdVal").textContent = $("threshold").value; });
  $("pdf").addEventListener("change", updateRun);
  $("ocr").addEventListener("change", () => $("ocrOpts").classList.toggle("hidden", !$("ocr").checked));

  // Re-selecting the SAME filename normally does NOT fire `change`, so editing a file and
  // re-uploading it wouldn't update the UI (you'd have to refresh the page). Clearing the
  // input's value when the picker opens guarantees `change` fires every time — even for the
  // same path — so the freshly-saved file content is always what gets read and sent.
  ["excel", "pdf"].forEach((id) => $(id).addEventListener("click", () => { $(id).value = ""; }));

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
      const colSel = $("columns");
      // Preserve the user's column picks across a re-inspect (e.g. after re-uploading an
      // edited file), so they don't have to reselect columns every time.
      const previously = new Set(Array.from(colSel.selectedOptions).map((o) => o.value));
      const cols = (data.headers[sheetSel.value] || []).filter(Boolean);
      colSel.innerHTML = "";
      cols.forEach((c) => {
        const o = el("option", { value: c }, c);
        if (previously.has(c)) o.selected = true;
        colSel.appendChild(o);
      });
    };
    sheetSel.onchange = fill; fill();
  }

  async function runCheck() {
    $("msgs").innerHTML = "";
    // Clearing inputs on click (above) can leave one empty if a picker was cancelled.
    if (!$("excel").files.length || !$("pdf").files.length) {
      $("msgs").appendChild(banner("err", "Please choose both an Excel and a PDF file."));
      updateRun();
      return;
    }
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
    fd.append("ocr_psm", $("ocr_psm").value || "3");

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

// Plain-language mapping, mirroring proofcheck/humanize.py (presentation only — the API
// still uses EXACT/FUZZY/MISSING/SKIPPED).
const HUMAN = {
  EXACT:   { label: "Found",                  icon: "✓", meaning: "Found in the PDF exactly." },
  FUZZY:   { label: "Found with differences", icon: "≈", meaning: "Found, but not an exact match — check the highlighted differences." },
  MISSING: { label: "Not found",              icon: "✗", meaning: "This value could not be found in the PDF." },
  SKIPPED: { label: "Blank",                  icon: "–", meaning: "The spreadsheet cell was empty, so there was nothing to check." },
};

function summarySentence(s) {
  const checked = s.total - s.skipped;
  const parts = [];
  if (s.exact) parts.push(`${s.exact} found`);
  if (s.fuzzy) parts.push(`${s.fuzzy} found with small differences`);
  if (s.missing) parts.push(`${s.missing} not found`);
  const body = parts.length ? parts.join("; ") : "nothing needed checking";
  let out = `We checked ${checked} value${checked === 1 ? "" : "s"} from your spreadsheet against the PDF: ${body}.`;
  if (s.skipped) out += ` ${s.skipped} blank cell${s.skipped === 1 ? " was" : "s were"} skipped.`;
  return out;
}

function sourceBadge(source) {
  if (source === "OCR") return '<span class="src src-ocr" title="Read from a scanned/image page by OCR">OCR</span>';
  if (source === "text") return '<span class="src src-text" title="From the PDF\'s embedded text layer">Text layer</span>';
  return '<span class="src src-none">-</span>';
}

function detailText(r) {
  const where = r.page == null ? "the PDF" : `page ${r.page}`;
  if (r.status === "EXACT") return `Found on ${where}.`;
  if (r.status === "FUZZY")
    return `Found on ${where}, but not an exact match. Your spreadsheet has “${r.expected}”; ` +
           `the PDF shows “${r.best_match || ""}” (${r.score}% similar).`;
  if (r.status === "MISSING")
    return r.best_match
      ? `Not found in the PDF. The closest text was “${r.best_match}” on ${where}, ` +
        `but it was too different (${r.score}% similar).`
      : "Not found anywhere in the PDF.";
  return "The spreadsheet cell was empty, so there was nothing to check.";
}

function renderResults(data) {
  const card = (l, v) => `<div class="card"><div class="n">${v}</div><div class="l">${esc(l)}</div></div>`;
  const s = data.summary;
  const results = document.getElementById("results");
  results.classList.remove("hidden");
  const legend = ["EXACT", "FUZZY", "MISSING", "SKIPPED"].map((st) =>
    `<li><span class="badge b-${st}">${HUMAN[st].icon} ${esc(HUMAN[st].label)}</span> — ${esc(HUMAN[st].meaning)}</li>`
  ).join("");
  results.innerHTML = `
    <div class="panel">
      <p class="lead">${esc(summarySentence(s))}</p>
      <div class="cards">
        ${card("Values checked", s.total - s.skipped)}${card("Found", s.exact)}
        ${card("Found w/ differences", s.fuzzy)}${card("Not found", s.missing)}
        ${card("Blank", s.skipped)}${card("Match rate", (s.pass_rate * 100).toFixed(0) + "%")}
      </div>
      ${data.warnings && data.warnings.length
        ? `<div class="banner" style="margin-top:1rem;"><b>Notes</b><ul>${data.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>`
        : ""}
      <details class="legend"><summary>How to read these results</summary>
        <ul>${legend}<li><b>Matched via</b> — where the PDF text came from: ${sourceBadge("text")} (the PDF's real text) or ${sourceBadge("OCR")} (read from a scanned/image page).</li><li class="muted">In the differences below, <del>red struck-through</del> text is in your spreadsheet but not the PDF; <ins>green</ins> text is in the PDF but not your spreadsheet.</li></ul>
      </details>
      <div style="margin-top:1rem;">
        <a class="report" href="${esc(data.report_urls.html)}" target="_blank">Download printable report</a> &nbsp;
        <a class="report" href="${esc(data.report_urls.xlsx)}">Download Excel report</a>
      </div>
    </div>
    <div class="panel">
      <div class="toolbar">
        <label>Show:
          <select id="statusFilter">
            <option value="">All results</option><option value="EXACT">Found</option>
            <option value="FUZZY">Found with differences</option><option value="MISSING">Not found</option>
            <option value="SKIPPED">Blank</option>
          </select>
        </label>
        <input type="search" id="search" placeholder="Search values…">
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
      "<thead><tr><th>Row</th><th>Value in your spreadsheet</th><th>Result</th><th>Matched via</th><th>Details</th></tr></thead><tbody>" +
      rows.map((r) => {
        let details = esc(detailText(r));
        if (r.status === "FUZZY" && r.diff && r.diff.length) {
          details += `<div class="diffline"><span class="muted">Difference:</span> ${diffHtml(r.diff, r.best_match)}</div>`;
        }
        const value = esc(r.expected) || '<span class="muted">(empty)</span>';
        return `<tr><td>${r.row}</td><td>${value}</td>` +
          `<td><span class="badge b-${r.status}">${HUMAN[r.status].icon} ${esc(HUMAN[r.status].label)}</span></td>` +
          `<td>${sourceBadge(r.source)}</td>` +
          `<td>${details}</td></tr>`;
      }).join("") + "</tbody>" });
    container.appendChild(table);
  });
  if (!container.innerHTML) container.innerHTML = '<p class="muted">No results match the current filter.</p>';
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
    "<thead><tr><th>When</th><th>Spreadsheet</th><th>PDF</th><th>Match rate</th>" +
    "<th>Found</th><th>With differences</th><th>Not found</th><th></th></tr></thead><tbody>" +
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
        ${card("Values checked", r.summary.total - r.summary.skipped)}${card("Found", r.summary.exact)}
        ${card("With differences", r.summary.fuzzy)}${card("Not found", r.summary.missing)}
        ${card("Blank", r.summary.skipped)}${card("Match rate", (r.summary.pass_rate * 100).toFixed(0) + "%")}
      </div>
      <div style="margin-top:1rem;">
        <a class="report" href="/reports/${esc(r.run_id)}.html" target="_blank">Printable report</a> &nbsp;
        <a class="report" href="/reports/${esc(r.run_id)}.xlsx">Excel report</a>
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
