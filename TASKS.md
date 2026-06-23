# ProofCheck — Task Checklist

ProofCheck is a **100% deterministic** tool (NO AI / LLM / ML, offline, no CDNs) that
verifies values from an Excel spreadsheet (delegate names, codes, cities, …) actually
appear in a PDF document. It supports fuzzy matching, normalization, and produces
HTML / xlsx reports plus a swappable web UI.

## Core engine
- [x] `models.py` — `RunConfig`, `RunResult`, `ColumnResult`, `MatchResult`, `Status` (the stable data contract)
- [x] `normalize.py` — deterministic normalization (casefold, whitespace, optional digit-fold + punctuation strip)
- [x] `excel.py` — load workbook, inspect sheets/headers, read column values per row
- [x] `pdf.py` — per-page text extraction, detect pages with no text layer (warnings)
- [x] `matcher.py` — exact / fuzzy / missing / skipped matching + `[op,text]` diff (difflib)
- [x] `pipeline.py` — **shared orchestration** `run(RunConfig) -> RunResult` (CLI + web call this, no duplication)

## Reports
- [x] `report_html.py` — standalone HTML report from `RunResult` (status colors, diff highlighting)
- [x] `report_xlsx.py` — xlsx report from `RunResult` (summary + per-column sheets, color-coded)

## CLI (thin wrapper)
- [x] `cli.py` — `check` (parse args -> `RunConfig` -> `pipeline.run()` -> report writers)
- [x] `cli.py` — `inspect` (list sheets/headers)
- [x] `cli.py` — `serve` subcommand (launches uvicorn on `web.app:app`)

## Web frontend (intentionally disposable)
- [x] `web/schemas.py` — pydantic models = **THE SWAP CONTRACT** (documented)
- [x] `web/app.py` — FastAPI routes + `RunResult` -> JSON serialization only (zero business logic)
- [x] `GET /` serves `static/index.html`; `GET /api/health`
- [x] `POST /api/inspect` — sheets + headers for the column picker
- [x] `POST /api/check` — documented JSON response shape + `report_urls`
- [x] `GET /reports/{run_id}.{html|xlsx}` — download generated reports
- [x] `web/static/index.html` — minimal vanilla UI (file inputs, picker, slider, results, filter/search)

## Ops / production touches (MVP-appropriate)
- [x] Validate file extensions (.xlsx/.xlsm, .pdf) -> 400
- [x] `MAX_UPLOAD_MB` env (default 25) -> 413 over limit
- [x] Uploads written to per-request tempfiles, **deleted immediately** after run (PII)
- [x] Reports in short-lived cache dir keyed by `run_id`, TTL cleanup (>1h) on each request
- [x] CORS middleware, allowed origins via `CORS_ORIGINS` env (default localhost)
- [x] Human-readable JSON errors (no raw tracebacks)

## Packaging & tests
- [x] `pyproject.toml` — pinned deps, `proofcheck` console script
- [x] `tests/conftest.py` — generates Excel + PDF fixtures (deterministic)
- [x] `test_normalize.py`, `test_matcher.py`, `test_pipeline.py`
- [x] `test_api.py` — TestClient: inspect shape, check shape + status counts, 400 bad ext, 413 oversize
- [x] `README.md` — usage, API contract, swap instructions, ops/roadmap notes

## Future suggestions / roadmap (v2)
- [ ] Replace throwaway HTML UI with a real SPA (React/Vue) consuming the **same** `/api/*` endpoints
- [ ] Background job queue (arq / RQ) + polling for large PDFs (keep `pipeline.run()` signature ready)
- [ ] Move report cache to object storage with lifecycle expiry (replace local TTL dir)
- [ ] Optional auth + persistent run history
- [ ] OCR fallback for pages with no text layer (currently warned + skipped) — must stay deterministic
- [ ] Per-column matching strategies (exact-only for codes, fuzzy for names)
- [ ] Internationalized digit/script folding beyond Arabic-Indic
