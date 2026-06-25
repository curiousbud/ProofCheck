# `tests/conftest.py` — Explained

> Defines shared, deterministically generated Excel and PDF fixtures crafted to exercise every match status (EXACT, FUZZY, MISSING, SKIPPED), reverse matching, and a no-text-layer page warning.

## Purpose
This module supplies pytest fixtures used across the test suite. Instead of committing binary `.xlsx`/`.pdf` files, it builds them at runtime with `openpyxl` and `reportlab` so the inputs are fully visible and reproducible. The fixture data (`ROWS` and `PDF_LINES`) is hand-crafted so that each row maps to a known expected status, allowing the pipeline and matcher tests to assert exact counts.

## Dependencies
- **Imports (external):** `pytest` (fixture decorators, `tmp_path_factory`); `openpyxl.Workbook` to author the Excel workbook in memory and save it; `reportlab.lib.pagesizes.letter` and `reportlab.pdfgen.canvas` to draw the PDF with a real text layer on page 1 and a text-free page 2.
- **Imports (internal):** None.
- **Used by:** pytest auto-discovers `conftest.py`; its `excel_path` and `pdf_path` fixtures are consumed by `tests/test_pipeline.py` and `tests/test_api.py`. (`test_normalize.py` and `test_matcher.py` use their own inline data and do not use these fixtures.)

## Line-by-line / block-by-block breakdown

### Module docstring
```python
"""Shared, deterministic test fixtures.

We generate the Excel and PDF on the fly (rather than committing binaries) so the
inputs are visible and reproducible. ...
"""
```
States the design intent: generate inputs at runtime so they are reviewable in source and bit-for-bit reproducible, and craft them to cover every status plus the no-text-layer warning.

### Imports
```python
from __future__ import annotations

import pytest
from openpyxl import Workbook
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
```
`from __future__ import annotations` makes annotations lazy strings. The rest pull in pytest plus the two generators that produce the fixtures.

### `ROWS` — the Excel data rows
```python
ROWS = [
    ("Gauttam Sharma", "CC-101", "Mumbai"),
    ("Priya Nair", "CC-102", "Delhi"),
    ("John Smith", "CC-103", "Bengaluru"),
    ("Zzxqq Nobody", "CC-999", "Atlantis"),
    (None, "CC-105", "Chennai"),
]
```
Five data rows (written after a header row) for columns `Name`, `CC Code`, `City`. Mapping of the **Name** column against the PDF text:
- `"Gauttam Sharma"` → **FUZZY**: PDF has the correctly spelled `"Gautam Sharma"` (one fewer `t`), close enough to clear a 90 threshold but not exact.
- `"Priya Nair"` → **EXACT**: appears verbatim in the PDF.
- `"John Smith"` → **MISSING** by default; the PDF only contains the reversed `"Smith John"`, so it becomes **EXACT** when reverse matching is enabled.
- `"Zzxqq Nobody"` → **MISSING**: appears nowhere in the PDF.
- `(None, ...)` → **SKIPPED**: the blank `Name` cell is skipped (only the `CC Code`/`City` are present in that row).

### `PDF_LINES` — text drawn on page 1
```python
PDF_LINES = [
    "Conference Delegate List",
    "Gautam Sharma   CC-101   Mumbai",
    "Priya Nair   CC-102   Delhi",
    "Smith John   CC-103   Bengaluru",
    "Other attendees from Chennai and elsewhere.",
]
```
Page-1 text layer. Note it contains `Gautam Sharma` (drives the FUZZY against `Gauttam Sharma`), `Priya Nair` (EXACT), and `Smith John` (the reversed form of `John Smith`). It does NOT contain `Zzxqq Nobody`, so that row stays MISSING.

### `excel_path` fixture
```python
@pytest.fixture(scope="session")
def excel_path(tmp_path_factory) -> str:
    path = tmp_path_factory.mktemp("fixtures") / "delegates.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Delegates"
    ws.append(["Name", "CC Code", "City"])
    for row in ROWS:
        ws.append(list(row))
    # A second sheet to prove /inspect reports multiple sheets.
    wb.create_sheet("Notes").append(["Field", "Value"])
    wb.save(path)
    return str(path)
```
Session-scoped so the workbook is built once for the whole test run. It creates a temp `fixtures/delegates.xlsx`, names the active sheet `Delegates`, writes the header row then the five data rows, and adds a second `Notes` sheet so `test_api.py::test_inspect_returns_sheets_and_headers` can confirm multi-sheet reporting. Returns the path as a string.

### `pdf_path` fixture
```python
@pytest.fixture(scope="session")
def pdf_path(tmp_path_factory) -> str:
    path = tmp_path_factory.mktemp("fixtures") / "program.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    y = 720
    for line in PDF_LINES:
        c.drawString(72, y, line)
        y -= 24
    c.showPage()
    # Page 2: a rectangle only, no text -> simulates a scanned/no-text-layer page.
    c.rect(72, 600, 200, 100, stroke=1, fill=0)
    c.showPage()
    c.save()
    return str(path)
```
Session-scoped. Draws each `PDF_LINES` entry on page 1 at x=72, starting y=720 and stepping down 24 points per line, then calls `showPage()` to finalize page 1. Page 2 draws only a rectangle (no `drawString`), simulating a scanned page with no extractable text layer; this triggers the `"no text layer"` warning asserted in `test_pipeline.py::test_warning_for_no_text_layer`. Returns the path as a string.

## Fixtures / Tests / Sections

| Name | What it verifies |
| --- | --- |
| `ROWS` (data) | Source Excel rows crafted so Name maps to EXACT/FUZZY/MISSING×2/SKIPPED. |
| `PDF_LINES` (data) | Page-1 PDF text that produces those statuses (incl. reversed `Smith John`). |
| `excel_path` | Builds a 2-sheet `delegates.xlsx` (Delegates + Notes) and returns its path. |
| `pdf_path` | Builds a 2-page `program.pdf`: page 1 has text, page 2 has no text layer. |

## Notes / gotchas
- **Deterministic fixtures:** inputs are generated from in-source constants, so they are reproducible run-to-run and reviewable in git diffs.
- **Why generated, not committed:** binaries are opaque in version control; generating them keeps the test inputs transparent and avoids storing build artifacts.
- **Session scope:** both fixtures are `scope="session"` so each file is built once, keeping the suite fast.
- **No-text-layer page:** page 2 deliberately has only a rectangle to exercise the warning path without OCR.
- **The blank-row design** is what produces the SKIPPED status and the `pass_rate` denominator of 4 (5 total minus 1 skipped) in the pipeline tests.

## v0.2 changes

Added an autouse `_isolated_db` fixture that points `PROOFCHECK_DB` at a per-test throwaway SQLite file (and calls `store.init_db()`), isolating users/history between tests. Auth stays disabled by default; auth tests opt in via `PROOFCHECK_AUTH`.

