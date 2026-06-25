"""FastAPI application: routes + RunResult->JSON serialization only.

No matching/normalization logic lives here — every request is adapted into a
:class:`RunConfig`, handed to :func:`proofcheck.pipeline.run`, and the result is
serialized to the :mod:`schemas` contract. Uploads are real PII (delegate names) so
they are written to per-request tempfiles and deleted immediately after the run.
"""

from __future__ import annotations

import os
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__, ocr, report_html, report_xlsx
from ..models import RunConfig, RunResult
from ..pipeline import PipelineError, run as pipeline_run
from . import auth, schemas, store

# ---- Configuration (env-driven, MVP-appropriate defaults) -------------------
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

EXCEL_EXTS = {".xlsx", ".xlsm"}
PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}
DOC_EXTS = PDF_EXTS | IMAGE_EXTS  # /api/check accepts a PDF or a single image

_STATIC_DIR = Path(__file__).parent / "static"
# Short-lived cache for generated report files, keyed by run_id (download links).
# NOTE: production should move this to object storage with lifecycle expiry.
_REPORT_DIR = Path(tempfile.gettempdir()) / "proofcheck_reports"
_REPORT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="ProofCheck API",
    version=__version__,
    description="Deterministic Excel-vs-PDF proof-reading. No AI/LLM/ML. "
    "The JSON contract here is the stable, swappable boundary; the bundled HTML "
    "UI is just one disposable client.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,  # session cookie is sent on same-origin /api/* calls
)

# Initialise persistence eagerly so the schema exists regardless of how the app is
# started (uvicorn, TestClient, embedded). Both calls are cheap and idempotent, and run
# at import time so they apply even when the ASGI lifespan isn't triggered (bare
# TestClient). Reload workers re-import the module, so this also covers --reload.
store.init_db()
auth.bootstrap_admin()

