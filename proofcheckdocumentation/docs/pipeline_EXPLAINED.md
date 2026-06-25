# `proofcheck/pipeline.py` — Explained

> The single shared orchestration entry point (`run(RunConfig) -> RunResult`) that loads Excel columns, extracts PDF text, matches every value, and assembles a complete result — called identically by the CLI and the web API.

## Purpose
This module is the one place that wires the pipeline together: load Excel → extract PDF → match every cell → summarize → assemble a `RunResult`. Both `cli.py` and `web/app.py` are thin wrappers that build a `RunConfig`, call `run()`, and render the returned `RunResult`; there is deliberately no duplicate of this glue elsewhere. It also defines `PipelineError`, the single user-facing exception type that wraps lower-level errors so callers have one thing to catch.

## Dependencies
- **Imports (external):** `os` (stdlib) — `os.path.basename` strips directory paths so `Meta` echoes just the file names.
- **Imports (internal):**
  - `proofcheck.excel` — `load_columns` reads the requested columns; `ExcelError` is its failure type.
  - `proofcheck.pdf` — `extract` returns a text object with `.pages` and `.warnings()`; `PdfError` is its failure type.
  - `proofcheck.matcher` — `match_value` classifies each cell.
  - `proofcheck.models` — `ColumnResult`, `Meta`, `RunConfig`, `RunResult`, `Status`, `Summary`.
- **Used by:** `proofcheck/cli.py` (`run as pipeline_run`), `proofcheck/web/app.py` (`run as pipeline_run`, plus a FastAPI exception handler for `PipelineError`), and `tests/test_pipeline.py`.

## Line-by-line / block-by-block breakdown

### Module docstring and imports

```python
import os

from . import excel, pdf
from .matcher import match_value
from .models import (
    ColumnResult,
    Meta,
    RunConfig,
    RunResult,
    Status,
    Summary,
)
```

The docstring establishes the contract: `run(RunConfig) -> RunResult` performs load-excel → extract-pdf → match → assemble, with no duplicate glue anywhere, and a stable signature so a future background-job runner (arq/RQ) could call it unchanged.

### `PipelineError`

```python
class PipelineError(Exception):
    """User-facing error raised when a run cannot proceed (bad input, no columns)."""
```

A single exception type representing any failure a user should see. Lower-level `ExcelError` / `PdfError` are caught inside `run()` and re-raised as `PipelineError` (with `from exc`), so callers — the CLI's `try/except` and the web app's `@app.exception_handler(PipelineError)` — only need to handle this one class.

### `_summarize`

```python
def _summarize(columns: list[ColumnResult]) -> Summary:
    summary = Summary()
    for col in columns:
        for r in col.results:
            summary.total += 1
            if r.status is Status.EXACT:
                summary.exact += 1
            elif r.status is Status.FUZZY:
                summary.fuzzy += 1
            elif r.status is Status.MISSING:
                summary.missing += 1
            elif r.status is Status.SKIPPED:
                summary.skipped += 1
    checked = summary.total - summary.skipped
    summary.pass_rate = round((summary.exact + summary.fuzzy) / checked, 4) if checked else 0.0
    return summary
```

Aggregates per-cell `MatchResult`s across all columns into a single `Summary`:
- Iterates every result, incrementing `total` and the matching status counter (`exact` / `fuzzy` / `missing` / `skipped`). Identity comparison (`is`) is used because `Status` is an enum.
- **`checked = total - skipped`**: skipped (blank) cells are excluded from the denominator — they represent nothing to verify, so counting them would unfairly depress the rate.
- **`pass_rate`**: `(exact + fuzzy) / checked`, rounded to 4 decimal places. Both EXACT and FUZZY count as passing. If `checked` is `0` (everything was blank, or no results), `pass_rate` is `0.0` to avoid division by zero.

### `run`

```python
def run(config: RunConfig) -> RunResult:
    if not config.all_columns and not config.columns:
        raise PipelineError("No columns selected. Pass column names or enable all-columns.")
```

The public entry point. **Guard:** unless `all_columns` is set or an explicit `columns` list is provided, there is nothing to check, so it raises `PipelineError` up front.

