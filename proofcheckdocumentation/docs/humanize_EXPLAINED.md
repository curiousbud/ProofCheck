# `proofcheck/humanize.py` — Explained

> Plain-language presentation helpers shared by the HTML and xlsx reports. Turns the terse machine statuses and numeric scores into everyday English. Presentation only — no effect on matching or the API.

## Purpose
Non-technical readers find `EXACT`/`FUZZY`/`MISSING`/`SKIPPED` and raw fuzzy scores confusing. This module is the single source of truth for the friendly wording — labels, icons, a one-sentence run overview, and a per-row explanation — so the HTML report and the xlsx report read identically. (The web UI carries a small JS twin of this map in `static/app.js`.) Crucially it changes **only presentation**: `models.Status` and the JSON API still use the machine statuses, so the data contract is untouched.

## Dependencies
- **External:** none.
- **Internal:** `from .models import MatchResult, RunResult, Status`.
- **Used by:** `proofcheck/report_html.py` and `proofcheck/report_xlsx.py`.

## The vocabulary
`LABELS` maps each `Status` to `(friendly label, icon, one-line meaning)`:

| Status | Label | Icon | Meaning |
| --- | --- | --- | --- |
| `EXACT` | Found | ✓ | Found in the PDF exactly. |
| `FUZZY` | Found with differences | ≈ | Found, but not an exact match — check the differences. |
| `MISSING` | Not found | ✗ | Could not be found in the PDF. |
| `SKIPPED` | Blank | – | The spreadsheet cell was empty. |

## Functions
| Name | Signature | Description |
| --- | --- | --- |
| `label` / `icon` / `meaning` | `(status) -> str` | The three `LABELS` fields. |
| `summary_sentence` | `summary_sentence(result) -> str` | One-line overview, e.g. "We checked 4 values…: 1 found; 1 found with small differences; 1 not found. 1 blank cell was skipped." |
| `detail` | `detail(r) -> str` | Per-row plain English: where it was found, the PDF text, and `% similar` for fuzzy/missing-with-closest. |

## Notes / gotchas
- **Presentation-only contract:** never let matching logic depend on these strings; they are
  for humans. The renderers map `Status` → wording here; the API keeps `Status` values.
- **`detail` wording adapts** to the status: exact → "Found on page N"; fuzzy → shows both
  the spreadsheet value and the PDF value with `% similar`; missing → either "Not found
  anywhere" or "closest text … too different"; skipped → "cell was empty".
- **Unicode icons** (`✓ ≈ ✗ –`) and curly quotes are safe in the UTF-8 HTML report and in
  xlsx (openpyxl), and in the browser. They are deliberately **not** printed by the CLI
  summary (which stays ASCII for legacy consoles).
- **Keep the JS twin in sync:** if you change a label here, update the `HUMAN` map in
  `proofcheck/web/static/app.js` so the live UI matches the downloadable reports.
