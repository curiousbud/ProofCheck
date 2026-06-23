# ProofCheck

Verify that values from an Excel spreadsheet (delegate names, codes, cities, …)
actually appear in a PDF document.

**100% deterministic. No AI / LLM / ML anywhere. Offline, no CDNs, no network at runtime.**
Matching is exact substring + [rapidfuzz](https://github.com/rapidfuzz/RapidFuzz)
fuzzy scoring; diffs come from stdlib `difflib`. Same inputs + flags always produce
the same output.

---

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .          # add ".[dev]" for the test/fixture extras
```

This installs the `proofcheck` console script.

## CLI

```bash
# List sheets and column headers
proofcheck inspect delegates.xlsx

# Check the "Name" column against a PDF, with reverse name matching, write reports
proofcheck check delegates.xlsx program.pdf \
    --sheet Delegates --column "Name" --column "City" \
    --fuzzy-threshold 90 --reverse \
    --html report.html --xlsx report.xlsx

# Check every column
proofcheck check delegates.xlsx program.pdf --all-columns
```

`check` exits non-zero when anything is `MISSING`, so it can gate CI / scripts.

Flags: `--fuzzy-threshold N` (0-100, default 90), `--normalize-digits`
(fold Arabic-Indic & other unicode digits to ASCII), `--strip-punctuation`,
`--reverse` (also try reversed word order, e.g. "Last First").

### Status meanings & colors

| Status    | Meaning                                   | Color |
|-----------|-------------------------------------------|-------|
| `EXACT`   | Found verbatim (after normalization)      | green |
| `FUZZY`   | Close match ≥ the fuzzy threshold         | amber |
| `MISSING` | No match ≥ the threshold                  | red   |
| `SKIPPED` | Nothing to check (blank cell)             | grey  |

Pages with no text layer (scanned images) are reported as warnings and skipped —
ProofCheck never OCRs or guesses.

## Web UI / API

```bash
proofcheck serve --host 0.0.0.0 --port 8000
# or directly:
uvicorn proofcheck.web.app:app --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000>. Auto-generated API docs at `/docs`.

### Architecture: why the frontend is swappable

The frontend contains **zero business logic**. All matching/normalization lives
server-side in `proofcheck/pipeline.py`. The CLI and the web API both call the
**same** `pipeline.run(RunConfig) -> RunResult` function — there is no duplicated
logic. The boundary between UI and server is a documented JSON HTTP API
(`proofcheck/web/schemas.py` = the contract).

**To replace the UI** (React/Vue/whatever): delete `proofcheck/web/static/`, drop
in your build's `dist/`, point it at the same `/api/*` endpoints. Backend untouched.

### API contract

| Method | Path                         | Purpose |
|--------|------------------------------|---------|
| `GET`  | `/`                          | Serves the bundled disposable UI |
| `GET`  | `/api/health`                | `{"status":"ok","version":"…"}` |
| `POST` | `/api/inspect`               | multipart `excel` → `{sheets, headers}` for the column picker |
| `POST` | `/api/check`                 | multipart `excel`+`pdf`+form fields → full `RunResult` JSON |
| `GET`  | `/reports/{run_id}.{html\|xlsx}` | Download the generated report |

`POST /api/check` form fields: `columns` (comma-separated), `all_columns`, `sheet`,
`header_row`, `fuzzy_threshold`, `normalize_digits`, `strip_punctuation`, `reverse`.

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

### Configuration (env vars)

| Var             | Default                                   | Purpose |
|-----------------|-------------------------------------------|---------|
| `MAX_UPLOAD_MB` | `25`                                      | Per-file upload cap; over → `413` |
| `CORS_ORIGINS`  | `http://localhost,…:8000,127.0.0.1:8000`  | Comma-separated allowed origins for a future hosted SPA |

### Operational notes

- File extensions are validated (`.xlsx`/`.xlsm`, `.pdf`); others → `400`.
- Uploads are real PII (delegate names): written to per-request tempfiles and
  **deleted immediately** after the run, success or failure. They are never persisted.
- Generated reports go to a short-lived cache dir keyed by `run_id`; files older than
  1h are cleaned up on each request. **Production should move this to object storage
  with lifecycle expiry.**
- Errors are returned as human-readable JSON (`{"error": "…"}`) — never raw tracebacks.
- Processing is **synchronous** for the MVP. For large PDFs, move work to a background
  job queue (arq / RQ) + polling. `pipeline.run()` is a pure function ready to be called
  from a worker without changes.

## Project layout

```
proofcheck/
  models.py        # RunConfig / RunResult / ColumnResult / MatchResult (internal contract)
  normalize.py     # deterministic text normalization
  excel.py         # workbook load + inspect (openpyxl)
  pdf.py           # per-page text extraction (pdfplumber)
  matcher.py       # exact/fuzzy/missing/skipped + [op,text] diff
  pipeline.py      # SHARED orchestration: run(RunConfig) -> RunResult
  report_html.py   # standalone HTML report
  report_xlsx.py   # xlsx report
  cli.py           # thin click CLI: check / inspect / serve
  web/
    app.py         # FastAPI: routes + RunResult->JSON only (no business logic)
    schemas.py     # pydantic models = THE SWAP CONTRACT
    static/index.html  # minimal vanilla UI (replaceable wholesale)
tests/             # pytest; fixtures generated deterministically in conftest.py
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```

## Roadmap (v2)

The bundled HTML UI is **intentionally throwaway**. The stable parts are
`pipeline.run()` and the `/api/*` JSON contract.

- Real SPA (React/Vue) consuming the same endpoints
- Background job queue (arq/RQ) + polling for large files
- Report cache → object storage with lifecycle expiry
- Optional auth + persistent run history
- Deterministic OCR fallback for no-text-layer pages

See [`TASKS.md`](TASKS.md) for the full checklist and future suggestions.