**Step 1 — load Excel columns.**
```python
    try:
        column_data = excel.load_columns(
            config.excel_path,
            sheet=config.sheet,
            header_row=config.header_row,
            columns=config.columns,
            all_columns=config.all_columns,
        )
    except excel.ExcelError as exc:
        raise PipelineError(str(exc)) from exc

    if not column_data:
        raise PipelineError("No columns to check were found on the sheet.")
```
Reads the requested columns from the workbook. Any `ExcelError` (bad path, missing sheet, etc.) is re-wrapped as `PipelineError`. If the load succeeds but matches no columns (e.g. the named headers don't exist), it raises `PipelineError` too.

**Step 2 — extract PDF text.**
```python
    try:
        pdf_text = pdf.extract(config.pdf_path)
    except pdf.PdfError as exc:
        raise PipelineError(str(exc)) from exc
```
Extracts the PDF text layer into a `pdf_text` object exposing `.pages` (page-number → text dict) and `.warnings()`. `PdfError` is likewise re-wrapped.

**Step 3 — match every value in every column.**
```python
    columns: list[ColumnResult] = []
    for cd in column_data:
        col_result = ColumnResult(name=cd.name)
        for row_num, value in cd.cells:
            col_result.results.append(
                match_value(
                    value,
                    pdf_text.pages,
                    fuzzy_threshold=config.fuzzy_threshold,
                    normalize_digits=config.normalize_digits,
                    strip_punctuation=config.strip_punctuation,
                    reverse=config.reverse,
                    row=row_num,
                )
            )
        columns.append(col_result)
```
For each loaded column, a `ColumnResult` is created and each `(row_num, value)` cell is passed to `matcher.match_value` against the full set of PDF pages. The matching flags are taken straight from the `RunConfig`, and the 1-based `row_num` is threaded through so results stay traceable to their spreadsheet rows. Results preserve column and row order (deterministic).

**Step 4 — assemble the result.**
```python
    summary = _summarize(columns)
    meta = Meta(
        excel=os.path.basename(config.excel_path),
        pdf=os.path.basename(config.pdf_path),
        timestamp=Meta.now_iso(),
        fuzzy_threshold=config.fuzzy_threshold,
        flags={
            "normalize_digits": config.normalize_digits,
            "strip_punctuation": config.strip_punctuation,
            "reverse": config.reverse,
            "all_columns": config.all_columns,
        },
    )
    return RunResult(
        meta=meta,
        summary=summary,
        columns=columns,
        warnings=pdf_text.warnings(),
    )
```
`_summarize` rolls up the counts. `Meta` records provenance: the **base file names** only (directories stripped via `os.path.basename`), a UTC ISO-8601 timestamp (`Meta.now_iso()`), the effective threshold, and an echo of the boolean flags. The function returns a fully self-describing `RunResult` carrying `meta`, `summary`, per-column `columns`, and any PDF extraction `warnings()` — everything a CLI report writer or the web JSON layer needs without re-deriving anything.

## Functions / Methods / Classes

| Name | Signature | Returns | Description |
| --- | --- | --- | --- |
| `PipelineError` | `class PipelineError(Exception)` | — | Single user-facing exception; wraps `ExcelError`/`PdfError` and signals invalid runs. |
| `_summarize` | `_summarize(columns: list[ColumnResult]) -> Summary` | `Summary` | Tallies status counts and computes `pass_rate` over non-skipped cells. |
| `run` | `run(config: RunConfig) -> RunResult` | `RunResult` | Orchestrates load → extract → match → assemble; the shared CLI/web entry point. |

## Key variables / constants

| Name | Purpose |
| --- | --- |
| `config` | The `RunConfig` input carrying paths, column selection, and all matching flags. |
| `column_data` | Columns loaded from Excel (`name` + `(row, value)` cells); empty → error. |
| `pdf_text` | PDF extraction object exposing `.pages` (page→text) and `.warnings()`. |
| `columns` | Assembled list of `ColumnResult`s (the per-cell match results). |
| `summary` | Aggregate counts and `pass_rate` from `_summarize`. |
| `checked` | `total - skipped`; denominator for `pass_rate` (excludes blank cells). |
| `meta` | Provenance: base file names, UTC timestamp, threshold, flag echo. |

## Notes / gotchas
- **Single source of truth:** This is the only place the load→extract→match→assemble glue lives; CLI and web both call `run()` so behavior can't drift between them. The stable `run(RunConfig) -> RunResult` signature is intentionally left ready for a background-job runner.
- **Error propagation:** `excel.ExcelError` and `pdf.PdfError` are caught and re-raised as `PipelineError` (`raise PipelineError(str(exc)) from exc`), preserving the chain. Two additional `PipelineError`s are raised directly: no columns selected, and no columns found on the sheet. Callers only catch `PipelineError`.
- **`pass_rate` excludes skipped:** the denominator is `total - skipped`, so blank cells don't drag the rate down; EXACT and FUZZY both count as passing; rounded to 4 dp; `0.0` when nothing was checked (no division by zero).
- **Determinism:** No AI/ML anywhere in the path — given the same inputs and flags, `run()` produces identical results (aside from the wall-clock `Meta.timestamp`).
- **File names, not paths:** `Meta` stores `os.path.basename(...)` so reports don't leak absolute/local directory paths.
- **Order preserved:** columns and rows are processed and stored in their loaded order, keeping output stable and traceable to spreadsheet positions.

## v0.2 changes

`run()` now passes `ocr`/`ocr_dpi`/`ocr_lang` to `pdf.extract` and `fold_diacritics` to `match_value`, and echoes `fold_diacritics` + `ocr` in `Meta.flags`. OCR warnings flow through `pdf_text.warnings()` into `RunResult.warnings` unchanged.


## v0.2 changes (OCR diagnostics + source column)

`run` now passes `ocr_psm` to `pdf.extract` and, after matching, sets each `MatchResult.source` to 'OCR' or 'text' based on whether its matched page is in `pdf_text.ocr_pages`.


## v0.2 changes (image input + engine v3)

`run` now calls `document.extract` (not `pdf.extract`) so the same run handles a PDF, an image, or a folder of images; image inputs are OCR'd with each image as one page. The text-layer-vs-OCR `source` logic is unchanged (image pages are all `ocr_pages` -> source 'OCR').


## v0.2 changes (theme + OCR-cache toggle)

`run` passes `use_cache=config.ocr_cache` to `document.extract` and echoes `ocr_cache` in `Meta.flags`.

