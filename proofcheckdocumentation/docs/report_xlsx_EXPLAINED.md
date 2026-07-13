# `proofcheck/report_xlsx.py` — Explained

> Turns a `RunResult` into an openpyxl `.xlsx` workbook with a Summary sheet and one color-coded sheet per checked column.

## Purpose
This module renders a `RunResult` (the stable internal contract produced by the ProofCheck pipeline) into an Excel workbook and can save it to disk. It produces a Summary sheet (run metadata, aggregate counts, optional warnings) plus one worksheet per checked column, where each row's Status cell is filled with a color matching the HTML report and web UI. Because xlsx cells cannot carry inline rich markup the way HTML can, diffs are flattened into plain-text markers.

## Dependencies
- **Imports (external):**
  - `openpyxl.Workbook` — the workbook object that is built and saved.
  - `openpyxl.styles.Font, PatternFill` — `PatternFill` provides the solid background colors for status cells; `Font` provides bold headers and the white bold text used on colored status cells.
  - `openpyxl.utils.get_column_letter` — converts a 1-based numeric column index to a column letter (e.g. `3` -> `"C"`) when applying autosize widths.
- **Imports (internal):** `from .models import RunResult, Status` — `RunResult` is the input; `Status` provides the four enum members used as keys in the `_FILLS` color map.
- **Used by:**
  - `proofcheck/cli.py` (imported lazily, then `report_xlsx.write(result, xlsx_out)`).
  - `proofcheck/web/app.py` (`from .. import ... report_xlsx`, then `report_xlsx.write(result, str(_REPORT_DIR / f"{run_id}.xlsx"))`).

## Line-by-line / block-by-block breakdown

### Module docstring
```python
"""xlsx report generated from a :class:`RunResult` (openpyxl).

A Summary sheet plus one sheet per checked column, with status cells color-coded to
match the HTML report and web UI.
"""
```
Declares the output shape (Summary sheet + per-column sheets) and the cross-surface color-coding contract.

### `_FILLS`, `_WHITE`, `_HEADER` — styling constants
```python
_FILLS = {
    Status.EXACT: PatternFill("solid", fgColor="2E7D32"),
    Status.FUZZY: PatternFill("solid", fgColor="F59E0B"),
    Status.MISSING: PatternFill("solid", fgColor="C62828"),
    Status.SKIPPED: PatternFill("solid", fgColor="9E9E9E"),
}
_WHITE = Font(color="FFFFFF", bold=True)
_HEADER = Font(bold=True)
```
- `_FILLS` maps each `Status` to a solid `PatternFill`. The hex colors (`2E7D32`, `F59E0B`, `C62828`, `9E9E9E`) are exactly the HTML report's status colors minus the leading `#`, so a green EXACT / amber FUZZY / red MISSING / grey SKIPPED cell matches the web UI and HTML report.
- `_WHITE` is bold white font, applied on top of the colored fills so status text stays legible against dark backgrounds.
- `_HEADER` is plain bold font for the column-header row of each sheet.

### `_flatten_diff(diff)` — render a diff as plain text
```python
def _flatten_diff(diff: list[tuple[str, str]]) -> str:
    """Render the diff as plain text since xlsx cells can't hold inline markup."""
    out = []
    for op, text in diff:
        if op == "equal":
            out.append(text)
        elif op == "delete":
            out.append(f"[-{text}-]")
        elif op == "insert":
            out.append(f"{{+{text}+}}")
        else:
            out.append(f"[-{text}-]")
    return "".join(out)
```
The xlsx analog of `report_html._diff_html`. Since a cell value is a single plain string with no per-run formatting here, deletions and insertions are encoded with text markers instead of tags:
- `equal` -> text unchanged.
- `delete` -> `[-text-]` (present in expected, absent from match).
- `insert` -> `{+text+}` (present in match, absent from expected). The doubled braces in the f-string (`{{` / `}}`) are escapes that emit literal single braces.
- `replace` (the `else`) is reserved and rendered defensively as a deletion, mirroring the HTML version. No HTML escaping is needed because the value is written as a literal cell string, not markup.

