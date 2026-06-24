# `proofcheck/excel.py` — Explained

> Read-only loading and inspection of `.xlsx`/`.xlsm` workbooks via openpyxl: list sheets, read header rows, and pull selected columns' values keyed by spreadsheet row number.

## Purpose
This module is the spreadsheet ingestion layer of ProofCheck. It opens workbooks read-only and with computed values (not formulae), enumerates sheets and their header rows for the web column picker, and extracts the cell values of selected columns paired with their 1-based row numbers. It deliberately contains **no matching logic** — it only produces the expected values that later stages compare against the PDF. All behavior is deterministic.

## Dependencies
- **Imports (external):**
  - `from __future__ import annotations` — defers annotation evaluation so `str | None` style unions work and self-referential type hints are cheap.
  - `from dataclasses import dataclass` — used to define the lightweight `ColumnData` container.
  - `from openpyxl import load_workbook` — the actual `.xlsx`/`.xlsm` reader; opened in `read_only` + `data_only` mode.
- **Imports (internal):** None.
- **Used by:**
  - `proofcheck/pipeline.py` — calls `excel.load_columns(...)` and catches `excel.ExcelError` (step 1 of the run pipeline).
  - `proofcheck/web/app.py` — imports the module as `excel_mod` and calls `excel_mod.inspect(path)` for the column-picker endpoint.

## Line-by-line / block-by-block breakdown

### Module docstring & `from __future__ import annotations`
```python
"""Excel loading and inspection (openpyxl).

Read-only access to .xlsx/.xlsm workbooks: list sheets, read header rows, and pull
the values of selected columns. No matching logic here.
"""

from __future__ import annotations
```
States the module's scope and enables postponed evaluation of annotations.

### `class ExcelError(Exception)`
```python
class ExcelError(Exception):
    """Raised for user-facing spreadsheet problems (missing sheet/column, bad file)."""
```
A dedicated exception type so callers (pipeline, web app) can distinguish user-facing spreadsheet issues from unexpected bugs and translate them into clean error messages / HTTP 400s.

### `class ColumnData`
```python
@dataclass
class ColumnData:
    """Values of one column, paired with their 1-based spreadsheet row numbers."""

    name: str
    # (row_number, raw_value) for every data row below the header.
    cells: list[tuple[int, object]]
```
A simple dataclass holding one column's `name` (the header text) and `cells`, a list of `(row_number, raw_value)` tuples. Row numbers are 1-based spreadsheet rows so downstream reports can point users back to the exact cell. `raw_value` is typed `object` because openpyxl returns native Python types (str, int, float, datetime, `None`, etc.).

### `_open(path)`
```python
def _open(path: str):
    try:
        # read_only is fast and memory-light; data_only returns computed values, not formulae.
        return load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises a grab-bag of exceptions on bad files
        raise ExcelError(f"Could not open Excel file: {exc}") from exc
```
Private helper that centralizes workbook opening. `read_only=True` streams rows so large files stay memory-light; `data_only=True` makes openpyxl return the last-computed cell values rather than formula strings (important — formulae would never match the PDF). Any openpyxl failure is wrapped into a user-facing `ExcelError`, preserving the cause via `from exc`.

### `inspect(path)`
```python
def inspect(path: str) -> dict[str, list[str]]:
    """Return {sheet_name: [header, ...]} using row 1 as headers for every sheet."""
    wb = _open(path)
    try:
        result: dict[str, list[str]] = {}
        for ws in wb.worksheets:
            headers = _read_header(ws, header_row=1)
            result[ws.title] = headers
        return result
    finally:
        wb.close()
```
Builds a map of every sheet title to its row-1 headers, used to power the web column picker so users select from real header names instead of typing them. The `try/finally` guarantees `wb.close()` runs even on error (read-only workbooks hold file handles that must be released).

### `sheet_names(path)`
```python
def sheet_names(path: str) -> list[str]:
    wb = _open(path)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()
```
Returns just the list of sheet names, again ensuring the workbook is closed via `finally`.

### `_read_header(ws, header_row)`
```python
def _read_header(ws, header_row: int) -> list[str]:
    """Read a header row into a list of stripped strings (blank cells -> '')."""
    rows = ws.iter_rows(min_row=header_row, max_row=header_row, values_only=True)
    try:
        raw = next(rows)
    except StopIteration:
        return []
    return ["" if v is None else str(v).strip() for v in raw]
```
Reads exactly one row (`min_row == max_row == header_row`) with `values_only=True` so each cell yields its value not a Cell object. `next(rows)` pulls that single row; if the sheet is empty (no such row) `StopIteration` is caught and an empty list returned. Every cell is normalized: `None` becomes `""`, everything else is stringified and `.strip()`ped of surrounding whitespace.

### `load_columns(...)`
```python
def load_columns(
    path: str,
    *,
    sheet: str | None = None,
    header_row: int = 1,
    columns: list[str] | None = None,
    all_columns: bool = False,
) -> list[ColumnData]:
```
The core extraction function. All arguments after `path` are keyword-only (the `*`). It resolves a sheet, reads headers, selects columns, then walks data rows.

