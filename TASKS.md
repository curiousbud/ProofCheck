# ProofCheck — Task Checklist

ProofCheck is a **100% deterministic** tool (NO AI / LLM / ML, offline, no CDNs) that
verifies values from an Excel spreadsheet (delegate names, codes, cities, …) actually
appear in a PDF document. It supports fuzzy matching, normalization, and produces
HTML / xlsx reports plus a swappable web UI.

## Core engine
- [x] `models.py` — `RunConfig`, `RunResult`, `ColumnResult`, `MatchResult`, `Status` (the stable data contract)
- [x] `normalize.py` — deterministic normalization (casefold, whitespace, optional digit-fold + punctuation strip + **diacritic fold**)
- [x] `excel.py` — load workbook, inspect sheets/headers, read column values per row
- [x] `pdf.py` — per-page text extraction, detect pages with no text layer (warnings), **optional OCR fallback**
- [x] `ocr.py` — **optional, deterministic Tesseract OCR** for no-text-layer (scanned) pages; graceful no-op when absent
- [x] `matcher.py` — exact / fuzzy / missing / skipped matching + `[op,text]` diff (difflib)
- [x] `pipeline.py` — **shared orchestration** `run(RunConfig) -> RunResult` (CLI + web call this, no duplication)

## Reports
- [x] `report_html.py` — standalone HTML report from `RunResult` (status colors, diff highlighting)
- [x] `report_xlsx.py` — xlsx report from `RunResult` (summary + per-column sheets, color-coded)

## CLI (thin wrapper)
- [x] `cli.py` — `check` (parse args -> `RunConfig` -> `pipeline.run()` -> report writers)
- [x] `cli.py` — `check` OCR + folding flags: `--ocr` / `--ocr-lang` / `--ocr-dpi` / `--fold-diacritics`
- [x] `cli.py` — `inspect` (list sheets/headers)
- [x] `cli.py` — `serve` subcommand (launches uvicorn on `web.app:app`)

## Web frontend (real SPA + auth + history)
- [x] `web/schemas.py` — pydantic models = **THE SWAP CONTRACT** (now incl. auth + history models)
- [x] `web/app.py` — FastAPI routes + `RunResult` -> JSON serialization only (zero business logic)
- [x] `GET /` serves the SPA shell; `GET /api/health` (now reports `auth_enabled` + `ocr_available`)
- [x] `GET /static/*` — SPA assets mounted (app.js / app.css)
- [x] `POST /api/inspect` — sheets + headers for the column picker
- [x] `POST /api/check` — documented JSON response shape + `report_urls` (now incl. OCR + fold flags)
- [x] `GET /reports/{run_id}.{html|xlsx}` — download generated reports
- [x] **Auth** — `web/auth.py` (PBKDF2 hashes + HMAC session cookies); `POST /api/auth/{login,logout,register}`, `GET /api/auth/me`; opt-in via `PROOFCHECK_AUTH`
- [x] **Persistent run history** — `web/store.py` (stdlib sqlite); `GET /api/history`, `GET/DELETE /api/history/{run_id}`
- [x] `web/static/` — **real hash-routed SPA** (`index.html` + `app.js` + `app.css`): Login / Check / History views, all over the same `/api/*` contract

## Ops / production touches (MVP-appropriate)
- [x] Validate file extensions (.xlsx/.xlsm, .pdf) -> 400
- [x] `MAX_UPLOAD_MB` env (default 25) -> 413 over limit
- [x] Uploads written to per-request tempfiles, **deleted immediately** after run (PII)
- [x] Reports in short-lived cache dir keyed by `run_id`, TTL cleanup (>1h) on each request
- [x] CORS middleware, allowed origins via `CORS_ORIGINS` env (default localhost)
- [x] Human-readable JSON errors (no raw tracebacks)

## Packaging & tests
- [x] `pyproject.toml` — pinned deps, `proofcheck` console script, **optional `[ocr]` extra**
- [x] `scripts/setup.sh` + `scripts/setup.ps1` — **cross-OS setup**: install Tesseract engine, venv, `pip install -e ".[dev,ocr]"`, run tests
- [x] `tests/conftest.py` — generates Excel + PDF fixtures (deterministic) + per-test isolated sqlite DB
- [x] `test_normalize.py` (incl. diacritic folding), `test_matcher.py`, `test_pipeline.py`
- [x] `test_ocr.py` — OCR graceful-degradation + monkeypatched recovery + flag echo
- [x] `test_auth.py` — auth on/off, login/logout/register, per-user persistent history
- [x] `test_api.py` — TestClient: inspect shape, check shape + status counts, 400 bad ext, 413 oversize, SPA assets
- [x] `README.md` — usage, API contract, swap instructions, ops/roadmap notes

## Future suggestions / roadmap
- [x] Replace throwaway HTML UI with a real SPA consuming the **same** `/api/*` endpoints
      *(done framework-free — hash-routed vanilla SPA — to honor the offline/no-CDN/no-build rule)*
- [x] Optional auth + persistent run history *(opt-in via `PROOFCHECK_AUTH`; sqlite-backed)*
- [x] OCR fallback for pages with no text layer (was warned + skipped) — stays deterministic (Tesseract)
- [x] Internationalized digit/script folding beyond Arabic-Indic *(diacritic/accent folding added; digit fold already covers all unicode scripts)*
- [ ] Background job queue (arq / RQ) + polling for large PDFs (keep `pipeline.run()` signature ready) — *needs Redis; out of scope for the offline MVP*
- [ ] Move report cache to object storage with lifecycle expiry (replace local TTL dir) — *needs object storage; out of scope for the offline MVP*
- [ ] Per-column matching strategies (exact-only for codes, fuzzy for names)