### `_autosize(ws, max_width=60)` — column width fitting
```python
def _autosize(ws, max_width: int = 60) -> None:
    widths: dict[int, int] = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None:
                widths[cell.column] = min(max(widths.get(cell.column, 0), len(str(cell.value))), max_width)
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width + 2
```
Computes a width for each column by scanning every cell:
- For each non-empty cell, it tracks the longest stringified value seen in that column (`max(...)`), capped at `max_width` (default 60) so a long diff or snippet can't blow the column out (`min(..., max_width)`).
- After scanning, each column's `column_dimensions[...].width` is set to that length plus 2 for padding. `get_column_letter` converts the numeric `cell.column` index into the letter key openpyxl expects.

### `build(result)` — construct the workbook
```python
def build(result: RunResult) -> Workbook:
    wb = Workbook()
    summary_ws = wb.active
    summary_ws.title = "Summary"
```
Creates a new workbook and renames the default active sheet to `"Summary"`.

```python
    s = result.summary
    rows = [
        ("ProofCheck report", ""),
        ("Excel", result.meta.excel),
        ("PDF", result.meta.pdf),
        ("Timestamp", result.meta.timestamp),
        ("Fuzzy threshold", result.meta.fuzzy_threshold),
        ("", ""),
        ("Total", s.total),
        ("Exact", s.exact),
        ("Fuzzy", s.fuzzy),
        ("Missing", s.missing),
        ("Skipped", s.skipped),
        ("Pass rate", f"{s.pass_rate * 100:.1f}%"),
    ]
    for label, value in rows:
        summary_ws.append([label, value])
    summary_ws["A1"].font = Font(bold=True, size=14)
```
Builds the Summary sheet as label/value pairs: a title row, run metadata from `result.meta`, a blank spacer row, then the aggregate counts from `Summary`, ending with the pass rate formatted as a one-decimal percentage (same formatting as the HTML report). Each pair is appended as a two-column row. The `A1` title cell is enlarged to bold size 14.

```python
    if result.warnings:
        summary_ws.append(["", ""])
        summary_ws.append(["Warnings", ""])
        for w in result.warnings:
            summary_ws.append(["", w])
    _autosize(summary_ws)
```
If there are warnings, append a blank spacer, a "Warnings" label row, then one row per warning (warning text in column B). Finally autosize the Summary sheet's columns.

```python
    for col in result.columns:
        # Sheet titles are capped at 31 chars and can't contain certain characters.
        title = col.name[:31] or "Column"
        ws = wb.create_sheet(title=title)
        ws.append(["Row", "Status", "Expected", "Best match", "Diff", "Page", "Score"])
        for cell in ws[1]:
            cell.font = _HEADER
```
One worksheet per `ColumnResult`. The sheet title is truncated to Excel's 31-character limit (`col.name[:31]`); if the name is empty, it falls back to `"Column"` (an empty sheet title is invalid). The header row gets the seven column labels and is styled bold via `_HEADER`. Note: the comment also mentions Excel forbids certain characters in sheet titles (e.g. `[ ] : * ? / \`); the code truncates but does not sanitize those, so a column name containing them could still raise in openpyxl.

```python
        for r in col.results:
            ws.append([
                r.row, r.status.value, r.expected, r.best_match or "",
                _flatten_diff(r.diff), r.page if r.page is not None else "", r.score,
            ])
            status_cell = ws.cell(row=ws.max_row, column=2)
            status_cell.fill = _FILLS[r.status]
            status_cell.font = _WHITE
        _autosize(ws)
```
For each `MatchResult`, append a row: 1-based `row`, the status string (`r.status.value`), `expected`, `best_match` (or empty string when `None`), the flattened plain-text diff, `page` (empty string when `None`), and `score`. The just-appended Status cell (column 2 of `ws.max_row`) is then filled with the status color via `_FILLS[r.status]` and given bold white text via `_WHITE`. Each column sheet is autosized last.

