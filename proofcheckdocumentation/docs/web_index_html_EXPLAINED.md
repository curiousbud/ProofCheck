# `proofcheck/web/static/index.html` — Explained

> A single, dependency-free, intentionally disposable vanilla-JS page that drives the ProofCheck workflow purely by calling the backend `/api/*` JSON contract.

## Purpose
This file is the entire ProofCheck frontend: one self-contained HTML document with inline CSS and inline JavaScript and **zero business logic**. All deterministic proof-reading happens server-side; the page only collects inputs, posts them, and renders the JSON it gets back. It is explicitly meant to be thrown away — the swap rule (stated in the file's own header comment) is: delete this file (and anything else in `static/`) and drop in your own build, as long as the replacement keeps calling the same `/api/inspect`, `/api/check`, and `/reports/...` endpoints. No CDNs, no build step, fully offline.

## Dependencies
- **External:** none (no CDNs); a single inline `<style>` block plus a single inline `<script>` block of vanilla JS. No frameworks, no imports.
- **Runtime API dependency:** calls `POST /api/inspect` (to list sheets/headers from the chosen Excel file) and `POST /api/check` (to run the comparison). It also links to report files served under `/reports/...` via the `report_urls.html` / `report_urls.xlsx` values returned by `/api/check`.
- **Used by:** served by `GET /` in `web/app.py`; the FormData field names posted here must match that app's form parameters.

## Structure breakdown

### Markup
The document is a fixed `<header>` (title + tagline) over a centered `<main>` containing three regions:

- **Input panel** (`.panel`):
  - **File inputs** — `#excel` (`accept=".xlsx,.xlsm"`) and `#pdf` (`accept=".pdf"`), side by side in a `.row`.
  - **Sheet dropdown** — `<select id="sheet">`, populated dynamically after inspecting the Excel file.
  - **Multi-select column picker** — `<select id="columns" multiple>` (min-height styled for visibility), with a muted hint to hold Ctrl/Cmd for multiple selection.
  - **Fuzzy threshold slider** — `<input type="range" id="threshold" min="0" max="100" value="90">` with a live readout in `#thresholdVal`.
  - **Checkboxes** — `#normalize_digits`, `#strip_punctuation`, `#reverse` (reverse word order), and `#all_columns` (check all columns).
  - **Run button** — `<button id="run" disabled>` plus a muted `#hint` prompting the user to pick files.
- **Banners** — `#errorBanner` (`.banner.err`, red) and `#warnBanner` (`.banner`, amber), both starting `.hidden`.
- **Results panel** (`#results`, starts `.hidden`): a summary-cards panel (`#cards`) with two report download links (`#dlHtml` opens in a new tab, `#dlXlsx`), and a second panel holding a `.toolbar` (status `#statusFilter` dropdown with All/Exact/Fuzzy/Missing/Skipped options + `#search` box) above the `#tables` container where per-column result tables are injected.

### CSS
All styling is in one inline `<style>`. The key piece is the status color variables declared on `:root`:

```css
--exact:#2e7d32; --fuzzy:#f59e0b; --missing:#c62828; --skipped:#9e9e9e;
```

`--exact` is green, `--fuzzy` amber, `--missing` red, `--skipped` grey. These deliberately **match the colors used in the generated reports**, so the on-screen badges and the downloadable HTML/xlsx reports look consistent. The badge classes consume them:

```css
.badge { font-weight:700; font-size:.72rem; padding:.1rem .45rem; border-radius:4px; color:#fff; }
.b-EXACT{background:var(--exact);} .b-FUZZY{background:var(--fuzzy);} .b-MISSING{background:var(--missing);} .b-SKIPPED{background:var(--skipped);}
```

Diff text gets inline highlighting (`del` red-ish background + strikethrough, `ins` green-ish background, no underline). There is also a `.spinner` shown on the Run button while a check is in flight, driven by a CSS keyframe animation:

```css
.spinner { ... animation:spin .7s linear infinite; ... }
@keyframes spin { to { transform:rotate(360deg); } }
```

A `.hidden { display:none; }` utility toggles the banners and results panel.

### JavaScript
The whole script runs in `"use strict"` mode and keeps a single piece of state, `lastData`, holding the most recent `/api/check` response so the table view can be re-filtered without re-posting.

**`$` helper** — a terse `getElementById` wrapper used everywhere:

```javascript
const $ = (id) => document.getElementById(id);
let lastData = null;
```

**`showError` / `clearError`** — show or hide the red error banner:

```javascript
function showError(msg) {
  const b = $("errorBanner");
  b.textContent = msg; b.classList.remove("hidden");
}
function clearError() { $("errorBanner").classList.add("hidden"); }
```

**`updateRunEnabled`** — enables the Run button only when both files are chosen:

```javascript
function updateRunEnabled() {
  $("run").disabled = !($("excel").files.length && $("pdf").files.length);
}
```

**Threshold input handler** — mirrors the slider value into the label:

```javascript
$("threshold").addEventListener("input", () => { $("thresholdVal").textContent = $("threshold").value; });
$("pdf").addEventListener("change", updateRunEnabled);
```

**Excel change → `/api/inspect` → `populatePickers`** — on selecting an Excel file, posts just that file to `/api/inspect` and uses the response to fill the pickers; surfaces any error in the banner:

```javascript
$("excel").addEventListener("change", async () => {
  updateRunEnabled();
  if (!$("excel").files.length) return;
  clearError();
  const fd = new FormData();
  fd.append("excel", $("excel").files[0]);
  try {
    const res = await fetch("/api/inspect", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) { showError(data.error || data.detail || "Could not inspect file."); return; }
    populatePickers(data);
  } catch (e) { showError("Inspect failed: " + e.message); }
});
```

**`populatePickers`** — fills the sheet dropdown from `data.sheets`, then fills the column multi-select from `data.headers[sheetName]` (skipping falsy headers via `.filter(Boolean)`); re-runs the column fill whenever the sheet changes:

```javascript
function populatePickers(data) {
  const sheetSel = $("sheet");
  sheetSel.innerHTML = "";
  data.sheets.forEach((s) => {
    const o = document.createElement("option"); o.value = s; o.textContent = s; sheetSel.appendChild(o);
  });
  const fillColumns = () => {
    const cols = data.headers[sheetSel.value] || [];
    const colSel = $("columns"); colSel.innerHTML = "";
    cols.filter(Boolean).forEach((c) => {
      const o = document.createElement("option"); o.value = c; o.textContent = c; colSel.appendChild(o);
    });
  };
  sheetSel.onchange = fillColumns;
  fillColumns();
}
```

**Run click → builds FormData → `POST /api/check` → `render`** — assembles every form field (note `columns` is sent as a comma-joined string, `header_row` is hardcoded `"1"`, and the booleans/threshold are stringified), shows the spinner, posts, then renders or errors and always restores the button in `finally`:

```javascript
$("run").addEventListener("click", async () => {
  clearError();
  const fd = new FormData();
  fd.append("excel", $("excel").files[0]);
  fd.append("pdf", $("pdf").files[0]);
  const selected = Array.from($("columns").selectedOptions).map((o) => o.value);
  fd.append("columns", selected.join(","));
  fd.append("all_columns", $("all_columns").checked);
  fd.append("sheet", $("sheet").value);
  fd.append("header_row", "1");
  fd.append("fuzzy_threshold", $("threshold").value);
  fd.append("normalize_digits", $("normalize_digits").checked);
  fd.append("strip_punctuation", $("strip_punctuation").checked);
  fd.append("reverse", $("reverse").checked);

  const btn = $("run");
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>Running…';
  try {
    const res = await fetch("/api/check", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) { showError(data.error || data.detail || "Check failed."); return; }
    lastData = data; render(data);
  } catch (e) {
    showError("Check failed: " + e.message);
  } finally {
    btn.disabled = false; btn.textContent = "Run check"; updateRunEnabled();
  }
});
```

**`card`** — small template helper for a summary card:

```javascript
function card(label, value) {
  return `<div class="card"><div class="n">${value}</div><div class="l">${label}</div></div>`;
}
```

**`render`** — reveals the results panel, builds the summary cards from `data.summary` (total/exact/fuzzy/missing/skipped + a `pass_rate` formatted as a percentage), wires the two report download links from `data.report_urls`, shows/hides the warnings banner (escaping each warning), then calls `renderTables`:

```javascript
function render(data) {
  $("results").classList.remove("hidden");
  const s = data.summary;
  $("cards").innerHTML = [
    card("Total", s.total), card("Exact", s.exact), card("Fuzzy", s.fuzzy),
    card("Missing", s.missing), card("Skipped", s.skipped),
    card("Pass rate", (s.pass_rate * 100).toFixed(1) + "%"),
  ].join("");

  $("dlHtml").href = data.report_urls.html;
  $("dlXlsx").href = data.report_urls.xlsx;

  const warn = $("warnBanner");
  if (data.warnings && data.warnings.length) {
    warn.innerHTML = "<b>Warnings</b><ul>" + data.warnings.map((w) => `<li>${esc(w)}</li>`).join("") + "</ul>";
    warn.classList.remove("hidden");
  } else { warn.classList.add("hidden"); }

  renderTables();
}
```

**`esc`** — HTML-escapes a value before it is interpolated into markup (the page's XSS guard):

```javascript
function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[c]));
}
```

**`diffHtml`** — renders the server's diff as `[op, text]` pairs into `<del>`/`<ins>` markup; falls back to the escaped `best` string when there is no diff, and treats any unknown op as a deletion:

```javascript
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
```

**`renderTables`** — the client-side filter/search renderer: for each column in `lastData.columns`, keeps rows matching the current status filter and the lowercased search query (matched against `expected` + `best_match`), then builds one `<h3>` + `<table>` per non-empty column. Each row shows row number, a colored status badge, escaped expected text, the diff/best-match cell, page (blank if null), and score. If nothing matches, it prints a muted "No rows match" message:

```javascript
function renderTables() {
  if (!lastData) return;
  const filter = $("statusFilter").value;
  const query = $("search").value.trim().toLowerCase();
  const container = $("tables"); container.innerHTML = "";

  lastData.columns.forEach((col) => {
    const rows = col.results.filter((r) => {
      if (filter && r.status !== filter) return false;
      if (query) {
        const hay = (r.expected + " " + (r.best_match || "")).toLowerCase();
        if (!hay.includes(query)) return false;
      }
      return true;
    });
    if (!rows.length) return;
    const h = document.createElement("h3"); h.textContent = col.name; container.appendChild(h);
    const table = document.createElement("table");
    table.innerHTML = "<thead><tr><th>Row</th><th>Status</th><th>Expected</th>" +
      "<th>Best match / diff</th><th>Page</th><th>Score</th></tr></thead><tbody>" +
      rows.map((r) =>
        `<tr><td>${r.row}</td>` +
        `<td><span class="badge b-${r.status}">${r.status}</span></td>` +
        `<td>${esc(r.expected)}</td>` +
        `<td>${diffHtml(r.diff, r.best_match)}</td>` +
        `<td>${r.page == null ? "" : r.page}</td>` +
        `<td>${r.score}</td></tr>`
      ).join("") + "</tbody>";
    container.appendChild(table);
  });
  if (!container.innerHTML) container.innerHTML = '<p class="muted">No rows match the current filter.</p>';
}
```

**Filter / search event handlers** — re-render the tables from cached `lastData` without any network call:

```javascript
$("statusFilter").addEventListener("change", renderTables);
$("search").addEventListener("input", renderTables);
```

## Functions / Handlers

| Name | Trigger | Description |
| --- | --- | --- |
| `$` | called everywhere | `getElementById` shorthand. |
| `showError` | called on any error path | Sets text and unhides the red error banner. |
| `clearError` | start of inspect/run | Hides the error banner. |
| `updateRunEnabled` | excel/pdf change, after run | Enables Run only when both files are present. |
| threshold `input` handler | slider drag | Live-updates the threshold value label. |
| pdf `change` handler | PDF file chosen | Re-evaluates Run button enablement. |
| excel `change` handler | Excel file chosen | Posts file to `/api/inspect`, then `populatePickers`. |
| `populatePickers` | after inspect | Fills sheet dropdown and (per sheet) the column multi-select. |
| `fillColumns` (inner) | sheet selected / initial | Rebuilds the column options from `headers[sheet]`. |
| run `click` handler | Run button | Builds FormData, posts `/api/check`, calls `render`; manages spinner. |
| `card` | from `render` | Returns one summary-card HTML string. |
| `render` | after `/api/check` success | Fills cards, report links, warnings; calls `renderTables`. |
| `esc` | from render/diff/tables | HTML-escapes a string (XSS guard). |
| `diffHtml` | from `renderTables` | Turns `[op,text]` diff pairs into `<del>`/`<ins>` markup. |
| `renderTables` | after render + filter/search | Filters cached rows and rebuilds per-column result tables. |
| statusFilter `change` handler | filter dropdown | Re-runs `renderTables`. |
| search `input` handler | search box typing | Re-runs `renderTables`. |

## Notes / gotchas
- **Zero business logic:** the page never decides what counts as a match — it only displays whatever `/api/check` returns. All determinism lives server-side.
- **Client-side filtering only:** the status filter and search operate purely on the cached `lastData`; changing them never re-posts to the backend.
- **XSS safety via `esc()`:** every server-supplied string (warnings, expected text, diff text) is run through `esc()` before injection. Summary numbers and `report_urls` are interpolated unescaped, so they rely on the backend returning trusted values.
- **Diff rendering mirrors the server contract:** `diffHtml` expects exactly the `[op, text]` pair shape (`equal` / `delete` / `insert`) produced by the backend; unknown ops degrade to `<del>`.
- **FormData field names must match `app.py`:** `excel`, `pdf`, `columns` (comma-joined), `all_columns`, `sheet`, `header_row` (hardcoded `"1"`), `fuzzy_threshold`, `normalize_digits`, `strip_punctuation`, `reverse`. Booleans are sent as their stringified values. Inspect posts only the `excel` field. If you swap this UI out, the replacement must send the same field names.

RUNTIME_EDGES: POST /api/inspect, POST /api/check, GET /reports/... (HTML + xlsx report downloads via data.report_urls), served by GET /
