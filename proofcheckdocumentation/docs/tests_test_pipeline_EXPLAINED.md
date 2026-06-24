# `tests/test_pipeline.py` — Explained

> End-to-end tests of `proofcheck.pipeline.run`, asserting exact status counts, reverse-mode behavior, the no-text-layer warning, pass-rate math, all-columns mode, and error handling for missing/unknown columns.

## Purpose
These tests drive the full pipeline against the generated Excel and PDF fixtures, verifying that reading the workbook, extracting PDF text, matching, and summarizing all compose correctly. They lock in the exact EXACT/FUZZY/MISSING/SKIPPED counts produced by the crafted fixture data and confirm configuration flags (`reverse`, `all_columns`) and validation errors behave as documented.

## Dependencies
- **Imports (external):** `pytest` (for `pytest.raises`).
- **Imports (internal):** `proofcheck.models` — `RunConfig`, `Status`; `proofcheck.pipeline` — `PipelineError`, `run`.
- **Used by:** Run by pytest. Consumes the `excel_path` and `pdf_path` fixtures from `conftest.py`.

## Line-by-line / block-by-block breakdown

### Imports and `_status_counts` helper
```python
import pytest

from proofcheck.models import RunConfig, Status
from proofcheck.pipeline import PipelineError, run


def _status_counts(result):
    counts = {s: 0 for s in Status}
    for col in result.columns:
        for r in col.results:
            counts[r.status] += 1
    return counts
```
`_status_counts` flattens the result (`result.columns[].results[]`) into a tally of each `Status`, the basis for the count assertions below.

### `test_run_name_column`
```python
def test_run_name_column(excel_path, pdf_path):
    config = RunConfig(
        excel_path=excel_path, pdf_path=pdf_path,
        columns=["Name"], sheet="Delegates", fuzzy_threshold=90,
    )
    result = run(config)
    counts = _status_counts(result)
    assert counts[Status.EXACT] == 1     # Priya Nair
    assert counts[Status.FUZZY] == 1     # Gauttam Sharma
    assert counts[Status.MISSING] == 2   # John Smith (no reverse) + Zzxqq Nobody
    assert counts[Status.SKIPPED] == 1   # blank cell
    assert result.summary.total == 5
```
Runs the `Name` column on the `Delegates` sheet at threshold 90 (reverse off by default). The five fixture rows yield exactly: **1 EXACT** (`Priya Nair`), **1 FUZZY** (`Gauttam Sharma` ≈ `Gautam Sharma`), **2 MISSING** (`John Smith` — only reversed in PDF, plus `Zzxqq Nobody`), **1 SKIPPED** (blank cell), totaling **5**.

### `test_run_with_reverse`
```python
def test_run_with_reverse(excel_path, pdf_path):
    config = RunConfig(
        excel_path=excel_path, pdf_path=pdf_path,
        columns=["Name"], sheet="Delegates", fuzzy_threshold=90, reverse=True,
    )
    counts = _status_counts(run(config))
    # John Smith now matches "Smith John".
    assert counts[Status.EXACT] == 2
    assert counts[Status.MISSING] == 1
```
With `reverse=True`, `John Smith` now matches the reversed `Smith John` in the PDF, so EXACT rises to **2** (`Priya Nair` + `John Smith`) and MISSING drops to **1** (`Zzxqq Nobody`). FUZZY (`Gauttam Sharma`) and SKIPPED are unchanged.

### `test_warning_for_no_text_layer`
```python
def test_warning_for_no_text_layer(excel_path, pdf_path):
    config = RunConfig(excel_path=excel_path, pdf_path=pdf_path, columns=["Name"], sheet="Delegates")
    result = run(config)
    assert any("no text layer" in w for w in result.warnings)
```
Page 2 of the fixture PDF has only a rectangle (no text). The pipeline must emit a `"no text layer"` warning into `result.warnings`. (Default threshold is used here, no explicit value.)

### `test_pass_rate_excludes_skipped`
```python
def test_pass_rate_excludes_skipped(excel_path, pdf_path):
    config = RunConfig(excel_path=excel_path, pdf_path=pdf_path, columns=["Name"], sheet="Delegates")
    result = run(config)
    # checked = 4 (5 total - 1 skipped); pass = exact(1) + fuzzy(1) = 2 -> 0.5
    assert result.summary.pass_rate == 0.5
```
Confirms pass rate excludes SKIPPED rows from the denominator: denominator = 5 total − 1 skipped = 4 checked; numerator = EXACT(1) + FUZZY(1) = 2; `pass_rate == 2/4 == 0.5`.

### `test_all_columns`
```python
def test_all_columns(excel_path, pdf_path):
    config = RunConfig(excel_path=excel_path, pdf_path=pdf_path, all_columns=True, sheet="Delegates")
    result = run(config)
    assert {c.name for c in result.columns} == {"Name", "CC Code", "City"}
```
With `all_columns=True`, the pipeline checks every header on the sheet; the resulting column names are exactly the three headers `{"Name", "CC Code", "City"}`.

### `test_no_columns_raises`
```python
def test_no_columns_raises(excel_path, pdf_path):
    with pytest.raises(PipelineError):
        run(RunConfig(excel_path=excel_path, pdf_path=pdf_path, sheet="Delegates"))
```
With neither `columns` nor `all_columns` specified, the pipeline has nothing to check and must raise `PipelineError`.

### `test_unknown_column_raises`
```python
def test_unknown_column_raises(excel_path, pdf_path):
    with pytest.raises(PipelineError):
        run(RunConfig(excel_path=excel_path, pdf_path=pdf_path, columns=["Nope"], sheet="Delegates"))
```
Requesting a column name (`"Nope"`) that does not exist on the sheet must raise `PipelineError` rather than silently producing empty results.

## Fixtures / Tests / Sections

| Name | What it verifies |
| --- | --- |
| `_status_counts` (helper) | Tallies statuses across all columns/results. |
| `test_run_name_column` | Name column → EXACT 1, FUZZY 1, MISSING 2, SKIPPED 1, total 5. |
| `test_run_with_reverse` | `reverse=True` → EXACT 2, MISSING 1 (John Smith matches). |
| `test_warning_for_no_text_layer` | Emits "no text layer" warning for the blank page 2. |
| `test_pass_rate_excludes_skipped` | `pass_rate == 0.5` (2 passed / 4 checked, skipped excluded). |
| `test_all_columns` | `all_columns=True` checks all three headers. |
| `test_no_columns_raises` | No columns selected → `PipelineError`. |
| `test_unknown_column_raises` | Nonexistent column → `PipelineError`. |

## Notes / gotchas
- **Counts are fixture-driven:** the exact numbers come straight from the crafted `ROWS`/`PDF_LINES` in `conftest.py`; changing those constants would break these assertions.
- **Pass rate excludes SKIPPED** from both numerator and denominator — a documented behavior, not an accident.
- **Default threshold** is exercised in the warning/pass-rate/all-columns tests (no `fuzzy_threshold` passed), implying the default still classifies `Gauttam Sharma` as FUZZY.
- **`PipelineError`** is the single validation error type for both "no columns" and "unknown column" cases.
