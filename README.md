# ProofCheck

Verify that values from an Excel spreadsheet (delegate names, codes, cities, …)
actually appear in a PDF document.

**100% deterministic. No AI / LLM / ML anywhere. Offline, no CDNs, no network at runtime.**
Matching is exact substring + [rapidfuzz](https://github.com/rapidfuzz/RapidFuzz)
fuzzy scoring; diffs come from stdlib `difflib`. Same inputs + flags always produce
the same output. The optional OCR fallback uses classic offline **Tesseract** — a fixed
glyph recogniser, not a learned model — so it stays deterministic too.

---

## Features

A complete tour of what ProofCheck does and why.

### Verification engine
- **Excel → PDF value checking.** Reads selected columns from a spreadsheet and verifies
  each value actually appears in the PDF. Every cell gets one verdict:
  - `EXACT` — found verbatim (after normalization)
  - `FUZZY` — found a close match at/above your similarity threshold
  - `MISSING` — no match at/above the threshold
  - `SKIPPED` — blank cell, nothing to check
- **Deterministic fuzzy matching.** rapidfuzz `partial_ratio` (0–100) with an adjustable
  `--fuzzy-threshold`. Pure function of its inputs — no randomness, no model.
- **Character-level diffs.** For every fuzzy/missing value you get a `[op, text]` diff
  (`equal`/`insert`/`delete`) showing exactly how the expected value differs from what was
  found, rendered as `<del>`/`<ins>` highlighting in the UI and reports.
- **Pass rate** = `(exact + fuzzy) / (total − skipped)`; blank cells are excluded.
- **Per-page location.** Each match reports the PDF page it was found on.

### Text normalization (toggle per run)
All normalization is deterministic and applied to both sides before comparison:
- **Always on:** Unicode NFKC, case-folding, and whitespace collapse/trim.
- **`--normalize-digits`** — fold Arabic-Indic & other Unicode digits to ASCII (`١٠` → `10`).
- **`--strip-punctuation`** — ignore punctuation/symbols when matching (`CC-101` ≈ `CC 101`).
- **`--fold-diacritics`** — accent/diacritic folding so `Núñez` matches `Nunez`, `Café` = `Cafe`.
- **`--reverse`** — also try reversed word order, so `John Smith` matches `Smith John`.

### OCR for scanned / image-only pages (optional, deterministic)
- Pages with no embedded text layer are normally reported as warnings and skipped.
- With **`--ocr`** (CLI) or the **OCR checkbox** (web), those pages are rendered
  (`pypdfium2`) and read with the offline **Tesseract** engine — a fixed glyph recognizer,
  so the same image at the same DPI always yields the same text. It recovers real glyphs;
  it never *guesses*.
- Tunable: **`--ocr-lang`** (e.g. `eng+ara`) and **`--ocr-dpi`** (default 300).
- **Cached by content — never OCR the same file twice.** OCR text is cached keyed by a
  SHA-256 of the file's bytes. Re-uploading the **same** PDF is a cache hit (no OCR, no
  engine needed); a file whose data **changed** gets a different hash and is OCR'd fresh.
  The content hash *is* the change detector. Disable with `PROOFCHECK_OCR_CACHE=off`.
- **Graceful:** if the OCR libraries or the Tesseract binary aren't present, OCR just stays
  off and pages fall back to warn-and-skip — a run never crashes. The web `/api/health`
  endpoint and the UI's "OCR ready / not installed" pill reflect availability.

### Reports (written for non-technical readers)
- **Plain language everywhere.** The web results, the printable HTML report, and the Excel
  report all use ordinary words instead of jargon: **Found** / **Found with differences** /
  **Not found** / **Blank** (no `EXACT`/`FUZZY`/`MISSING`/`SKIPPED`, no raw scores).
