# `proofcheck/report_html.py` — Explained

> Turns a `RunResult` into a single, self-contained, offline HTML report whose status colors match the web UI and the xlsx report.

## Purpose
This module renders a `RunResult` (the stable internal contract produced by the ProofCheck pipeline) into a complete HTML document string and can write it to disk. The output is fully self-contained: all styling is inlined in a `<style>` block, there are no external CSS/JS/CDN references, and it opens correctly with no network access. It presents a header with run metadata, summary cards, optional warnings, and one table per checked column with per-row status badges and inline word-level diffs.

## Dependencies
- **Imports (external):**
  - `html` (stdlib) — `html.escape` is used to escape every piece of dynamic text (filenames, expected values, diff text, warnings) so that untrusted cell values and PDF snippets can never inject markup into the report.
- **Imports (internal):** `from .models import RunResult, Status` — `RunResult` is the input data structure; `Status` provides the four outcome enum members (`EXACT`, `FUZZY`, `MISSING`, `SKIPPED`) used as keys in the status-to-CSS-class mapping.
- **Used by:**
  - `proofcheck/cli.py` (imported lazily inside the command, then `report_html.write(result, html_out)`).
  - `proofcheck/web/app.py` (`from .. import ... report_html`, then `report_html.write(result, str(_REPORT_DIR / f"{run_id}.html"))`).

## Line-by-line / block-by-block breakdown

### Module docstring
```python
"""Standalone HTML report generated from a :class:`RunResult`.

Self-contained (inline CSS, no CDNs, offline). Status colors match the web UI and
the xlsx report: green EXACT, amber FUZZY, red MISSING, grey SKIPPED.
"""
```
States the two guarantees the rest of the file must uphold: the report is self-contained/offline (no CDNs), and its color palette is shared with both the web UI and the xlsx report.

### `_STATUS_CLASS` — status to CSS class mapping
```python
_STATUS_CLASS = {
    Status.EXACT: "exact",
    Status.FUZZY: "fuzzy",
    Status.MISSING: "missing",
    Status.SKIPPED: "skipped",
}
```
Maps each `Status` enum member to the lowercase CSS class name applied to its badge `<span>`. Those class names are defined in `_CSS` with their corresponding background colors, so this dict is the link between a result's status and its on-screen color.

### `_CSS` — inline stylesheet
```python
_CSS = """
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; color: #1a1a1a; }
...
.exact { background: #2e7d32; } .fuzzy { background: #f59e0b; } .missing { background: #c62828; }
.skipped { background: #9e9e9e; }
del { background: #ffd7d5; text-decoration: line-through; } ins { background: #d7f5dd; text-decoration: none; }
"""
```
The entire stylesheet as one string, injected into a `<style>` tag (no external files). Notable rules:
- Layout primitives: `body`, the summary `.cards`/`.card` flex grid, the amber `.warn` warning box, and `table`/`th`/`td` styling.
- Status colors: `.exact` green `#2e7d32`, `.fuzzy` amber `#f59e0b`, `.missing` red `#c62828`, `.skipped` grey `#9e9e9e`. These are the same four colors used by the xlsx fills (`report_xlsx._FILLS`, minus the `#`) and the web UI, which is how the three surfaces stay visually consistent.
- Diff colors: `del` is rendered with a red/pink background and a line-through (deleted text), `ins` with a green background and no underline (inserted text). This is the HTML representation of a diff.

### `_diff_html(diff)` — render a diff as HTML
```python
def _diff_html(diff: list[tuple[str, str]]) -> str:
    out = []
    for op, text in diff:
        t = html.escape(text)
        if op == "equal":
            out.append(t)
        elif op == "delete":
            out.append(f"<del>{t}</del>")
        elif op == "insert":
            out.append(f"<ins>{t}</ins>")
        else:  # replace (reserved) — render both sides defensively
            out.append(f"<del>{t}</del>")
    return "".join(out)
```
Converts a list of `(op, text)` diff operations (see `models.DiffOp`) into an HTML fragment showing how `expected` becomes `best_match`:
- Every `text` is escaped first (`html.escape`) before any tags are added, so diff content cannot break out of the markup.
- `equal` -> plain text.
- `delete` -> wrapped in `<del>` (red, struck-through; text in expected but missing from the match).
- `insert` -> wrapped in `<ins>` (green; text in the match but not in expected).
- `replace` is reserved in the model (the matcher decomposes replacements into delete+insert), so it is never expected here; the `else` branch defensively renders it as a `<del>` rather than dropping it.
This is the HTML counterpart of `report_xlsx._flatten_diff`, which uses `[-...-]` / `{+...+}` text markers instead of `<del>`/`<ins>` tags.

