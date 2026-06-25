# `proofcheck/models.py` — Explained

> Defines the dataclasses and enums that form ProofCheck's stable internal contract, describing the result of a check run independent of any presentation format.

## Purpose
This module holds the core data structures that flow through the entire ProofCheck pipeline. The pipeline produces a `RunResult`, and every consumer — the CLI report writers, the xlsx/HTML renderers, and the web JSON layer — reads from it without re-deriving anything. The types are deliberately free of presentation concerns (no HTML, no colors) so each client can render them its own way, and they are kept deterministic to preserve ProofCheck's no-AI guarantee.

## Dependencies
- **Imports (external):**
  - `from __future__ import annotations` — enables PEP 563 deferred annotation evaluation so modern union syntax like `int | None` works regardless of runtime Python version and avoids needing string-quoted forward references.
  - `dataclasses.dataclass`, `dataclasses.field` — `@dataclass` generates boilerplate (`__init__`, `__repr__`, `__eq__`); `field(default_factory=...)` provides safe mutable defaults (lists/dicts) per instance.
  - `datetime.datetime`, `datetime.timezone` — used in `Meta.now_iso()` to produce a UTC ISO-8601 timestamp.
  - `enum.Enum` — base class for the `Status` enumeration.
- **Imports (internal):** None.
- **Used by:**
  - `proofcheck/pipeline.py` (imports `ColumnResult`, `Meta`, `RunConfig`, `RunResult`, `Status`, `Summary`)
  - `proofcheck/matcher.py` (imports `DiffOp`, `MatchResult`, `Status`)
  - `proofcheck/report_html.py` (imports `RunResult`, `Status`)
  - `proofcheck/report_xlsx.py` (imports `RunResult`, `Status`)
  - `proofcheck/cli.py` (imports `RunConfig`, `Status`)
  - `tests/test_pipeline.py`, `tests/test_matcher.py`

## Line-by-line / block-by-block breakdown

### Module docstring
```python
"""Core data structures for ProofCheck.

These dataclasses are the **stable internal contract**. ...
"""
```
States the design intent: these types are the contract between the pipeline and all consumers, and must stay deterministic and presentation-free.

### Future import
```python
from __future__ import annotations
```
Defers evaluation of all annotations to strings. This lets the file use `int | None`, `list[DiffOp]`, etc., as annotations without requiring a newer runtime to evaluate them eagerly.

### `Status` enum
```python
class Status(str, Enum):
    """Outcome of matching a single expected value against the PDF."""

    EXACT = "EXACT"      # found verbatim (after normalization)
    FUZZY = "FUZZY"      # found a close match at/above the fuzzy threshold
    MISSING = "MISSING"  # no match at/above the threshold
    SKIPPED = "SKIPPED"  # nothing to check (blank cell)
```
A string-backed enumeration of the four possible outcomes for one checked value. Subclassing `str` (`class Status(str, Enum)`) means each member *is* a string, so it serializes directly to JSON and compares/equals its string value without extra conversion. The four members:
- `EXACT` — value found verbatim after normalization.
- `FUZZY` — close match scoring at or above the configured threshold.
- `MISSING` — no match reached the threshold.
- `SKIPPED` — the cell was blank, so nothing was checked.

### `DiffOp` type alias
```python
DiffOp = tuple[str, str]
```
A type alias for a single diff operation: `(op, text)`, where `op` is one of `equal | insert | delete | replace`. The accompanying comment documents the semantics — diffs describe how to turn `expected` into `best_match`: `equal` = unchanged, `delete` = present in expected but absent from match, `insert` = present in match but absent from expected, and `replace` is reserved (the matcher decomposes replacements into delete+insert).