- Each report opens with a one-sentence overview ("We checked 12 values… 9 found, 2 with
  small differences, 1 not found") and a short "how to read this" legend.
- Every row explains itself in English — where the value was found, the exact text in the
  PDF, and a highlighted difference (red = removed, green = added) when it isn't an exact match.
- **Standalone HTML report** — self-contained, printable, color-coded.
- **Excel (.xlsx) report** — a Summary sheet plus one friendly sheet per checked column.
- All three views are generated from the same result, so they always agree.

### Command-line interface
- **`proofcheck inspect`** — list a workbook's sheets and column headers.
- **`proofcheck check`** — run a verification, write reports, print a summary. Exits
  **non-zero when anything is `MISSING`**, so it can gate CI pipelines.
- **`proofcheck serve`** — launch the web UI / JSON API.

### Web app (single-page, framework-free, offline)
- A real hash-routed SPA with three views: **Check**, **History**, and **Login**
  (when auth is enabled) — no framework, no build step, no CDN.
- Drag-free workflow: pick the Excel → it auto-loads sheets/columns into a picker → pick the
  PDF → tune flags/threshold → run. Results are filterable by status and searchable, with
  inline diff highlighting and one-click report downloads.
- Re-uploading an **edited file** re-reads it automatically (no page refresh needed), and your
  column selection is preserved across re-inspects.
- It only speaks the documented `/api/*` JSON contract, so the whole frontend is replaceable
  wholesale (e.g. with a bundled React/Vue build) without touching the backend.

### Authentication & run history (optional, opt-in, zero-infra)
- **Auth** (`PROOFCHECK_AUTH=on`): login/logout/register with salted PBKDF2-HMAC-SHA256
  password hashing and HMAC-signed HttpOnly session cookies. Off by default → a single
  `anonymous` user, so nothing is required to get started.
- **Persistent run history**: every run's **non-PII metadata** (filenames, summary counts,
  flags) is stored in SQLite and listed per user; open a past run or delete it. The uploaded
  spreadsheets/PDFs themselves are never stored.
- Both use only the standard library (`sqlite3`, `hashlib`, `hmac`) — no Redis, no database
  server, no external identity provider.

### Privacy & operational safeguards
- Uploads are treated as **PII**: streamed to per-request tempfiles and **deleted immediately**
  after each run, success or failure.
- Generated reports live in a short-lived cache keyed by an opaque `run_id`, auto-cleaned after ~1h.
- Upload **size cap** (`MAX_UPLOAD_MB`, default 25 → `413`) and **extension validation**
  (`.xlsx`/`.xlsm`, `.pdf` → `400`).
- CORS allow-list (`CORS_ORIGINS`); errors returned as human-readable JSON, never raw tracebacks.

### Architecture & tooling
- **One orchestration entry point** — `pipeline.run(RunConfig) -> RunResult`. The CLI and the
  web API both call it; there is no duplicated logic. The UI/server boundary is a documented
  JSON contract (`web/schemas.py`).
- **Cross-OS setup scripts** (`scripts/setup.sh` / `setup.ps1`) install the Tesseract engine,
  create a virtualenv, install the package, and run the tests in one command.
- **Deterministic test suite** (52 tests) with fixtures generated on the fly — no committed
  binaries. OCR tests pass with or without the engine installed.

---

## Quick setup (recommended)

One command installs the Tesseract OCR engine, creates a virtualenv, installs the package
with all extras, and runs the tests. Idempotent — safe to re-run.

```bash
# Linux / macOS
bash scripts/setup.sh

# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

See [`scripts/README.md`](scripts/README.md) for options (skip the engine, pick an
interpreter, etc.).

### Manual install

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -e .            # core only
pip install -e ".[dev]"     # + test/fixture extras
pip install -e ".[ocr]"     # + OCR helpers (also needs the Tesseract *binary*, see below)
```

This installs the `proofcheck` console script.

#### Installing the Tesseract engine (only needed for `--ocr`)

`pip install ".[ocr]"` adds the Python helpers; the **engine binary** is a separate
system install:

| OS | Command |
|----|---------|
| Debian/Ubuntu | `sudo apt-get install -y tesseract-ocr` |
| Fedora | `sudo dnf install -y tesseract` |
| Arch | `sudo pacman -S tesseract` |
| macOS | `brew install tesseract` |
| Windows | `winget install UB-Mannheim.TesseractOCR` |

ProofCheck auto-discovers the engine on PATH and at the standard Windows location
(`C:\Program Files\Tesseract-OCR`). Override with `TESSERACT_CMD=/path/to/tesseract`.
If the engine is missing, OCR simply stays disabled and no-text-layer pages are warned +
skipped, exactly as without `--ocr`.

---

## CLI

```bash
# List sheets and column headers
proofcheck inspect delegates.xlsx

# Check the "Name"/"City" columns against a PDF, with reverse name matching, write reports
proofcheck check delegates.xlsx program.pdf \
    --sheet Delegates --column "Name" --column "City" \
    --fuzzy-threshold 90 --reverse --fold-diacritics \
    --html report.html --xlsx report.xlsx

# OCR scanned / image-only pages before matching (needs the Tesseract engine)
proofcheck check scan.xlsx scan.pdf --column "Name" --ocr --ocr-lang eng --ocr-dpi 300

# Check every column
proofcheck check delegates.xlsx program.pdf --all-columns
```

`check` exits non-zero when anything is `MISSING`, so it can gate CI / scripts.

**Matching flags:** `--fuzzy-threshold N` (0-100, default 90), `--normalize-digits`
(fold Arabic-Indic & other unicode digits to ASCII), `--strip-punctuation`,
`--fold-diacritics` (accented names match their unaccented form, e.g. `Núñez` = `Nunez`),
`--reverse` (also try reversed word order, e.g. "Last First").

