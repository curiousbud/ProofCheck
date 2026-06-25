# `proofcheck/pdf.py` — Explained

> Deterministic extraction of a PDF's embedded text layer page by page via pdfplumber, reporting pages with no extractable text (scanned images) instead of OCR-ing them.

## Purpose
This module is the PDF ingestion layer of ProofCheck. It opens a PDF and pulls the embedded text layer of every page into a 1-based page-number → text map. Pages that yield no extractable text (e.g. scanned image-only pages that would need OCR) are recorded separately and surfaced as warnings so the caller can skip them. It stays fully deterministic — it never OCRs, infers, or guesses content.

## Dependencies
- **Imports (external):**
  - `from __future__ import annotations` — defers annotation evaluation for cheap/forward-compatible type hints.
  - `from dataclasses import dataclass, field` — defines the `PdfText` container; `field(default_factory=...)` gives each instance fresh mutable defaults.
  - `import pdfplumber` — the PDF text-layer extractor; provides `pdfplumber.open(...)` and `page.extract_text()`.
- **Imports (internal):** None.
- **Used by:**
  - `proofcheck/pipeline.py` — calls `pdf.extract(config.pdf_path)`, catches `pdf.PdfError`, and uses `pdf_text.pages` and `pdf_text.warnings()` (step 2 of the run pipeline).

## Line-by-line / block-by-block breakdown

### Module docstring & `from __future__ import annotations`
```python
"""PDF text-layer extraction (pdfplumber).

Pulls the embedded text layer of each page. Pages with no extractable text
(scanned images needing OCR) are reported so the caller can warn and skip them.
This stays fully deterministic — we never OCR or guess.
"""

from __future__ import annotations
```
Documents scope and explicitly commits to no-OCR determinism.

### `class PdfError(Exception)`
```python
class PdfError(Exception):
    """Raised for user-facing PDF problems (unreadable/corrupt file)."""
```
A dedicated exception type so the pipeline/web layer can present clean error messages for unreadable or corrupt PDFs rather than leaking raw pdfplumber/internal errors.

### `class PdfText`
```python
@dataclass
class PdfText:
    """Extracted PDF text, page by page."""

    # 1-based page number -> extracted text (already whitespace-joined by pdfplumber).
    pages: dict[int, str] = field(default_factory=dict)
    # 1-based page numbers that had no extractable text layer.
    empty_pages: list[int] = field(default_factory=list)
```
The result container. `pages` maps 1-based page numbers to their extracted text (pdfplumber already joins whitespace). `empty_pages` lists the 1-based page numbers that had no text layer. Both use `field(default_factory=...)` so each `PdfText()` gets its own dict/list (avoiding the classic shared-mutable-default bug).

```python
    @property
    def page_count(self) -> int:
        return len(self.pages)
```
Convenience property: total number of pages recorded (every page, including empty ones, is added to `pages`).

```python
    def warnings(self) -> list[str]:
        return [
            f"Page {p} has no text layer — OCR required, skipped."
            for p in self.empty_pages
        ]
```
Generates one human-readable warning string per empty page, for display by the CLI/web reports.

### `extract(path)`
```python
def extract(path: str) -> PdfText:
    """Extract text from every page of the PDF at ``path``."""
    result = PdfText()
    try:
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                result.pages[i] = text
                if not text.strip():
                    result.empty_pages.append(i)
    except PdfError:
        raise
    except Exception as exc:
        raise PdfError(f"Could not read PDF file: {exc}") from exc
    return result
```
The single public function. It creates an empty `PdfText`, opens the PDF in a context manager (guaranteeing the file is closed), and iterates pages with `enumerate(..., start=1)` so `i` is the 1-based page number. `page.extract_text()` returns the text layer or `None` for an empty page; `or ""` normalizes that to a string. Every page (even empty) is stored in `result.pages[i]`. If the stored text is blank after `.strip()`, the page number is appended to `empty_pages`.

Error handling: a `PdfError` raised inside is re-raised unchanged (`except PdfError: raise`), so an explicit PdfError isn't double-wrapped; any other exception (corrupt file, unreadable path, pdfplumber internals) is wrapped into a user-facing `PdfError` preserving the cause via `from exc`. The populated `result` is returned on success.

## Functions / Methods / Classes
| Name | Signature | Returns | Description |
| --- | --- | --- | --- |
| `PdfError` | `class PdfError(Exception)` | — | User-facing PDF error type (unreadable/corrupt file). |
| `PdfText` | `@dataclass PdfText(pages: dict[int,str] = {}, empty_pages: list[int] = [])` | — | Per-page extracted text plus list of empty (no-text-layer) pages. |
| `PdfText.page_count` | `page_count(self) -> int` (property) | `int` | Number of pages recorded in `pages`. |
| `PdfText.warnings` | `warnings(self) -> list[str]` | `list[str]` | One warning string per empty page. |
| `extract` | `extract(path: str) -> PdfText` | `PdfText` | Extracts the text layer of every page; records empty pages. |

## Key variables / constants
| Name | Purpose |
| --- | --- |
| `result` | The `PdfText` instance accumulated and returned by `extract`. |
| `i` | Current 1-based page number during iteration. |
| `text` | Extracted text for the current page, normalized to `""` when none. |
| `pages` | (field) Map of 1-based page number -> extracted text. |
| `empty_pages` | (field) 1-based page numbers with no extractable text layer. |

## Notes / gotchas
- **Determinism:** No OCR, no inference — output is purely the embedded text layer. Scanned/image-only pages are reported, never guessed.
- **No-text-layer pages:** detected via `not text.strip()`; such pages are still present in `pages` (mapped to `""`) and additionally listed in `empty_pages`, so `page_count` counts them too.
- **1-based numbering:** `enumerate(..., start=1)` keeps page numbers aligned with what users see in a PDF viewer / reports.
- **`extract_text()` returning `None`:** normalized with `or ""` so the rest of the code can assume a string.
- **Error handling:** explicit `PdfError`s pass through unchanged; all other failures are wrapped into `PdfError` (with `from exc`) for clean user-facing messages. The `with pdfplumber.open(...)` context manager ensures the file handle is always released.
- **Whitespace:** pdfplumber already joins/normalizes whitespace within a page's extracted text; this module does not re-tokenize it.

## v0.2 changes

`extract()` now takes `ocr`/`ocr_dpi`/`ocr_lang`. When `ocr=True` and pages have no text layer, `_apply_ocr` lazily imports `proofcheck.ocr` and recovers them. `PdfText` gained `ocr_pages`, `ocr_unavailable_reason`, and `ocr_error` fields; `warnings()` now reports OCR-recovered pages and any OCR unavailability/error. OCR never raises into a run -- failures are recorded as warnings, preserving determinism. See ocr_EXPLAINED.md.


## v0.2 changes (continued)

`PdfText` gained `ocr_from_cache`. `_apply_ocr` now consults `ocr_cache` first (keyed by sha256 of the file + dpi + lang): an identical file reuses cached OCR text with no re-OCR and without even needing the engine; a changed file (different hash) is OCR'd fresh and stored. `warnings()` distinguishes cache reuse ('file unchanged') from fresh OCR. See ocr_cache_EXPLAINED.md.

