# `proofcheck/web/schemas.py` — Explained

> The pydantic models that define ProofCheck's stable JSON API — **THE SWAP CONTRACT** every frontend speaks.

## Purpose
`schemas.py` declares the pydantic models that make up the public JSON contract of the ProofCheck web API. These shapes mirror the internal `proofcheck.models` dataclasses exactly and add nothing semantic; the web layer simply maps the internal `RunResult` onto them. Because this is the stable, swappable boundary between server and any client (the bundled HTML page, a future SPA, a CI integration), changes here are API changes and must stay backward compatible or be versioned.

## Dependencies
- **Imports (external):**
  - `pydantic` (`BaseModel`, `Field`) — defines the typed, validated, serializable models; `Field` supplies defaults (`default_factory`) and human-facing descriptions.
- **Imports (internal):** None. (The module is intentionally standalone so the contract has no coupling to internal logic; `from __future__ import annotations` is used for deferred annotation evaluation.)
- **Used by:** `proofcheck/web/app.py` — builds these models in `_serialize` and uses them as FastAPI `response_model`s (`HealthResponse`, `InspectResponse`, `CheckResponse`); FastAPI also derives the OpenAPI schema from them; clients (bundled `static/index.html`, tests, future frontends) consume the resulting JSON.

## Line-by-line / block-by-block breakdown

### Module docstring & imports (lines 1–14)
```python
"""Pydantic models — **THE SWAP CONTRACT**. ..."""
from __future__ import annotations
from pydantic import BaseModel, Field
```
The docstring is the governing policy: these models are the stable JSON API, the HTML page is just one disposable client, and changes must remain backward compatible or be versioned. It also notes the shapes mirror `proofcheck.models` exactly.

### `HealthResponse` (lines 17–19)
```python
class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
```
Returned by `GET /api/health`. `status` defaults to `"ok"`; `version` is the package version. Confirms liveness and surfaces the running build.

### `InspectResponse` (lines 22–26)
```python
class InspectResponse(BaseModel):
    """Sheets + per-sheet headers, used to populate the UI column picker."""
    sheets: list[str]
    headers: dict[str, list[str]]
```
Returned by `POST /api/inspect`. `sheets` is the ordered list of sheet names; `headers` maps each sheet name to its list of column headers. Lets a client build a column picker without parsing the workbook itself.

### `DiffPair` (lines 29–37)
```python
class DiffPair(BaseModel):
    """One [op, text] diff fragment. op in {equal, insert, delete, replace}. ..."""
    op: str
    text: str
```
A single diff fragment: an operation (`equal`/`insert`/`delete`/`replace`) and its text. The docstring documents that diffs are emitted as 2-element arrays so the frontend renders highlighting itself — the server never bakes in `<del>`/`<ins>` HTML. (Note: in practice `MatchResultModel.diff` is serialized as a list of `(op, text)` tuples rather than as `DiffPair` objects; `DiffPair` documents/typifies the fragment shape.)

### `MatchResultModel` (lines 40–48)
```python
class MatchResultModel(BaseModel):
    row: int
    expected: str
    status: str = Field(description="EXACT | FUZZY | MISSING | SKIPPED")
    page: int | None = None
    best_match: str | None = None
    score: int = 0
    diff: list[tuple[str, str]] = Field(default_factory=list)
```
One row's check result. `row` is the source row number; `expected` is the value from Excel; `status` is the outcome string (one of `EXACT`/`FUZZY`/`MISSING`/`SKIPPED`, serialized from the internal enum's `.value`). `page` is the PDF page where a match was found (nullable), `best_match` the matched PDF text (nullable), `score` the fuzzy match score (0–100, default 0), and `diff` the list of `[op, text]` fragments (defaults to empty).

### `ColumnResultModel` (lines 51–53)
```python
class ColumnResultModel(BaseModel):
    name: str
    results: list[MatchResultModel] = Field(default_factory=list)
```
Per-column container: the column `name` and its list of per-row `MatchResultModel`s (defaults to empty).

### `MetaModel` (lines 56–61)
```python
class MetaModel(BaseModel):
    excel: str
    pdf: str
    timestamp: str
    fuzzy_threshold: int
    flags: dict[str, bool]
```
Run metadata: original `excel` and `pdf` filenames, the run `timestamp`, the `fuzzy_threshold` used, and a `flags` map of boolean options (e.g. normalize_digits / strip_punctuation / reverse) that were active.

### `SummaryModel` (lines 64–70)
```python
class SummaryModel(BaseModel):
    total: int
    exact: int
    fuzzy: int
    missing: int
    skipped: int
    pass_rate: float
```
Aggregate counts across all checked rows — `total` plus the breakdown by status (`exact`, `fuzzy`, `missing`, `skipped`) — and a computed `pass_rate` float.

