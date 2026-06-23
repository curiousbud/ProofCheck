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

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .. import __version__, report_html, report_xlsx
from ..models import RunConfig, RunResult
from ..pipeline import PipelineError, run as pipeline_run
from . import schemas

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
)


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


# ---- Routes -----------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve the bundled disposable UI."""
    index_file = _STATIC_DIR / "index.html"
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.get("/api/health", response_model=schemas.HealthResponse)
async def health() -> schemas.HealthResponse:
    return schemas.HealthResponse(status="ok", version=__version__)


@app.post("/api/inspect", response_model=schemas.InspectResponse)
async def inspect(excel: UploadFile = File(...)) -> schemas.InspectResponse:  # noqa: A002
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
    reverse: str = Form("false"),
) -> JSONResponse:
    """Run a full check and return the documented JSON shape + report download URLs."""
    _cleanup_reports()
    _validate_ext(excel.filename, EXCEL_EXTS, "Excel file")
    _validate_ext(pdf.filename, PDF_EXTS, "PDF file")

    excel_path = await _save_upload(excel, suffix=".xlsx")
    pdf_path = None
    try:
        pdf_path = await _save_upload(pdf, suffix=".pdf")

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
            reverse=_parse_bool(reverse),
        )
        result = pipeline_run(config)

        run_id = uuid.uuid4().hex
        # Original filenames are kept only in meta; the cached files use the opaque run_id.
        result.meta.excel = excel.filename or result.meta.excel
        result.meta.pdf = pdf.filename or result.meta.pdf
        report_html.write(result, str(_REPORT_DIR / f"{run_id}.html"))
        report_xlsx.write(result, str(_REPORT_DIR / f"{run_id}.xlsx"))

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
