# `proofcheck/web/app.py` — Explained

> The FastAPI application: a thin, disposable HTTP adapter that turns uploads into a `RunConfig`, calls `pipeline.run()`, and serializes the `RunResult` to the documented JSON swap contract — with zero business logic.

## Purpose
`app.py` is the entire web layer's runtime. It exposes a small set of HTTP routes that accept Excel/PDF uploads, hand them to the deterministic `proofcheck.pipeline.run` function, and return results as JSON shaped by `schemas.py`. It deliberately contains no matching, normalization, or scoring logic — every route is an adapter. Because uploads are real PII (delegate names), it writes them to per-request tempfiles and deletes them immediately after the run.

## Dependencies
- **Imports (external):**
  - `os` — read environment variables (config) and low-level `os.fdopen`/`os.unlink` for tempfile streaming and deletion.
  - `tempfile` — create per-request upload tempfiles (`mkstemp`) and locate the report cache dir (`gettempdir`).
  - `time` — compute the TTL cutoff for the report cache cleanup.
  - `uuid` — mint opaque `run_id` hex tokens for cached report download links (no PII in the URL).
  - `pathlib.Path` — path manipulation for static dir, report dir, and file-extension parsing.
  - `fastapi` (`FastAPI`, `File`, `Form`, `HTTPException`, `Request`, `UploadFile`) — the web framework, multipart form/file binding, and structured HTTP errors.
  - `fastapi.middleware.cors.CORSMiddleware` — allow the bundled UI / other clients to call the API cross-origin.
  - `fastapi.responses` (`FileResponse`, `HTMLResponse`, `JSONResponse`) — serve the report downloads, the bundled HTML UI, and JSON (incl. error envelopes).
- **Imports (internal):**
  - `proofcheck.__version__` — surfaced in app metadata and `/api/health`.
  - `proofcheck.report_html`, `proofcheck.report_xlsx` — write the downloadable report artifacts.
  - `proofcheck.models` (`RunConfig`, `RunResult`) — the config dataclass built from the request and the result dataclass returned by the pipeline.
  - `proofcheck.pipeline` (`PipelineError`, `run as pipeline_run`) — the single business-logic entry point and its domain error type.
  - `proofcheck.web.schemas` — the pydantic swap contract used for serialization and response models.
  - `proofcheck.excel` — imported lazily inside `/api/inspect` to enumerate sheets/headers.
- **Used by:** `proofcheck` CLI `serve` command launches this `app` (via uvicorn); the bundled `static/index.html` is the disposable client that calls `/api/inspect`, `/api/check`, and the `/reports/...` links; tests exercise the routes directly.

## Line-by-line / block-by-block breakdown

### Module docstring & imports (lines 1–24)
```python
"""FastAPI application: routes + RunResult->JSON serialization only.

No matching/normalization logic lives here — every request is adapted into a
:class:`RunConfig`, handed to :func:`proofcheck.pipeline.run`, and the result is
serialized to the :mod:`schemas` contract. Uploads are real PII (delegate names) so
they are written to per-request tempfiles and deleted immediately after the run.
"""
```
States the design contract up front: this module is an adapter only, and uploads are PII that must be deleted promptly. The imports pull in stdlib utilities, FastAPI primitives, and the internal pipeline/report/schema modules.

### Configuration: env vars and constants (lines 26–45)
```python
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "25"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CORS_ORIGINS", "http://localhost,http://localhost:8000,http://127.0.0.1:8000"
    ).split(",")
    if o.strip()
]
REPORT_TTL_SECONDS = 60 * 60  # delete generated reports older than 1 hour
```
- **`MAX_UPLOAD_MB`** — upload size cap in megabytes (default `25`); `MAX_UPLOAD_BYTES` is the byte form enforced while streaming uploads. Exceeding it yields **413**.
- **`CORS_ORIGINS`** — comma-separated allowlist of origins (default localhost variants on port 8000), parsed into a clean list with blanks dropped.
- **`REPORT_TTL_SECONDS`** — `3600` (1 hour). Cached report files older than this are pruned opportunistically.