# Serve the SPA's static assets (app.css / app.js). "/" still returns index.html below.
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ---- Error handling: human-readable JSON, never raw tracebacks --------------
@app.exception_handler(PipelineError)
async def _pipeline_error_handler(_: Request, exc: PipelineError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": str(exc)})


@app.exception_handler(Exception)
async def _unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": f"Unexpected error: {exc}"})


# ---- Helpers ----------------------------------------------------------------
def _cleanup_reports() -> None:
    """Delete report files older than the TTL. Called opportunistically per request."""
    cutoff = time.time() - REPORT_TTL_SECONDS
    for path in _REPORT_DIR.glob("*"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def _validate_ext(filename: str, allowed: set[str], kind: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"{kind} must be one of {', '.join(sorted(allowed))} (got {ext or 'no extension'}).",
        )
    return ext


async def _save_upload(upload: UploadFile, suffix: str) -> str:
    """Stream an upload to a tempfile, enforcing the size cap; return its path."""
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


def _safe_unlink(path: str | None) -> None:
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass


def _serialize(result: RunResult, run_id: str) -> dict:
    """Map an internal RunResult onto the JSON swap contract."""
    payload = schemas.CheckResponse(
        meta=schemas.MetaModel(
            excel=result.meta.excel,
            pdf=result.meta.pdf,
            timestamp=result.meta.timestamp,
            fuzzy_threshold=result.meta.fuzzy_threshold,
            flags=result.meta.flags,
        ),
        summary=schemas.SummaryModel(
            total=result.summary.total,
            exact=result.summary.exact,
            fuzzy=result.summary.fuzzy,
            missing=result.summary.missing,
            skipped=result.summary.skipped,
            pass_rate=result.summary.pass_rate,
        ),
        columns=[
            schemas.ColumnResultModel(
                name=col.name,
                results=[
                    schemas.MatchResultModel(
                        row=r.row,
                        expected=r.expected,
                        status=r.status.value,
                        page=r.page,
                        best_match=r.best_match,
                        score=r.score,
                        diff=[(op, text) for op, text in r.diff],
                        source=r.source,
                    )
                    for r in col.results
                ],
            )
            for col in result.columns
        ],
        warnings=result.warnings,
        report_urls=schemas.ReportUrls(
            html=f"/reports/{run_id}.html",
            xlsx=f"/reports/{run_id}.xlsx",
        ),
    )
    return payload.model_dump()


def _parse_bool(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"} if value is not None else False


def _summary_dict(result: RunResult) -> dict:
    s = result.summary
    return {
        "total": s.total, "exact": s.exact, "fuzzy": s.fuzzy,
        "missing": s.missing, "skipped": s.skipped, "pass_rate": s.pass_rate,
    }


def _meta_dict(result: RunResult) -> dict:
    m = result.meta
    return {
        "excel": m.excel, "pdf": m.pdf, "timestamp": m.timestamp,
        "fuzzy_threshold": m.fuzzy_threshold, "flags": m.flags,
    }


def _record_history(run_id: str, user: str, result: RunResult) -> None:
    """Store non-PII run metadata. Never lets a storage hiccup fail the actual check."""
    try:
        store.add_run(
            run_id=run_id,
            username=user,
            created_at=result.meta.timestamp,
            excel=result.meta.excel,
            pdf=result.meta.pdf,
            summary=_summary_dict(result),
            meta=_meta_dict(result),
        )
    except Exception:  # pragma: no cover - history is best-effort, never blocks a run
        pass


def _history_item(record: store.RunRecord) -> schemas.HistoryItem:
    return schemas.HistoryItem(
        run_id=record.run_id,
        created_at=record.created_at,
        excel=record.excel,
        pdf=record.pdf,
        summary=schemas.SummaryModel(**record.summary),
        meta=schemas.MetaModel(**record.meta),
    )


# ---- Routes -----------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve the bundled disposable UI."""
    index_file = _STATIC_DIR / "index.html"
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.get("/api/health", response_model=schemas.HealthResponse)
async def health() -> schemas.HealthResponse:
    return schemas.HealthResponse(
        status="ok",
        version=__version__,
        auth_enabled=auth.auth_enabled(),
        ocr_available=ocr.available(),
    )


@app.post("/api/inspect", response_model=schemas.InspectResponse)
async def inspect(
    excel: UploadFile = File(...),  # noqa: A002
    user: str = Depends(auth.current_user),
) -> schemas.InspectResponse:
    """Return sheets + headers so the UI can build a column picker."""
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


@app.post("/api/check")
async def check(
    excel: UploadFile = File(...),  # noqa: A002
    pdf: UploadFile = File(...),
    columns: str = Form(""),
    all_columns: str = Form("false"),
    sheet: str = Form(""),
    header_row: int = Form(1),
    fuzzy_threshold: int = Form(90),
    normalize_digits: str = Form("false"),
    strip_punctuation: str = Form("false"),
    fold_diacritics: str = Form("false"),
    reverse: str = Form("false"),
    ocr: str = Form("false"),  # noqa: A002 - shadows the ocr module locally; resolved below
    ocr_lang: str = Form("eng"),
    ocr_dpi: int = Form(300),
    ocr_psm: int = Form(3),
    user: str = Depends(auth.current_user),
) -> JSONResponse:
    """Run a full check and return the documented JSON shape + report download URLs."""
    _cleanup_reports()
    _validate_ext(excel.filename, EXCEL_EXTS, "Excel file")
    pdf_ext = _validate_ext(pdf.filename, DOC_EXTS, "PDF or image file")

    excel_path = await _save_upload(excel, suffix=".xlsx")
    pdf_path = None
    try:
        # Save with the real extension so the pipeline routes PDFs vs images correctly.
        pdf_path = await _save_upload(pdf, suffix=pdf_ext)

        # Columns arrive as a comma- (or newline-) separated form field.
        col_list = [c.strip() for c in columns.replace("\n", ",").split(",") if c.strip()]
        config = RunConfig(
            excel_path=excel_path,
            pdf_path=pdf_path,
            columns=col_list,
            all_columns=_parse_bool(all_columns),
            sheet=sheet or None,
            header_row=header_row,
            fuzzy_threshold=fuzzy_threshold,
            normalize_digits=_parse_bool(normalize_digits),
            strip_punctuation=_parse_bool(strip_punctuation),
            fold_diacritics=_parse_bool(fold_diacritics),
            reverse=_parse_bool(reverse),
            ocr=_parse_bool(ocr),
            ocr_lang=ocr_lang or "eng",
            ocr_dpi=ocr_dpi,
            ocr_psm=ocr_psm,
        )
        result = pipeline_run(config)

        run_id = uuid.uuid4().hex
        # Original filenames are kept only in meta; the cached files use the opaque run_id.
        result.meta.excel = excel.filename or result.meta.excel
        result.meta.pdf = pdf.filename or result.meta.pdf
        report_html.write(result, str(_REPORT_DIR / f"{run_id}.html"))
        report_xlsx.write(result, str(_REPORT_DIR / f"{run_id}.xlsx"))

        # Persist non-PII run metadata so it survives the short-lived report cache.
        _record_history(run_id, user, result)

        return JSONResponse(content=_serialize(result, run_id))
    finally:
        # PII: delete uploads immediately, whether the run succeeded or failed.
        _safe_unlink(excel_path)
        _safe_unlink(pdf_path)


@app.get("/reports/{run_id}.{ext}")
async def download_report(run_id: str, ext: str) -> FileResponse:
    """Download a generated report. run_id is validated to be a bare hex token."""
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


# ---- Auth routes (optional; no-ops semantically when auth is disabled) -------
def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=auth.SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=auth._session_seconds(),
        path="/",
    )


@app.post("/api/auth/login", response_model=schemas.AuthUser)
async def login(credentials: schemas.Credentials, response: Response) -> schemas.AuthUser:
    """Validate credentials and set an HttpOnly session cookie."""
    if not auth.auth_enabled():
        # Auth is off: there is nothing to log into; report the single-user identity.
        return schemas.AuthUser(username=auth.ANONYMOUS, authenticated=False)
    if not auth.authenticate(credentials.username, credentials.password):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    _set_session_cookie(response, auth.make_token(credentials.username))
    return schemas.AuthUser(username=credentials.username, authenticated=True)


@app.post("/api/auth/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"status": "ok"}


@app.get("/api/auth/me", response_model=schemas.AuthUser)
async def me(user: str = Depends(auth.current_user)) -> schemas.AuthUser:
    """Return the current user (the dependency enforces 401 when auth is on)."""
    return schemas.AuthUser(username=user, authenticated=auth.auth_enabled())


@app.post("/api/auth/register", response_model=schemas.AuthUser, status_code=201)
async def register(credentials: schemas.Credentials, response: Response) -> schemas.AuthUser:
    """Self-service registration. Disabled unless PROOFCHECK_ALLOW_REGISTER is on."""
    if not auth.auth_enabled() or not auth.registration_enabled():
        raise HTTPException(status_code=403, detail="Registration is disabled.")
    try:
        auth.register_user(credentials.username, credentials.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _set_session_cookie(response, auth.make_token(credentials.username))
    return schemas.AuthUser(username=credentials.username, authenticated=True)


# ---- Run history routes (persisted metadata; PII inputs are never stored) ----
@app.get("/api/history", response_model=schemas.HistoryList)
async def history(user: str = Depends(auth.current_user)) -> schemas.HistoryList:
    return schemas.HistoryList(runs=[_history_item(r) for r in store.list_runs(user)])


@app.get("/api/history/{run_id}", response_model=schemas.HistoryItem)
async def history_item(run_id: str, user: str = Depends(auth.current_user)) -> schemas.HistoryItem:
    if not run_id.isalnum():
        raise HTTPException(status_code=404, detail="Run not found.")
    record = store.get_run(run_id, user)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return _history_item(record)


@app.delete("/api/history/{run_id}")
async def delete_history_item(run_id: str, user: str = Depends(auth.current_user)) -> dict:
    if not run_id.isalnum() or not store.delete_run(run_id, user):
        raise HTTPException(status_code=404, detail="Run not found.")
    # Best-effort: also drop any cached report files for this run.
    for ext in ("html", "xlsx"):
        try:
            (_REPORT_DIR / f"{run_id}.{ext}").unlink()
        except OSError:
            pass
    return {"status": "deleted", "run_id": run_id}