### `render(result)` — build the full HTML document
```python
def render(result: RunResult) -> str:
    """Return the full HTML document as a string."""
    s = result.summary
    e = html.escape
    cards = [
        ("Total", s.total), ("Exact", s.exact), ("Fuzzy", s.fuzzy),
        ("Missing", s.missing), ("Skipped", s.skipped),
        ("Pass rate", f"{s.pass_rate * 100:.1f}%"),
    ]
```
- `s` aliases `result.summary`; `e` aliases `html.escape` for terse, repeated escaping.
- `cards` is the ordered list of summary tiles. Counts come straight from `Summary`; `pass_rate` (a 0-1 float) is formatted as a one-decimal percentage.

```python
    parts: list[str] = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>ProofCheck report</title>",
        f"<style>{_CSS}</style></head><body>",
        "<h1>ProofCheck report</h1>",
        (f"<div class='meta'>Excel: <b>{e(result.meta.excel)}</b> &nbsp; "
         f"PDF: <b>{e(result.meta.pdf)}</b> &nbsp; "
         f"Threshold: {result.meta.fuzzy_threshold} &nbsp; "
         f"{e(result.meta.timestamp)}</div>"),
        "<div class='cards'>",
    ]
```
The document is assembled incrementally into a `parts` list and joined at the end (efficient string building). The head declares UTF-8, a mobile viewport, a title, and inlines `_CSS`. The `.meta` line echoes run provenance from `result.meta`: the Excel and PDF filenames (escaped), the numeric fuzzy threshold (trusted int, not escaped), and the timestamp. `&nbsp;` separators keep the metadata on one line.

```python
    for label, value in cards:
        parts.append(f"<div class='card'><div class='n'>{value}</div><div class='l'>{label}</div></div>")
    parts.append("</div>")
```
Emits one `.card` per summary tile (big number `.n`, small label `.l`) and closes the `.cards` container. Card values/labels are internally generated (ints and fixed labels), so no escaping is needed.

```python
    if result.warnings:
        parts.append("<div class='warn'><b>Warnings</b><ul>")
        parts.extend(f"<li>{e(w)}</li>" for w in result.warnings)
        parts.append("</ul></div>")
```
If the run produced warnings, render them in the amber `.warn` box as a bulleted list. Each warning string is escaped because warnings may contain document- or input-derived text.

```python
    for col in result.columns:
        parts.append(f"<h2>{e(col.name)}</h2>")
        parts.append("<table><thead><tr><th>Row</th><th>Status</th><th>Expected</th>"
                     "<th>Best match / diff</th><th>Page</th><th>Score</th></tr></thead><tbody>")
        for r in col.results:
            cls = _STATUS_CLASS[r.status]
            diff_cell = _diff_html(r.diff) if r.diff else e(r.best_match or "")
            page = "" if r.page is None else r.page
            parts.append(
                f"<tr><td>{r.row}</td>"
                f"<td><span class='badge {cls}'>{r.status.value}</span></td>"
                f"<td>{e(r.expected)}</td><td>{diff_cell}</td>"
                f"<td>{page}</td><td>{r.score}</td></tr>"
            )
        parts.append("</tbody></table>")
```
One section per `ColumnResult`: an escaped `<h2>` heading plus a table with columns Row / Status / Expected / Best match-diff / Page / Score. For each `MatchResult`:
- `cls` selects the badge color class via `_STATUS_CLASS[r.status]`.
- `diff_cell`: if a structured diff exists, render it with `_diff_html` (already escaped internally); otherwise fall back to the escaped `best_match` (or empty string when `None`). MISSING/SKIPPED rows with no diff still show whatever best match text exists, safely escaped.
- `page` becomes an empty cell when `r.page is None`; otherwise the 1-based page integer.
- The badge text is `r.status.value` (the uppercase string `EXACT`/`FUZZY`/etc.). `r.expected` is escaped; `r.row` and `r.score` are trusted integers.