**OCR flags:** `--ocr` (OCR pages with no text layer), `--ocr-lang` (Tesseract language(s),
e.g. `eng+ara`), `--ocr-dpi` (render DPI, default 300).

### Status meanings & colors

| Status    | Meaning                                   | Color |
|-----------|-------------------------------------------|-------|
| `EXACT`   | Found verbatim (after normalization)      | green |
| `FUZZY`   | Close match ≥ the fuzzy threshold         | amber |
| `MISSING` | No match ≥ the threshold                  | red   |
| `SKIPPED` | Nothing to check (blank cell)             | grey  |

Pages with no text layer (scanned images) are reported as warnings and skipped — unless
`--ocr` is passed, in which case ProofCheck deterministically recovers their text via
Tesseract. It still never *guesses*: OCR reads real glyphs, and a missing engine degrades
to warn-and-skip.

---

## Web UI / API

```bash
proofcheck serve --host 0.0.0.0 --port 8000
# or directly:
uvicorn proofcheck.web.app:app --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000>. Auto-generated API docs at `/docs`.

The bundled frontend is a **framework-free single-page app** (hash-routed views:
**Check**, **History**, and **Login** when auth is on). It is still a disposable client —
it only speaks the `/api/*` JSON contract — kept framework-free to honor the offline /
no-CDN / no-build rule.

### Architecture: why the frontend is swappable

The frontend contains **zero business logic**. All matching/normalization/OCR lives
server-side in `proofcheck/pipeline.py`. The CLI and the web API both call the **same**
`pipeline.run(RunConfig) -> RunResult` function — there is no duplicated logic. The
boundary between UI and server is a documented JSON HTTP API (`proofcheck/web/schemas.py`
= the contract).

**To replace the UI** (React/Vue/whatever): delete `proofcheck/web/static/`, drop in your
build's `dist/`, point it at the same `/api/*` endpoints. Backend untouched.

### API contract

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/` | Serves the SPA shell |
| `GET`  | `/static/*` | SPA assets (`app.js`, `app.css`) |
| `GET`  | `/api/health` | `{"status","version","auth_enabled","ocr_available"}` |
| `POST` | `/api/inspect` | multipart `excel` → `{sheets, headers}` for the column picker |
| `POST` | `/api/check` | multipart `excel`+`pdf`+form fields → full `RunResult` JSON |
| `GET`  | `/reports/{run_id}.{html\|xlsx}` | Download the generated report |
| `POST` | `/api/auth/login` · `/logout` · `/register` | Session auth (when enabled) |
| `GET`  | `/api/auth/me` | Current user |
| `GET`  | `/api/history` | List the user's past runs (metadata) |
| `GET` / `DELETE` | `/api/history/{run_id}` | Fetch / delete one past run |

`POST /api/check` form fields: `columns` (comma-separated), `all_columns`, `sheet`,
`header_row`, `fuzzy_threshold`, `normalize_digits`, `strip_punctuation`,
`fold_diacritics`, `reverse`, `ocr`, `ocr_lang`, `ocr_dpi`.

Response shape:

```json
{
  "meta":    { "excel":"…", "pdf":"…", "timestamp":"…", "fuzzy_threshold":90, "flags":{…} },
  "summary": { "total":5, "exact":1, "fuzzy":1, "missing":2, "skipped":1, "pass_rate":0.5 },
  "columns": [
    { "name":"Name",
      "results":[
        { "row":2, "expected":"Gauttam Sharma", "status":"FUZZY", "page":1,
          "best_match":"gautam sharma", "score":96,
          "diff":[["equal","gau"],["delete","t"],["equal","tam sharma"]] }
      ] }
  ],
  "warnings": ["Page 2 has no text layer — OCR required, skipped."],
  "report_urls": { "html":"/reports/<run_id>.html", "xlsx":"/reports/<run_id>.xlsx" }
}
```

The `diff` is emitted as `[op, text]` pairs (`op` ∈ `equal|insert|delete|replace`)
so **any** frontend renders highlighting itself — the server never bakes in
`<del>`/`<ins>` HTML.

### Authentication & run history (optional)

Both are **opt-in** and need no extra infrastructure (stdlib `sqlite3` + `hashlib`/`hmac`).
Auth is **off by default** — every request is the single-user `anonymous` identity, so the
disposable UI and the CLI work with zero config. Enable auth by setting `PROOFCHECK_AUTH=on`:

```bash
PROOFCHECK_AUTH=on \
PROOFCHECK_ADMIN_USER=admin PROOFCHECK_ADMIN_PASSWORD=change-me-now \
  proofcheck serve --port 8000
```

Passwords are salted PBKDF2-HMAC-SHA256; sessions are HMAC-signed HttpOnly cookies.
**Run history persists only non-PII metadata** (filenames + summary counts + flags) in
SQLite, scoped per user; uploaded spreadsheets/PDFs are still deleted immediately after
each run.

### Configuration (env vars)

| Var | Default | Purpose |
|-----|---------|---------|
| `MAX_UPLOAD_MB` | `25` | Per-file upload cap; over → `413` |
| `CORS_ORIGINS` | `http://localhost,…:8000,127.0.0.1:8000` | Comma-separated allowed origins |
| `PROOFCHECK_AUTH` | `off` | `on` enables session auth |
| `PROOFCHECK_SECRET` | autogenerated | HMAC key for session tokens (set to persist across restarts) |
| `PROOFCHECK_SESSION_HOURS` | `12` | Session lifetime |
| `PROOFCHECK_ADMIN_USER` / `_PASSWORD` | — | Bootstrap admin (created if no users exist) |
| `PROOFCHECK_ALLOW_REGISTER` | `off` | `on` exposes `POST /api/auth/register` |
| `PROOFCHECK_DB` | `<tempdir>/proofcheck/proofcheck.db` | SQLite path for users + history |
| `TESSERACT_CMD` | auto-discover | Explicit path to the Tesseract binary |

### Operational notes

- File extensions are validated (`.xlsx`/`.xlsm`, `.pdf`); others → `400`.
- Uploads are real PII (delegate names): written to per-request tempfiles and
  **deleted immediately** after the run, success or failure. They are never persisted.
- Generated reports go to a short-lived cache dir keyed by `run_id`; files older than
  1h are cleaned up on each request. Run **history** (metadata only) outlives them in SQLite.
- Errors are returned as human-readable JSON (`{"error": "…"}`) — never raw tracebacks.
- Processing is **synchronous** for the MVP. For large PDFs, move work to a background
  job queue (arq / RQ) + polling. `pipeline.run()` is a pure function ready to be called
  from a worker without changes.

---

## Deploying

ProofCheck is a Python/FastAPI server (it needs the Tesseract binary for OCR and a writable
filesystem), so it runs on container/PaaS/VPS hosts. The repo ships a production
[`Dockerfile`](Dockerfile), [`docker-compose.yml`](docker-compose.yml), and ready configs in
[`deploy/`](deploy/) for Render, Fly.io, Heroku, Netlify, and Vercel.

```bash
docker compose up --build -d     # full app (incl. OCR) on http://localhost:8000
```

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for step-by-step guides: Docker, Cloud Run, Render,
Railway, Fly.io, Heroku, AWS, Azure, DigitalOcean, a plain VPS (systemd + nginx), and using
Netlify/Vercel for the SPA with the API proxied to your backend.

## Project layout

```
scripts/
  setup.sh / setup.ps1     # cross-OS: Tesseract engine + venv + install + tests
proofcheck/
  models.py        # RunConfig / RunResult / ColumnResult / MatchResult (internal contract)
  normalize.py     # deterministic text normalization (casefold, digits, punct, diacritics)
  excel.py         # workbook load + inspect (openpyxl)
  pdf.py           # per-page text extraction (pdfplumber) + optional OCR fallback
  ocr.py           # OPTIONAL deterministic Tesseract OCR (graceful no-op if absent)
  matcher.py       # exact/fuzzy/missing/skipped + [op,text] diff
  pipeline.py      # SHARED orchestration: run(RunConfig) -> RunResult
  report_html.py   # standalone HTML report
  report_xlsx.py   # xlsx report
  cli.py           # thin click CLI: check / inspect / serve
  web/
    app.py         # FastAPI: routes + RunResult->JSON only (no business logic)
    schemas.py     # pydantic models = THE SWAP CONTRACT
    auth.py        # OPTIONAL auth: PBKDF2 hashing + HMAC session cookies
    store.py       # OPTIONAL sqlite persistence: users + run history
    static/        # framework-free SPA: index.html + app.js + app.css
tests/             # pytest; fixtures generated deterministically in conftest.py
```

Full per-file deep-dives live in [`proofcheckdocumentation/`](proofcheckdocumentation/)
(start at `claude.md`).

## Tests

```bash
pip install -e ".[dev]"
pytest          # 52 tests
```

OCR tests cover both the real graceful-degradation path and a monkeypatched recovery path,
so the suite passes whether or not the Tesseract engine is installed.

## Roadmap

Done in v0.2: real (framework-free) SPA, optional auth + persistent run history,
deterministic OCR fallback, diacritic folding. Still open:

- Background job queue (arq/RQ) + polling for large files — needs Redis (out of the offline MVP)
- Report cache → object storage with lifecycle expiry — needs object storage
- Per-column matching strategies (exact-only for codes, fuzzy for names)

See [`TASKS.md`](TASKS.md) for the full checklist.