### `MatchResult` dataclass
```python
@dataclass
class MatchResult:
    """Result of checking one spreadsheet cell against the PDF."""

    row: int                      # 1-based spreadsheet row of the value
    expected: str                 # the original cell value
    status: Status
    page: int | None = None       # 1-based PDF page where the (best) match was found
    best_match: str | None = None # the closest snippet found in the PDF
    score: int = 0                # fuzzy score 0-100 (100 for EXACT)
    diff: list[DiffOp] = field(default_factory=list)
```
Represents the outcome for one spreadsheet cell. `row` and `expected` plus `status` are required (no defaults). `page` and `best_match` are optional and default to `None` (a `MISSING`/`SKIPPED` result may have no page or snippet). `score` defaults to `0` and is 0–100 (100 for an exact match). `diff` uses `field(default_factory=list)` so each instance gets its own empty list rather than sharing one mutable default.

### `ColumnResult` dataclass
```python
@dataclass
class ColumnResult:
    """All match results for a single spreadsheet column."""

    name: str
    results: list[MatchResult] = field(default_factory=list)
```
Groups every `MatchResult` under its column header `name`. `results` again uses `default_factory=list` for a per-instance empty list.

### `RunConfig` dataclass
```python
@dataclass
class RunConfig:
    """Everything needed to perform one check run. ..."""

    excel_path: str
    pdf_path: str
    columns: list[str] = field(default_factory=list)
    all_columns: bool = False
    sheet: str | None = None          # None -> first/active sheet
    header_row: int = 1               # 1-based row containing column headers
    fuzzy_threshold: int = 90         # 0-100; >= this score counts as FUZZY
    normalize_digits: bool = False    # fold Arabic-Indic & other unicode digits to ASCII
    strip_punctuation: bool = False   # drop punctuation before comparing
    reverse: bool = False             # also try reversed word order (e.g. "Last First")
```
The complete input to a single run. `excel_path` and `pdf_path` are required. `columns` lists which headers to check; when `all_columns` is `True` the pipeline checks every column found and `columns` is ignored (per the docstring). `sheet=None` means the first/active sheet. `header_row` defaults to row 1 (1-based). `fuzzy_threshold=90` is the minimum score (0–100) for a `FUZZY` match. `normalize_digits`, `strip_punctuation`, and `reverse` are normalization/matching flags, all defaulting to `False`.

### `Summary` dataclass
```python
@dataclass
class Summary:
    """Aggregate counts across every checked value."""

    total: int = 0
    exact: int = 0
    fuzzy: int = 0
    missing: int = 0
    skipped: int = 0
    pass_rate: float = 0.0  # (exact + fuzzy) / checked, rounded to 4 dp; checked excludes skipped
```
Holds aggregate counts. All counters default to `0`. `pass_rate` is `(exact + fuzzy) / checked` rounded to 4 decimal places, where `checked` excludes `skipped` values (the actual computation lives in `pipeline.py`; this dataclass just stores the result).

### `Meta` dataclass
```python
@dataclass
class Meta:
    """Provenance / configuration echo for a run."""

    excel: str
    pdf: str
    timestamp: str
    fuzzy_threshold: int
    flags: dict[str, bool]

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
```
Echoes provenance and configuration into the result: the source `excel` and `pdf` paths, the run `timestamp`, the `fuzzy_threshold`, and a `flags` dict of the boolean options. `now_iso()` is a `@staticmethod` helper returning the current UTC time as an ISO-8601 string (`datetime.now(timezone.utc).isoformat()` — timezone-aware UTC, so the string includes an offset).

### `RunResult` dataclass
```python
@dataclass
class RunResult:
    """Complete, self-describing result of a check run."""

    meta: Meta
    summary: Summary
    columns: list[ColumnResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
```
The top-level, self-describing output of a run. Requires a `Meta` and a `Summary`; carries the list of `ColumnResult`s and any `warnings` strings (both default to per-instance empty lists). This is the single object the pipeline returns and every renderer consumes.