```python
    parts.append("</body></html>")
    return "".join(parts)
```
Closes the document and returns the whole thing as one string.

### `write(result, path)` — persist to disk
```python
def write(result: RunResult, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render(result))
```
Thin wrapper that renders the document and writes it to `path` as UTF-8 (matching the `<meta charset='utf-8'>` declared in the markup). This is the function the CLI and web app call.

## Functions / Methods / Classes
| Name | Signature | Returns | Description |
| --- | --- | --- | --- |
| `_diff_html` | `_diff_html(diff: list[tuple[str, str]]) -> str` | `str` | Render a list of `(op, text)` diff ops as escaped HTML using `<del>`/`<ins>` tags. |
| `render` | `render(result: RunResult) -> str` | `str` | Build and return the complete self-contained HTML document for a run. |
| `write` | `write(result: RunResult, path: str) -> None` | `None` | Render the report and write it to `path` as UTF-8. |

## Key variables / constants
| Name | Purpose |
| --- | --- |
| `_STATUS_CLASS` | Maps each `Status` enum member to its CSS class name (`exact`/`fuzzy`/`missing`/`skipped`), linking status to badge color. |
| `_CSS` | The full inline stylesheet (layout, cards, warning box, tables, status badge colors, and `del`/`ins` diff colors). Defines the shared color palette. |
| `s` (in `render`) | Local alias for `result.summary`. |
| `e` (in `render`) | Local alias for `html.escape` used throughout `render` for escaping dynamic text. |
| `cards` (in `render`) | Ordered list of `(label, value)` summary tiles, including the formatted pass-rate percentage. |
| `parts` (in `render`) | Accumulator list of HTML fragments joined into the final document. |

## Notes / gotchas
- **HTML escaping:** Every dynamic value derived from input or the document (filenames, timestamp, expected value, best match, diff text, warnings, column names) is passed through `html.escape`. Only trusted internal integers (`row`, `score`, `page`, `fuzzy_threshold`, summary counts) and the fixed enum `status.value` are interpolated unescaped.
- **Self-contained / offline:** All CSS is inlined via `<style>{_CSS}</style>`; there are no `<link>`, `<script>`, or CDN references, so the report renders identically with no internet connection.
- **Shared color palette:** The four status colors (`#2e7d32`, `#f59e0b`, `#c62828`, `#9e9e9e`) are intentionally identical to the xlsx fills in `report_xlsx._FILLS` (there written without the leading `#`) and to the web UI, keeping all three surfaces consistent.
- **Diff representation differs by format:** HTML uses semantic `<del>`/`<ins>` tags with background colors; the xlsx report cannot hold inline markup and instead uses `[-deleted-]` / `{+inserted+}` text markers (`report_xlsx._flatten_diff`).
- **`replace` op is reserved:** The model decomposes replacements into delete+insert, so the `else` branch in `_diff_html` should not normally fire; it defensively renders the text as a deletion rather than silently dropping it.
- **Diff fallback:** When `r.diff` is empty, the "Best match / diff" cell falls back to the escaped `best_match`, so rows without a computed diff still display useful text.

## v0.2 changes (continued)

Rewritten for non-technical readers. Now opens with a one-sentence overview (`humanize.summary_sentence`) and a 'how to read this' legend; each row is explained in plain English (`humanize.detail`) with Found / Found-with-differences / Not-found / Blank badges instead of EXACT/FUZZY/etc. Table columns: Row | Value in your spreadsheet | Result | Details, with red=removed / green=added diff highlighting under fuzzy rows. Document title is now 'ProofCheck results'. Depends on humanize.py (see humanize_EXPLAINED.md).