```python
    wb = _open(path)
    try:
        if sheet is None:
            ws = wb.active
        elif sheet in wb.sheetnames:
            ws = wb[sheet]
        else:
            raise ExcelError(
                f"Sheet {sheet!r} not found. Available: {', '.join(wb.sheetnames)}"
            )
```
Sheet resolution: `None` -> the workbook's active sheet; a known name -> that sheet; an unknown name -> an `ExcelError` listing available sheets.

```python
        headers = _read_header(ws, header_row)
        if not headers:
            raise ExcelError(f"No header row found at row {header_row}.")
```
Reads headers from the chosen row and errors if the row is empty.

```python
        # Map header name -> column index. First occurrence wins on duplicates.
        header_index: dict[str, int] = {}
        for idx, name in enumerate(headers):
            if name and name not in header_index:
                header_index[name] = idx
```
Builds a name→index lookup. Blank names (`""`) are skipped, and on duplicate headers the **first** occurrence wins (`name not in header_index` guard).

```python
        if all_columns:
            selected = [h for h in headers if h]
        else:
            selected = columns or []
            missing = [c for c in selected if c not in header_index]
            if missing:
                raise ExcelError(
                    f"Column(s) not found: {', '.join(missing)}. "
                    f"Available: {', '.join(header_index)}"
                )
```
Column selection: with `all_columns=True`, every non-blank header is used (order preserved, duplicates de-emphasized only at index level). Otherwise the explicit `columns` list is used (`columns or []` guards against `None`), and any requested column not present raises a descriptive `ExcelError`.

```python
        result = [ColumnData(name=name, cells=[]) for name in selected]
        by_name = {cd.name: cd for cd in result}
```
Pre-creates one `ColumnData` per selected column and a name→object map for fast appends. Note: if `selected` contains duplicate names (possible when `all_columns` and headers repeat — though repeats are filtered there, or if the caller passes duplicate `columns`), `by_name` keeps only the last `ColumnData` of that name.

```python
        for row_num, row in enumerate(
            ws.iter_rows(min_row=header_row + 1, values_only=True),
            start=header_row + 1,
        ):
            for name in selected:
                col_idx = header_index[name]
                value = row[col_idx] if col_idx < len(row) else None
                by_name[name].cells.append((row_num, value))

        return result
    finally:
        wb.close()
```
Iterates data rows starting just below the header. `enumerate(..., start=header_row + 1)` makes `row_num` the true 1-based spreadsheet row. For each selected column it reads the value at that column's index, guarding against short/ragged rows (`col_idx < len(row)` else `None`), and appends `(row_num, value)` to the matching `ColumnData`. The `finally` closes the workbook.

## Functions / Methods / Classes
| Name | Signature | Returns | Description |
| --- | --- | --- | --- |
| `ExcelError` | `class ExcelError(Exception)` | — | User-facing spreadsheet error type. |
| `ColumnData` | `@dataclass ColumnData(name: str, cells: list[tuple[int, object]])` | — | One column's header name + `(row_number, raw_value)` cells. |
| `_open` | `_open(path: str)` | openpyxl `Workbook` | Opens workbook read-only/data-only; wraps failures in `ExcelError`. |
| `inspect` | `inspect(path: str)` | `dict[str, list[str]]` | Maps each sheet name to its row-1 headers (column picker). |
| `sheet_names` | `sheet_names(path: str)` | `list[str]` | Lists all sheet names. |
| `_read_header` | `_read_header(ws, header_row: int)` | `list[str]` | Reads one header row to stripped strings (`None` -> `""`). |
| `load_columns` | `load_columns(path: str, *, sheet=None, header_row=1, columns=None, all_columns=False)` | `list[ColumnData]` | Extracts selected columns' values keyed by 1-based row number. |

## Key variables / constants
| Name | Purpose |
| --- | --- |
| `header_index` | Maps header name -> 0-based column index; first occurrence wins on duplicates. |
| `selected` | Ordered list of column names to extract (all non-blank headers, or the explicit `columns`). |
| `result` | List of `ColumnData` objects being populated and returned. |
| `by_name` | Name -> `ColumnData` lookup for fast per-row appends. |
| `row_num` | Current 1-based spreadsheet row number during data iteration. |
| `missing` | Requested column names absent from the header row (drives error message). |

## Notes / gotchas
- **Determinism:** No AI/ML; output is a pure function of file contents, sheet, header row, and column selection.
- **`data_only=True`:** Returns the workbook's *last cached* computed values. If a file was never opened/recalculated by Excel, formula cells may read as `None` — openpyxl does not evaluate formulae.
- **`read_only=True`:** Streams rows for low memory use, but the workbook must be explicitly closed; every public function uses `try/finally: wb.close()` to release file handles.
- **Row numbers are 1-based** spreadsheet rows (header excluded from data), so downstream reports can cite exact cells.
- **Empty header row** -> `ExcelError("No header row found at row N.")`; an entirely empty sheet makes `_read_header` return `[]` via the `StopIteration` guard.
- **Duplicate headers:** only the first occurrence is indexed; later columns sharing that name are unreachable by name.
- **Ragged rows:** rows shorter than a column's index yield `None` rather than raising `IndexError`.
- **Blank headers** (`""`) are never selectable and are excluded from `all_columns`.
- **Error handling:** all openpyxl failures and missing sheet/column conditions surface as `ExcelError`, which callers translate into clean user messages.