## Functions / Methods / Classes
| Name | Signature | Returns | Description |
| --- | --- | --- | --- |
| `Status` | `class Status(str, Enum)` | — | String-backed enum of match outcomes: `EXACT`, `FUZZY`, `MISSING`, `SKIPPED`. |
| `MatchResult` | `@dataclass MatchResult(row, expected, status, page=None, best_match=None, score=0, diff=[])` | — | Result of checking one cell against the PDF. |
| `ColumnResult` | `@dataclass ColumnResult(name, results=[])` | — | All `MatchResult`s for one column. |
| `RunConfig` | `@dataclass RunConfig(excel_path, pdf_path, columns=[], all_columns=False, sheet=None, header_row=1, fuzzy_threshold=90, normalize_digits=False, strip_punctuation=False, reverse=False)` | — | Full input configuration for a run. |
| `Summary` | `@dataclass Summary(total=0, exact=0, fuzzy=0, missing=0, skipped=0, pass_rate=0.0)` | — | Aggregate counts and pass rate. |
| `Meta` | `@dataclass Meta(excel, pdf, timestamp, fuzzy_threshold, flags)` | — | Provenance/config echo for a run. |
| `Meta.now_iso` | `now_iso() -> str` (staticmethod) | `str` | Current UTC time as an ISO-8601 string. |
| `RunResult` | `@dataclass RunResult(meta, summary, columns=[], warnings=[])` | — | Complete self-describing run result. |

## Key variables / constants
| Name | Purpose |
| --- | --- |
| `DiffOp` | Type alias `tuple[str, str]` = `(op, text)` describing one diff operation (`equal`/`insert`/`delete`/`replace`). |
| `Status.EXACT` | Outcome: value found verbatim after normalization. |
| `Status.FUZZY` | Outcome: close match at/above the fuzzy threshold. |
| `Status.MISSING` | Outcome: no match reached the threshold. |
| `Status.SKIPPED` | Outcome: blank cell, nothing checked. |
| `RunConfig.fuzzy_threshold` | Default `90`; minimum score (0–100) for a FUZZY match. |
| `RunConfig.header_row` | Default `1`; 1-based row containing column headers. |
| `Summary.pass_rate` | `(exact + fuzzy) / checked` rounded to 4 dp; `checked` excludes skipped. |

## Notes / gotchas
- **Determinism:** All types are pure data with no AI/ML/network logic, consistent with ProofCheck's deterministic guarantee. The only non-deterministic element is `Meta.now_iso()`, which reads the wall clock — fine for a provenance timestamp, but not part of the matching logic.
- **`Status(str, Enum)`:** Because members subclass `str`, they serialize to JSON and compare against plain strings transparently, which is why the web JSON layer can emit them directly.
- **Mutable defaults:** Every list/dict field uses `field(default_factory=...)` to avoid the classic shared-mutable-default bug; never replace these with bare `[]`/`{}`.
- **1-based indexing:** `MatchResult.row`, `MatchResult.page`, and `RunConfig.header_row` are all 1-based (matching spreadsheet/PDF conventions), not 0-based.
- **`pass_rate` excludes skipped:** The denominator (`checked`) intentionally omits `SKIPPED` values; an all-blank run would not count toward the pass rate. The actual arithmetic is performed in `pipeline.py`, not here.
- **`replace` diff op is reserved:** The matcher decomposes replacements into `delete` + `insert`, so a `replace` op is documented but not currently emitted.
- **Presentation-free by design:** No HTML, colors, or formatting belong in these types; keep rendering concerns in the report writers.

## v0.2 changes

`RunConfig` gained `fold_diacritics: bool`, `ocr: bool`, `ocr_dpi: int = 300`, and `ocr_lang: str = 'eng'`. `Meta.flags` now also echoes `fold_diacritics` and `ocr` (still a `dict[str, bool]`; dpi/lang are config, not flags).


## v0.2 changes (OCR diagnostics + source column)

`MatchResult` gained `source` (`'text'` | `'OCR'` | None) — whether the matched page's text came from the embedded text layer or from OCR; set by `pipeline.run` from `pdf_text.ocr_pages` and shown as the reports' 'Matched via' column. `RunConfig` gained `ocr_psm` (Tesseract page-segmentation mode, default 3).