```python
    return wb
```
Returns the assembled `Workbook` (not yet saved).

### `write(result, path)` — persist to disk
```python
def write(result: RunResult, path: str) -> None:
    build(result).save(path)
```
Builds the workbook and saves it to `path` via openpyxl's `Workbook.save`. This is the entry point the CLI and web app call.

## Functions / Methods / Classes

| Name | Signature | Returns | Description |
| --- | --- | --- | --- |
| `_flatten_diff` | `_flatten_diff(diff: list[tuple[str, str]]) -> str` | `str` | Flatten a diff into plain text using `[-del-]` / `{+ins+}` markers. |
| `_autosize` | `_autosize(ws, max_width: int = 60) -> None` | `None` | Set each column's width to its longest stringified cell (capped, +2 padding). |
| `build` | `build(result: RunResult) -> Workbook` | `Workbook` | Build the full workbook (Summary sheet + one color-coded sheet per column). |
| `write` | `write(result: RunResult, path: str) -> None` | `None` | Build the workbook and save it to `path`. |

## Key variables / constants

| Name | Purpose |
| --- | --- |
| `_FILLS` | Maps each `Status` to a solid `PatternFill` whose color matches the HTML/web status palette (green/amber/red/grey). |
| `_WHITE` | Bold white `Font` applied to colored status cells for legibility. |
| `_HEADER` | Bold `Font` for sheet header rows. |
| `s` (in `build`) | Local alias for `result.summary`. |
| `rows` (in `build`) | Ordered label/value pairs that make up the Summary sheet. |
| `widths` (in `_autosize`) | Per-column-index map of the longest stringified cell value seen. |
| `title` (in `build`) | Per-column sheet title, truncated to 31 chars with a `"Column"` fallback. |
| `status_cell` (in `build`) | The Status cell of the row just appended, recolored via `_FILLS`. |

## Notes / gotchas
- **No HTML escaping needed:** Values are written as literal cell strings, not markup, so unlike the HTML report there is no escaping step. The flip side is the next point.
- **xlsx can't hold inline markup:** A cell value is a single plain string and there is no per-substring rich text here, so diffs cannot use `<del>`/`<ins>`. `_flatten_diff` encodes them as `[-deleted-]` / `{+inserted+}` text markers instead. The doubled `{{`/`}}` in the f-string are literal-brace escapes.
- **Shared color palette:** `_FILLS` colors (`2E7D32`, `F59E0B`, `C62828`, `9E9E9E`) are the HTML report's status colors without the `#`, keeping the xlsx, HTML, and web UI visually consistent.
- **Sheet-title rules:** Excel caps sheet titles at 31 characters (handled by `col.name[:31]`) and an empty title is invalid (handled by the `or "Column"` fallback). The forbidden-character set (`[ ] : * ? / \`) mentioned in the comment is not stripped, so an unusual column name could still cause openpyxl to error.
- **Autosize is capped:** `_autosize` limits any column to `max_width` (60) characters so a long diff or PDF snippet does not produce an unusably wide column; it also adds +2 padding and skips empty cells.
- **`build` vs `write`:** `build` returns an in-memory `Workbook` (useful for testing or streaming), while `write` is the convenience wrapper that builds and saves.

## v0.2 changes (continued)

Rewritten for readability. The Summary sheet leads with `humanize.summary_sentence` and friendly counts (Found / Found with differences / Not found / Blank / Match rate); each per-column sheet is Row | Value in your spreadsheet | Result | Details, with the Result cell color-coded and the Details cell wrapped. The raw Diff/Score columns are gone (the % similar is folded into the plain-English Details). Depends on humanize.py.


## v0.2 changes (OCR diagnostics + source column)

Per-column sheets gained a 'Matched via' column (Text layer / OCR) between Result and Details.

