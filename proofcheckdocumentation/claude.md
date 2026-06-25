# ProofCheck — Codebase Guide (`claude.md`)

> **Index + onboarding doc for the whole ProofCheck codebase.** Start here. It links to
> per-file deep-dives in [`docs/`](docs/) and to the interactive
> [`dependency-graph.html`](dependency-graph.html). The final section is a
> **continuation brief** for resuming work in a fresh Claude Code session.

---

## 1. Purpose

ProofCheck verifies that values from an **Excel spreadsheet** (delegate names, codes,
cities, …) actually appear in a **PDF document**. It produces a per-row verdict —
`EXACT` / `FUZZY` / `MISSING` / `SKIPPED` — plus downloadable HTML and xlsx reports.

**Hard constraint (the project's defining rule): 100% deterministic. No AI / LLM / ML
anywhere. Offline, no CDNs, no network at runtime.** Matching is exact-substring +
[rapidfuzz](https://github.com/rapidfuzz/RapidFuzz) fuzzy scoring; diffs come from stdlib
`difflib`. Same inputs + flags always yield the same output.

Typical use: proof-reading a printed conference program / certificate batch against the
source delegate spreadsheet.

---

## 2. Tech stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Language | Python ≥ 3.10 | dataclasses, `str|None` typing |
| CLI | [click](https://click.palletsprojects.com/) 8.4.1 | subcommands, options |
| Excel I/O | [openpyxl](https://openpyxl.readthedocs.io/) 3.1.5 | read `.xlsx/.xlsm`, write xlsx reports |
| PDF text | [pdfplumber](https://github.com/jsvine/pdfplumber) 0.11.10 | per-page text-layer extraction |
| OCR (optional) | [pytesseract](https://github.com/madmaze/pytesseract) + [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) + [Pillow](https://python-pillow.org/) | deterministic Tesseract fallback for scanned pages; `[ocr]` extra |
| Fuzzy match | [rapidfuzz](https://github.com/rapidfuzz/RapidFuzz) 3.14.5 | deterministic `partial_ratio` + alignment |
| Diff | stdlib `difflib` | `[op,text]` opcode diffs |
| Web API | [FastAPI](https://fastapi.tiangolo.com/) 0.138.0 + [uvicorn](https://www.uvicorn.org/) 0.49.0 | JSON contract + auto-docs |
| Validation | [pydantic](https://docs.pydantic.dev/) 2.13.4 | the swap-contract schemas |
| Uploads | python-multipart 0.0.32 | multipart form handling |
| Auth + history | stdlib `sqlite3` + `hashlib`/`hmac` | opt-in users + persistent run history, zero infra |
| Frontend | framework-free SPA (vanilla JS hash router) | disposable client, no build step, no CDN |
| Tests | pytest 9.1.1, httpx 0.28.1, reportlab 5.0.0 | TestClient + deterministic fixture generation |

Full pinning and packaging: [`docs/pyproject_EXPLAINED.md`](docs/pyproject_EXPLAINED.md).

---

## 3. File-structure diagram

```
Proof-Reader/
├── claude.md                     ← you are here (index + continuation brief)
├── dependency-graph.html         ← interactive, editable import graph (open in a browser)
├── README.md                     ← user-facing usage / API contract
├── TASKS.md                      ← build checklist + v2 roadmap
├── pyproject.toml                ← pinned deps, `proofcheck` console script, [ocr] extra
├── scripts/                      ← cross-OS setup (setup.sh / setup.ps1): Tesseract + venv + install
├── docs/                         ← per-file "_EXPLAINED.md" deep-dives (this guide links them)
│
├── proofcheck/                   ← the package
│   ├── __init__.py               · version marker
│   ├── models.py                 · RunConfig / RunResult / ColumnResult / MatchResult / Status  (DATA CONTRACT)
│   ├── normalize.py              · deterministic text normalization (casefold, ws, digits, punct)
│   ├── excel.py                  · workbook load + inspect (openpyxl)
│   ├── pdf.py                    · per-page text extraction; flags no-text-layer pages; optional OCR fallback
│   ├── ocr.py                    · OPTIONAL deterministic Tesseract OCR for scanned pages (graceful no-op if absent)
│   ├── ocr_cache.py              · content-addressed OCR cache (sha256) — never OCR the same file twice
│   ├── matcher.py                · exact/fuzzy/missing/skipped + [op,text] diff   ← CORE LOGIC
│   ├── pipeline.py               · run(RunConfig) -> RunResult                    ← SHARED ORCHESTRATION
│   ├── humanize.py               · plain-language labels/sentences for the reports (presentation only)
│   ├── report_html.py            · standalone, human-readable HTML report from RunResult
│   ├── report_xlsx.py            · human-readable xlsx report from RunResult
│   ├── cli.py                    · thin click CLI: check / inspect / serve
│   └── web/                      ← disposable web layer (zero business logic)
│       ├── __init__.py
│       ├── app.py                · FastAPI routes + RunResult->JSON serialization
│       ├── schemas.py            · pydantic models = THE SWAP CONTRACT
│       ├── auth.py               · OPTIONAL auth: PBKDF2 hashing + HMAC session cookies (opt-in)
│       ├── store.py              · OPTIONAL persistence: stdlib sqlite users + run history
│       └── static/              ← framework-free SPA (disposable client)
│           ├── index.html        · SPA shell (nav + view mount)
│           ├── app.js            · hash router + views: Login / Check / History
│           └── app.css           · styles (status palette shared with reports)
│
└── tests/                        ← pytest; fixtures generated deterministically (no binaries)
    ├── conftest.py               · builds the Excel + PDF fixtures + per-test isolated sqlite DB
    ├── test_normalize.py         · incl. diacritic folding
    ├── test_matcher.py
    ├── test_pipeline.py
    ├── test_ocr.py               · OCR graceful-degradation + monkeypatched recovery
    ├── test_auth.py              · auth on/off, login/register, per-user history
    └── test_api.py               · FastAPI TestClient
```

### Architecture at a glance

```
            ┌──────────────┐         ┌──────────────────────┐
  CLI  ───► │              │         │  web/static/index.html│ (browser, vanilla JS)
            │              │         └──────────┬───────────┘
            │  cli.py      │                    │ HTTP /api/*
            └──────┬───────┘                    ▼
                   │                   ┌──────────────────┐
                   │                   │   web/app.py      │ (FastAPI, no logic)
                   │                   └──────────┬────────┘
                   │   both call the SAME         │
                   └────────────┬─────────────────┘
                                ▼
                       ┌─────────────────┐
                       │  pipeline.run() │  ◄── the single orchestration entry point
                       └───────┬─────────┘
            ┌──────────────────┼───────────────────┐
            ▼                  ▼                    ▼
       excel.py            pdf.py              matcher.py ──► normalize.py
       (openpyxl)        (pdfplumber)          (rapidfuzz/difflib)
            └──────────────────┴───────────────────┘
                                ▼
                        models.RunResult  ──► report_html.py / report_xlsx.py
```

**The golden rule:** CLI and web both call `pipeline.run(RunConfig) -> RunResult`. There
is **no duplicated orchestration**. `report_*.py` and the web JSON layer only *consume*
`RunResult`; the frontend only speaks the `/api/*` JSON contract. This is what makes the
UI swappable.

---

## 4. Key dependencies (and the layer each lives in)

- **Leaf / no internal imports:** `models.py`, `normalize.py`, `excel.py`, `pdf.py`,
  `ocr.py`, `web/schemas.py`, `web/store.py` — these depend only on stdlib/third-party libs.
- **Logic:** `matcher.py` (→ `models`, `normalize`), `report_html.py` / `report_xlsx.py` (→ `models`),
  `web/auth.py` (→ `store`).
- **Orchestration:** `pipeline.py` (→ `excel`, `pdf`, `matcher`, `models`); `pdf.py` lazily imports
  `ocr.py` only when OCR is requested.
- **Entry points:** `cli.py` and `web/app.py` (→ `pipeline`, `models`, report writers, `+ schemas`,
  `auth`, `store`, `ocr` for web).
- **Client:** `web/static/` SPA (`index.html` + `app.js` + `app.css`; runtime HTTP dependency on `web/app.py`).

See the live, draggable version in **[`dependency-graph.html`](dependency-graph.html)**.

---

## 5. Per-file documentation index

Each link is a line-by-line explainer (logic, functions, key variables, dependencies).

### Core package
| File | Deep-dive | Role |
|------|-----------|------|
| `proofcheck/__init__.py` | [proofcheck_init_EXPLAINED.md](docs/proofcheck_init_EXPLAINED.md) | Version marker |
| `proofcheck/models.py` | [models_EXPLAINED.md](docs/models_EXPLAINED.md) | Data contract (dataclasses + `Status`) |
| `proofcheck/normalize.py` | [normalize_EXPLAINED.md](docs/normalize_EXPLAINED.md) | Deterministic normalization |
| `proofcheck/excel.py` | [excel_EXPLAINED.md](docs/excel_EXPLAINED.md) | Excel load / inspect |
| `proofcheck/pdf.py` | [pdf_EXPLAINED.md](docs/pdf_EXPLAINED.md) | PDF text extraction (+ optional OCR fallback) |
| `proofcheck/ocr.py` | [ocr_EXPLAINED.md](docs/ocr_EXPLAINED.md) | Optional deterministic Tesseract OCR |
| `proofcheck/ocr_cache.py` | [ocr_cache_EXPLAINED.md](docs/ocr_cache_EXPLAINED.md) | Content-addressed OCR cache (skip unchanged files) |
| `proofcheck/matcher.py` | [matcher_EXPLAINED.md](docs/matcher_EXPLAINED.md) | Matching + diff (core logic) |
| `proofcheck/pipeline.py` | [pipeline_EXPLAINED.md](docs/pipeline_EXPLAINED.md) | Shared orchestration |
| `proofcheck/humanize.py` | [humanize_EXPLAINED.md](docs/humanize_EXPLAINED.md) | Plain-language report wording |
| `proofcheck/report_html.py` | [report_html_EXPLAINED.md](docs/report_html_EXPLAINED.md) | Human-readable HTML report writer |
| `proofcheck/report_xlsx.py` | [report_xlsx_EXPLAINED.md](docs/report_xlsx_EXPLAINED.md) | Human-readable xlsx report writer |
| `proofcheck/cli.py` | [cli_EXPLAINED.md](docs/cli_EXPLAINED.md) | CLI (check/inspect/serve) |

### Web layer
| File | Deep-dive | Role |
|------|-----------|------|
| `proofcheck/web/__init__.py` | [web_init_EXPLAINED.md](docs/web_init_EXPLAINED.md) | Web package marker |
| `proofcheck/web/app.py` | [web_app_EXPLAINED.md](docs/web_app_EXPLAINED.md) | FastAPI routes + serialization (auth/history/OCR wired) |
| `proofcheck/web/schemas.py` | [web_schemas_EXPLAINED.md](docs/web_schemas_EXPLAINED.md) | Pydantic swap contract (+ auth/history models) |
| `proofcheck/web/auth.py` | [web_auth_EXPLAINED.md](docs/web_auth_EXPLAINED.md) | Optional auth: PBKDF2 + HMAC sessions |
| `proofcheck/web/store.py` | [web_store_EXPLAINED.md](docs/web_store_EXPLAINED.md) | Optional sqlite persistence (users + runs) |
| `proofcheck/web/static/` | [web_index_html_EXPLAINED.md](docs/web_index_html_EXPLAINED.md) | Disposable framework-free SPA (index.html + app.js + app.css) |

### Tests & packaging
| File | Deep-dive |
|------|-----------|
| `tests/conftest.py` | [tests_conftest_EXPLAINED.md](docs/tests_conftest_EXPLAINED.md) |
| `tests/test_normalize.py` | [tests_test_normalize_EXPLAINED.md](docs/tests_test_normalize_EXPLAINED.md) |
| `tests/test_matcher.py` | [tests_test_matcher_EXPLAINED.md](docs/tests_test_matcher_EXPLAINED.md) |
| `tests/test_pipeline.py` | [tests_test_pipeline_EXPLAINED.md](docs/tests_test_pipeline_EXPLAINED.md) |
| `tests/test_ocr.py` | _(new in v0.2; see `ocr_EXPLAINED.md`)_ |
| `tests/test_auth.py` | _(new in v0.2; see `web_auth_EXPLAINED.md`)_ |
| `tests/test_api.py` | [tests_test_api_EXPLAINED.md](docs/tests_test_api_EXPLAINED.md) |
| `pyproject.toml` | [pyproject_EXPLAINED.md](docs/pyproject_EXPLAINED.md) |

---

## 6. Continuation brief — for resuming in a new Claude Code session

> Paste-ready context so a fresh session (after the previous one's context is gone) can
> pick up immediately. **Read this whole section first, then [`TASKS.md`](TASKS.md).**

### What this project is
ProofCheck: deterministic Excel-vs-PDF proof-reader. **No AI/LLM/ML — ever.** Offline,
no CDNs. If you're tempted to add a model/embedding/“smart” matcher, stop — that breaks
the project's core contract.

### Current state (as of this guide)
- Full core engine, CLI, web API + SPA, reports, and tests are implemented (v0.2.0).
- **52 tests pass.** Run: `pip install -e ".[dev]" && pytest`.
- v0.2 added: **optional deterministic OCR** fallback (`ocr.py`) with a **content-addressed
  cache** (`ocr_cache.py`, never OCR an unchanged file twice), **diacritic folding**
  (`--fold-diacritics`), a **framework-free SPA** (`static/app.js`), **opt-in auth +
  persistent run history** (`web/auth.py`, `web/store.py`, sqlite), and **human-readable
  reports** (`humanize.py` → HTML/xlsx/web all use Found / Found-with-differences / Not-found).
- The repo currently has read-only remote access in the build environment, so the code
  may live only in commits / a downloaded zip. **Verify `git remote` / push rights before
  assuming you can push.**

### How to run things
```bash
# One-shot cross-OS setup (Tesseract engine + venv + install + tests):
bash scripts/setup.sh                                  # Linux/macOS
# powershell -ExecutionPolicy Bypass -File scripts\setup.ps1   # Windows

# …or manually:
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"                  # core + test deps (the dev extra includes OCR libs)
# pip install -e ".[ocr]"                # OCR libs only; also needs the Tesseract *binary* on PATH
pytest                                   # 49 tests
proofcheck inspect file.xlsx             # list sheets/headers
proofcheck check file.xlsx file.pdf -c "Name" --reverse --fold-diacritics --html out.html
proofcheck check scan.xlsx scan.pdf -c "Name" --ocr --ocr-lang eng --ocr-dpi 300   # OCR scanned pages
proofcheck serve --port 8000             # SPA at http://localhost:8000  (/docs for OpenAPI)

# Optional auth (off by default — single-user "anonymous" otherwise):
PROOFCHECK_AUTH=on PROOFCHECK_ADMIN_USER=admin PROOFCHECK_ADMIN_PASSWORD=secret123 \
  proofcheck serve --port 8000
```

### Where logic lives (don't duplicate it)
- **All matching/normalization is server-side.** Add matching behavior in `matcher.py`
  (and `normalize.py` for canonicalization), never in the CLI, web layer, or frontend.
- **`pipeline.run(RunConfig) -> RunResult` is the one orchestration entry point.** CLI
  (`cli.py`) and web (`web/app.py`) both call it. Keep it that way.
- **`models.py` is the internal data contract**; `web/schemas.py` is the external JSON
  contract. Changing either is an API change — keep them in sync and backward compatible.
- The frontend (`web/static/`) is **disposable**: `app.js` only calls `/api/*`. It is a
  framework-free SPA (kept that way to honor the offline / no-CDN / no-build rule). To
  replace it with a bundled React/Vue build, swap the static files and keep the endpoints.

### Conventions / invariants to preserve
- Statuses: `EXACT` (green), `FUZZY` (amber), `MISSING` (red), `SKIPPED` (grey, blank
  cells). The same color palette is used in the HTML report, xlsx report, and web UI.
- `pass_rate = (exact + fuzzy) / (total - skipped)`; skipped cells are excluded.
- Diffs are emitted as `[op, text]` pairs (`equal|insert|delete|replace`); `replace` is
  decomposed into `delete`+`insert` so any client renders `<del>`/`<ins>` trivially.
- **OCR stays deterministic.** No-text-layer pages are warned + skipped by default. With
  `--ocr` (or the web checkbox) they are recovered via Tesseract — a fixed, offline glyph
  recogniser, NOT a learned/generative model — so same image + DPI → same text. If the OCR
  libs/binary are missing, it degrades to the old warn-and-skip behavior and never raises.
- **OCR is cached by content** (`ocr_cache.py`): keyed by `sha256(file)+dpi+lang`, so an
  unchanged file is never OCR'd twice and a changed file (different hash) is OCR'd fresh.
  The cache is an optimization only — it returns exactly what OCR would have produced.
- **Reports are human-readable** (`humanize.py` is the single source of truth). The data
  contract keeps `EXACT/FUZZY/MISSING/SKIPPED`; the HTML/xlsx writers and the SPA map those
  to Found / Found-with-differences / Not-found / Blank. If you add a status or change
  wording, update `humanize.py` **and** the `HUMAN` map in `web/static/app.js` together.
- **Auth is opt-in and stays out of the core.** All auth/history lives in `web/`; the CLI
  and `pipeline.run()` are untouched. Off by default → every request is the `anonymous`
  user, so the disposable single-user mode and the test-suite work with zero config.
  Passwords are PBKDF2-HMAC-SHA256 (salted); sessions are HMAC-signed HttpOnly cookies.
- **History stores only non-PII metadata** (filenames + summary counts + flags) in sqlite;
  the uploaded spreadsheets/PDFs are still deleted immediately after each run.
- Web ops invariants: uploads are PII → written to per-request tempfiles and **deleted
  immediately** after the run; reports cached by `run_id` with 1-hour TTL cleanup; file
  extensions validated (`400`), size cap via `MAX_UPLOAD_MB` (`413`); errors returned as
  human-readable JSON, never raw tracebacks.

### Known follow-ups (see TASKS.md “roadmap”)
- Background job queue (arq/RQ) + polling for large PDFs (`pipeline.run()` is already a
  pure function ready for a worker) — needs Redis, so out of scope for the offline MVP.
- Move report cache to object storage with lifecycle expiry — needs object storage infra.
- Per-column matching strategies (exact-only for codes, fuzzy for names).

### Done in v0.2 (previously roadmap)
- ✅ Real SPA (framework-free) replacing the throwaway UI — same `/api/*`.
- ✅ Optional auth + persistent run history (`web/auth.py`, `web/store.py`).
- ✅ Deterministic OCR fallback for no-text-layer pages (`ocr.py`).
- ✅ Diacritic/script folding beyond Arabic-Indic digits (`normalize.fold_diacritics`).

### When you change code
1. Update the relevant `docs/*_EXPLAINED.md` and this guide if structure changes.
2. Update [`dependency-graph.html`](dependency-graph.html) `NODES`/`EDGES` if you add/remove
   files or imports.
3. Run `pytest` (keep it green) and update [`TASKS.md`](TASKS.md).