### `ReportUrls` (lines 73–75)
```python
class ReportUrls(BaseModel):
    html: str
    xlsx: str
```
Download links for the generated reports, populated as `/reports/{run_id}.html` and `/reports/{run_id}.xlsx`.

### `CheckResponse` (lines 78–85)
```python
class CheckResponse(BaseModel):
    """Full result of POST /api/check — a direct serialization of RunResult."""
    meta: MetaModel
    summary: SummaryModel
    columns: list[ColumnResultModel]
    warnings: list[str] = Field(default_factory=list)
    report_urls: ReportUrls
```
The top-level payload for `POST /api/check`: `meta`, `summary`, the list of per-column results, any `warnings` (default empty), and the report download `report_urls`. This is the full, direct serialization of the internal `RunResult`.

### `ErrorResponse` (lines 88–91)
```python
class ErrorResponse(BaseModel):
    """Human-readable error envelope (never raw tracebacks)."""
    error: str
```
The documented error shape: a single human-readable `error` string. Matches the bodies emitted by `app.py`'s exception handlers (422 / 500), guaranteeing clients never receive raw tracebacks.

## Endpoints (app.py only)
Not applicable to this file — see `web_app_EXPLAINED.md`.

## Models (schemas.py only)

| Model | Fields | Purpose |
|-------|--------|---------|
| `HealthResponse` | `status: str = "ok"`, `version: str` | Liveness/version probe response for `GET /api/health`. |
| `InspectResponse` | `sheets: list[str]`, `headers: dict[str, list[str]]` | Sheet names + per-sheet headers for the UI column picker (`POST /api/inspect`). |
| `DiffPair` | `op: str`, `text: str` | One `[op, text]` diff fragment (`equal`/`insert`/`delete`/`replace`); client renders highlighting. |
| `MatchResultModel` | `row: int`, `expected: str`, `status: str`, `page: int\|None`, `best_match: str\|None`, `score: int = 0`, `diff: list[tuple[str, str]]` | A single row's match outcome. |
| `ColumnResultModel` | `name: str`, `results: list[MatchResultModel]` | Per-column grouping of row results. |
| `MetaModel` | `excel: str`, `pdf: str`, `timestamp: str`, `fuzzy_threshold: int`, `flags: dict[str, bool]` | Run metadata (filenames, timestamp, threshold, option flags). |
| `SummaryModel` | `total: int`, `exact: int`, `fuzzy: int`, `missing: int`, `skipped: int`, `pass_rate: float` | Aggregate counts and pass rate. |
| `ReportUrls` | `html: str`, `xlsx: str` | Download URLs for the generated reports. |
| `CheckResponse` | `meta: MetaModel`, `summary: SummaryModel`, `columns: list[ColumnResultModel]`, `warnings: list[str]`, `report_urls: ReportUrls` | Full `POST /api/check` payload (serialized `RunResult`). |
| `ErrorResponse` | `error: str` | Human-readable error envelope (never tracebacks). |

## Functions / Methods / Classes
This module declares only pydantic `BaseModel` subclasses (no standalone functions/methods); see the Models table above.

## Notes / gotchas
- **Swap contract:** this module IS the stable API. Treat any change as an API change — keep it backward compatible or version it. The bundled HTML UI is just one disposable client.
- **Mirrors `proofcheck.models`:** every field corresponds to the internal dataclasses; the web layer maps internal → schema in `app._serialize` and adds no new semantics.
- **No internal imports:** the contract is intentionally decoupled from internal logic (only `pydantic` is imported), so it can be lifted out or reimplemented for a different transport.
- **Diff as `[op, text]` arrays:** highlighting is left to the client; the server never emits HTML markup for diffs. `DiffPair` documents the fragment shape, while `MatchResultModel.diff` is serialized as tuples.
- **Status as string:** `MatchResultModel.status` is the enum `.value` (`EXACT`/`FUZZY`/`MISSING`/`SKIPPED`), not a numeric code.
- **Defaults / nullability:** `page` and `best_match` are nullable; `score` defaults to 0; `diff` and `warnings` default to empty lists — clients should tolerate omitted/empty values.
- **JSON error envelope:** `ErrorResponse` documents the `{"error": ...}` shape used by the 422/500 handlers in `app.py`; clients never see raw tracebacks.

IMPORT_EDGES: web/schemas.py -> (none)

## v0.2 changes

`HealthResponse` gained `auth_enabled` + `ocr_available`. New models: `Credentials`, `AuthUser` (auth) and `HistoryItem` (run_id, created_at, excel, pdf, summary, meta) + `HistoryList` (run history). These remain a pure serialization of internal state -- still the SWAP CONTRACT.


## v0.2 changes (OCR diagnostics + source column)

`MatchResultModel` gained `source` (`'text'` | `'OCR'` | null).