```python
EXCEL_EXTS = {".xlsx", ".xlsm"}
PDF_EXTS = {".pdf"}

_STATIC_DIR = Path(__file__).parent / "static"
_REPORT_DIR = Path(tempfile.gettempdir()) / "proofcheck_reports"
_REPORT_DIR.mkdir(parents=True, exist_ok=True)
```
- Allowed extensions for the two upload kinds (Excel accepts `.xlsx`/`.xlsm`; PDF only `.pdf`).
- `_STATIC_DIR` is the bundled UI directory (`index.html`).
- `_REPORT_DIR` is the short-lived report cache under the OS temp dir, created at import time. The inline NOTE flags that production should move this to object storage with lifecycle expiry.

### App + CORS middleware (lines 47–60)
```python
app = FastAPI(
    title="ProofCheck API",
    version=__version__,
    description="Deterministic Excel-vs-PDF proof-reading. No AI/LLM/ML. ...",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
Constructs the FastAPI app with title/version/description (the description explicitly markets the JSON contract as the stable, swappable boundary), then attaches CORS using the configured origin allowlist while permitting all methods and headers.

### Exception handlers (lines 63–71)
```python
@app.exception_handler(PipelineError)
async def _pipeline_error_handler(_: Request, exc: PipelineError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": str(exc)})


@app.exception_handler(Exception)
async def _unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": f"Unexpected error: {exc}"})
```
- Domain errors raised by the pipeline (`PipelineError`) become a clean **422** with a human-readable `{"error": ...}` envelope.
- Any other uncaught exception becomes a **500** with an `Unexpected error: ...` envelope.
- Both guarantee clients see the `ErrorResponse` JSON shape and **never** raw stack traces. (Note: `HTTPException` raised by routes is handled by FastAPI's built-in handler, producing the standard `{"detail": ...}` body with the chosen status code.)

### `_cleanup_reports()` (lines 75–83)
```python
def _cleanup_reports() -> None:
    cutoff = time.time() - REPORT_TTL_SECONDS
    for path in _REPORT_DIR.glob("*"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass
```
Opportunistic garbage collection of the report cache. Computes a cutoff (now − TTL) and unlinks any cached file whose mtime predates it. OS errors are swallowed so cleanup never breaks a request. Called at the top of `/api/check` and `/reports/...`.

### `_validate_ext()` (lines 86–93)
```python
def _validate_ext(filename: str, allowed: set[str], kind: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"{kind} must be one of {', '.join(sorted(allowed))} (got {ext or 'no extension'}).",
        )
    return ext
```
Validates an uploaded file's extension against an allowed set. On mismatch raises **400** with a descriptive message; otherwise returns the lowercased extension.

### `_save_upload()` (lines 96–113)
```python
async def _save_upload(upload: UploadFile, suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    total = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Limit is {MAX_UPLOAD_MB} MB.",
                    )
                out.write(chunk)
    except Exception:
        _safe_unlink(path)
        raise
    return path
```
Streams an upload to a fresh tempfile in 1 MB chunks, tracking cumulative size and raising **413** the moment it exceeds `MAX_UPLOAD_BYTES`. If anything fails (including the size cap), it deletes the partial tempfile before re-raising, so no PII leaks on error. Returns the tempfile path on success.

### `_safe_unlink()` (lines 116–121)
```python
def _safe_unlink(path: str | None) -> None:
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass
```
Best-effort tempfile deletion: no-op on `None`, swallows `OSError` (e.g. already gone). This is the workhorse of the PII-deletion guarantee, called in `finally` blocks.

### `_serialize()` (lines 124–166)
```python
def _serialize(result: RunResult, run_id: str) -> dict:
    payload = schemas.CheckResponse(
        meta=schemas.MetaModel(...),
        summary=schemas.SummaryModel(...),
        columns=[schemas.ColumnResultModel(...) for col in result.columns],
        warnings=result.warnings,
        report_urls=schemas.ReportUrls(
            html=f"/reports/{run_id}.html",
            xlsx=f"/reports/{run_id}.xlsx",
        ),
    )
    return payload.model_dump()
```
The mapping from the internal `RunResult` dataclass onto the pydantic swap contract — the only place the two shapes meet. It copies `meta`, `summary`, every column and its per-row `MatchResultModel` (converting `r.status` enum to `.value`, and `diff` into a list of `(op, text)` tuples), the `warnings` list, and builds the `report_urls` from the opaque `run_id`. Returns a plain dict via `model_dump()`. Adds nothing semantic.

### `_parse_bool()` (lines 169–170)
```python
def _parse_bool(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"} if value is not None else False
```
Converts a form string into a bool. `None` → `False`; otherwise truthy for `1/true/yes/on` (case-insensitive, trimmed). Used to coerce the boolean form fields in `/api/check`.

### Route: `GET /` (lines 174–178)
```python
@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    index_file = _STATIC_DIR / "index.html"
    return HTMLResponse(index_file.read_text(encoding="utf-8"))
```
Serves the bundled disposable UI by reading `static/index.html` and returning it as HTML. No business logic. (Status **200**; a missing file would surface as a **500** via the generic handler.)

### Route: `GET /api/health` (lines 181–183)
```python
@app.get("/api/health", response_model=schemas.HealthResponse)
async def health() -> schemas.HealthResponse:
    return schemas.HealthResponse(status="ok", version=__version__)
```
Liveness/version probe. Returns `{"status": "ok", "version": <__version__>}` (**200**).

### Route: `POST /api/inspect` (lines 186–198)
```python
@app.post("/api/inspect", response_model=schemas.InspectResponse)
async def inspect(excel: UploadFile = File(...)) -> schemas.InspectResponse:
    _validate_ext(excel.filename, EXCEL_EXTS, "Excel file")
    path = await _save_upload(excel, suffix=".xlsx")
    try:
        from .. import excel as excel_mod
        headers = excel_mod.inspect(path)
        return schemas.InspectResponse(sheets=list(headers.keys()), headers=headers)
    except Exception as exc:  # ExcelError and friends -> clean 400
        raise HTTPException(status_code=400, detail=f"Could not inspect Excel file: {exc}")
    finally:
        _safe_unlink(path)  # PII: delete immediately
```
Accepts only an Excel upload, validates its extension (**400** on bad ext / oversize via `_save_upload` → **413**), saves it to a tempfile, then lazily imports `proofcheck.excel` and calls `inspect(path)` to enumerate sheets and per-sheet headers. Returns an `InspectResponse` (sheets list + headers map) so the UI can build a column picker. Any inspection failure is converted to a clean **400**. The `finally` block deletes the tempfile immediately — the PII deletion guarantee.

### Route: `POST /api/check` (lines 201–251)
```python
@app.post("/api/check")
async def check(
    excel: UploadFile = File(...),
    pdf: UploadFile = File(...),
    columns: str = Form(""),
    all_columns: str = Form("false"),
    sheet: str = Form(""),
    header_row: int = Form(1),
    fuzzy_threshold: int = Form(90),
    normalize_digits: str = Form("false"),
    strip_punctuation: str = Form("false"),
    reverse: str = Form("false"),
) -> JSONResponse:
    _cleanup_reports()
    _validate_ext(excel.filename, EXCEL_EXTS, "Excel file")
    _validate_ext(pdf.filename, PDF_EXTS, "PDF file")

    excel_path = await _save_upload(excel, suffix=".xlsx")
    pdf_path = None
    try:
        pdf_path = await _save_upload(pdf, suffix=".pdf")

        col_list = [c.strip() for c in columns.replace("\n", ",").split(",") if c.strip()]
        config = RunConfig(...)
        result = pipeline_run(config)

        run_id = uuid.uuid4().hex
        result.meta.excel = excel.filename or result.meta.excel
        result.meta.pdf = pdf.filename or result.meta.pdf
        report_html.write(result, str(_REPORT_DIR / f"{run_id}.html"))
        report_xlsx.write(result, str(_REPORT_DIR / f"{run_id}.xlsx"))

        return JSONResponse(content=_serialize(result, run_id))
    finally:
        _safe_unlink(excel_path)
        _safe_unlink(pdf_path)
```
The core endpoint. It accepts both files plus a flat set of multipart form fields (FastAPI auto-coerces `header_row`/`fuzzy_threshold` to int — a non-int yields **422** from validation; booleans arrive as strings and are parsed with `_parse_bool`).

Flow:
1. `_cleanup_reports()` prunes stale cached reports.
2. Validate both extensions (**400** on bad ext).
3. Stream both uploads to tempfiles (**413** if either exceeds the size cap).
4. Parse the `columns` field (comma- or newline-separated) into a clean list.
5. Build a `RunConfig` and call `pipeline_run(config)` — the only business-logic call. A `PipelineError` here propagates to the **422** handler; an unexpected error to the **500** handler.
6. Mint an opaque `run_id` (uuid hex). Stamp the original filenames back into `result.meta` (kept only in meta; the cached files are named by the opaque `run_id`, so URLs carry no PII).
7. Write the HTML and XLSX reports into the cache keyed by `run_id`.
8. Serialize and return the JSON contract (**200**).
9. `finally`: delete both uploaded tempfiles whether the run succeeded or failed — the PII deletion guarantee.

### Route: `GET /reports/{run_id}.{ext}` (lines 254–266)
```python
@app.get("/reports/{run_id}.{ext}")
async def download_report(run_id: str, ext: str) -> FileResponse:
    _cleanup_reports()
    if ext not in {"html", "xlsx"} or not run_id.isalnum():
        raise HTTPException(status_code=404, detail="Report not found.")
    path = _REPORT_DIR / f"{run_id}.{ext}"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report expired or not found.")
    media = "text/html" if ext == "html" else (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return FileResponse(path, media_type=media, filename=f"proofcheck-{run_id}.{ext}")
```
Serves a previously generated report. It first prunes stale files, then validates inputs: `ext` must be `html` or `xlsx`, and `run_id` must be `.isalnum()` — this rejects any path-traversal attempt (dots, slashes, `..`) and yields **404** on a bad token. If the file is missing or has expired past the TTL, returns **404** ("Report expired or not found."). On success returns a `FileResponse` with the correct MIME type and a friendly `proofcheck-<run_id>.<ext>` download filename (**200**).

## Endpoints (app.py only)

| Method | Path | Request | Response | Error codes |
|--------|------|---------|----------|-------------|
| GET | `/` | none | `text/html` (bundled UI) | 500 (file read failure) |
| GET | `/api/health` | none | `HealthResponse` JSON | — |
| POST | `/api/inspect` | multipart: `excel` file | `InspectResponse` JSON (sheets + headers) | 400 (bad ext / inspect failure), 413 (too large), 422/500 |
| POST | `/api/check` | multipart: `excel`, `pdf` files + form fields (`columns`, `all_columns`, `sheet`, `header_row`, `fuzzy_threshold`, `normalize_digits`, `strip_punctuation`, `reverse`) | `CheckResponse` JSON (full result + report URLs) | 400 (bad ext), 413 (too large), 422 (PipelineError / form-validation), 500 (unexpected) |
| GET | `/reports/{run_id}.{ext}` | path params `run_id` (alnum), `ext` (`html`\|`xlsx`) | `FileResponse` (report download) | 404 (bad token/ext, missing, or expired) |

## Models (schemas.py only)
Not applicable to this file — see `web_schemas_EXPLAINED.md`.

## Functions / Methods / Classes

| Name | Signature | Returns | Description |
|------|-----------|---------|-------------|
| `_pipeline_error_handler` | `(_: Request, exc: PipelineError)` | `JSONResponse` | Maps domain `PipelineError` to a 422 `{"error": ...}` envelope. |
| `_unexpected_error_handler` | `(_: Request, exc: Exception)` | `JSONResponse` | Maps any uncaught exception to a 500 `{"error": ...}` envelope; never leaks tracebacks. |
| `_cleanup_reports` | `()` | `None` | Opportunistically deletes cached report files older than `REPORT_TTL_SECONDS`. |
| `_validate_ext` | `(filename: str, allowed: set[str], kind: str)` | `str` | Validates/normalizes an upload extension; raises 400 on mismatch. |
| `_save_upload` | `async (upload: UploadFile, suffix: str)` | `str` | Streams an upload to a tempfile with a size cap (413); cleans up on failure; returns its path. |
| `_safe_unlink` | `(path: str \| None)` | `None` | Best-effort tempfile deletion (PII); swallows errors. |
| `_serialize` | `(result: RunResult, run_id: str)` | `dict` | Maps an internal `RunResult` onto the `CheckResponse` swap contract and returns a dict. |
| `_parse_bool` | `(value: str \| None)` | `bool` | Coerces a form string to bool (`1/true/yes/on` truthy). |
| `index` | `async ()` | `HTMLResponse` | Serves the bundled `static/index.html`. |
| `health` | `async ()` | `HealthResponse` | Returns status + version. |
| `inspect` | `async (excel: UploadFile)` | `InspectResponse` | Returns sheets + headers for the column picker; deletes the upload. |
| `check` | `async (excel, pdf, + form fields)` | `JSONResponse` | Runs the full check via the pipeline, writes reports, returns JSON; deletes uploads. |
| `download_report` | `async (run_id: str, ext: str)` | `FileResponse` | Serves a cached report; validates `run_id`/`ext`; 404 if missing/expired. |

## Notes / gotchas
- **Zero business logic boundary:** the only logic this module owns is HTTP adaptation, file streaming, validation, and serialization. All matching/normalization/scoring lives behind `pipeline.run()`.
- **Swap contract:** responses are shaped by `schemas.py`, which is THE stable, versionable API. Any frontend speaking it can replace the bundled HTML UI.
- **PII tempfile deletion:** uploads are written to per-request tempfiles and unlinked in `finally` blocks (`/api/inspect` and `/api/check`) regardless of success or failure; partial uploads are also cleaned up inside `_save_upload`. Original filenames live only in `meta`, never in URLs.
- **CORS:** origins are env-configurable via `CORS_ORIGINS` (default localhost:8000 variants); all methods/headers allowed.
- **JSON error envelope (never tracebacks):** `PipelineError` → 422 and any other exception → 500, both as `{"error": <message>}`. Route-level `HTTPException` produces FastAPI's standard `{"detail": ...}` body.
- **Report cache TTL:** generated reports live in a temp dir for `REPORT_TTL_SECONDS` (1 hour) and are pruned opportunistically on `/api/check` and `/reports/...` requests; the cache is not durable (production should use object storage).
- **`run_id` validation (isalnum):** download `run_id` must be alphanumeric and `ext` must be `html`/`xlsx`, blocking path traversal; failures return 404, not 400.
- **Upload size cap:** enforced while streaming (`MAX_UPLOAD_MB`, default 25), raising 413 mid-stream rather than buffering the whole file.

IMPORT_EDGES: web/app.py -> __init__.py (proofcheck package, __version__), report_html.py, report_xlsx.py, models.py, pipeline.py, excel.py, web/schemas.py

## v0.2 changes

v0.2: mounts `/static` (StaticFiles) for the SPA assets; `/` still serves index.html. `/api/health` now reports `auth_enabled` + `ocr_available`. `/api/inspect` and `/api/check` depend on `auth.current_user` (anonymous when auth off, 401 when on). `/api/check` accepts `fold_diacritics`/`ocr`/`ocr_lang`/`ocr_dpi` form fields and records non-PII history via `store.add_run`. New routes: `/api/auth/{login,logout,me,register}` and `/api/history` (+ `/{run_id}` GET/DELETE). `store.init_db()` + `auth.bootstrap_admin()` run at import. See web_auth_EXPLAINED.md / web_store_EXPLAINED.md.


## v0.2 changes (OCR diagnostics + source column)

`/api/check` accepts an `ocr_psm` form field; the serialized match results now include `source` (text/OCR).

