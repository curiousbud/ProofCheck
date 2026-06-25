# ProofCheck

Verify that values from an Excel spreadsheet (delegate names, codes, cities, …)
actually appear in a PDF document.

**100% deterministic. No AI / LLM / ML anywhere. Offline, no CDNs, no network at runtime.**
Matching is exact substring + [rapidfuzz](https://github.com/rapidfuzz/RapidFuzz)
fuzzy scoring; diffs come from stdlib `difflib`. Same inputs + flags always produce
the same output. The optional OCR fallback uses classic offline **Tesseract** — a fixed
glyph recogniser, not a learned model — so it stays deterministic too.

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
pytest          # 49 tests
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
