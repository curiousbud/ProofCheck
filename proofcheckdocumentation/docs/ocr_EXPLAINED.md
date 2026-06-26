# `proofcheck/ocr.py` — Explained

> Optional, deterministic OCR fallback that recovers text from no-text-layer (scanned/image-only) PDF pages using the offline Tesseract engine, while preserving ProofCheck's "no AI/LLM/ML, same-input-same-output" guarantee.

## Purpose
By default ProofCheck only reads a PDF's embedded text layer; scanned/image-only pages have none and are warned + skipped. This module adds an **opt-in** recovery step: it renders those pages to images (via `pypdfium2`) and runs **Tesseract** OCR (via `pytesseract`) over them. Classic Tesseract is a fixed, offline glyph recogniser — not a learned/generative model — so the same image at the same DPI always yields the same text, keeping the project deterministic. The whole feature degrades gracefully: if the rendering/OCR libraries or the Tesseract binary are missing, OCR reports itself unavailable and the caller falls back to the original warn-and-skip behavior.

## Dependencies
- **Imports (external, all optional):**
  - `import pypdfium2 as _pdfium` — pure-wheel PDF renderer (no system binary). Wrapped in `try/except`; `None` when absent.
  - `import pytesseract as _pytesseract` — thin wrapper around the Tesseract engine binary. Wrapped in `try/except`; `None` when absent. (`Pillow` is pulled in transitively and used implicitly via `bitmap.to_pil()`.)
- **Imports (internal):** None — this is a leaf module.
- **Used by:**
  - `proofcheck/pdf.py` — `extract(..., ocr=True)` lazily imports this module inside `_apply_ocr` and calls `available()`, `unavailable_reason()`, and `ocr_pages(...)`.
  - `proofcheck/web/app.py` — `/api/health` reports `ocr.available()` so the SPA can show OCR readiness.

## Configuration constants
| Name | Value | Purpose |
| --- | --- | --- |
| `DEFAULT_DPI` | `300` | Conventional Tesseract accuracy sweet spot for rendered pages. |
| `DEFAULT_LANG` | `"eng"` | Tesseract language pack(s); supports `"eng+ara"` style combos. |
| `_PDF_POINTS_PER_INCH` | `72.0` | PDF user-space unit; render scale = `dpi / 72`. |

## Line-by-line / block-by-block breakdown

### Optional imports
```python
try:
    import pypdfium2 as _pdfium
except Exception:
    _pdfium = None
try:
    import pytesseract as _pytesseract
except Exception:
    _pytesseract = None
```
Both heavy/optional dependencies are imported defensively. A missing dependency leaves the alias as `None` rather than raising at import time, so importing `proofcheck.ocr` is always safe even on a minimal install.

### `class OcrError(Exception)`
A dedicated exception for user-facing OCR problems (bad render, engine failure). `pdf._apply_ocr` catches it and records it as a warning rather than letting it crash a run.

### `tesseract_available()`
```python
def tesseract_available() -> bool:
    if _pytesseract is None:
        return False
    try:
        _pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False
```
Distinguishes "pytesseract installed" from "the Tesseract **binary** is callable on PATH". `get_tesseract_version()` shells out to the engine; any failure (binary missing) means OCR can't actually run.

### `available()` / `unavailable_reason()`
`available()` returns `True` only when both the renderer (`_pdfium`) and a usable Tesseract engine are present. `unavailable_reason()` returns a human-readable explanation (which piece is missing) or `None` when OCR is ready. The two are designed to agree: `available()` is `True` ⇔ `unavailable_reason()` is `None` (asserted in `tests/test_ocr.py`).

### `ocr_pages(path, page_numbers, *, dpi, lang)`
```python
if not available():
    raise OcrError(unavailable_reason() or "OCR is unavailable.")
scale = dpi / _PDF_POINTS_PER_INCH
document = _pdfium.PdfDocument(path)
...
page = document[page_number - 1]
bitmap = page.render(scale=scale)
image = bitmap.to_pil()
text = _pytesseract.image_to_string(image, lang=lang)
```
The single public workhorse. It guards on `available()`, computes the render scale from DPI, opens the document once, and for each requested **1-based** page renders it to a PIL image and OCRs it. Out-of-range page numbers are skipped (not errors). Per-page failures are wrapped in `OcrError` (with `from exc`); the document is always closed in a `finally`. Returns `{page_number: text}`. Determinism comes from the fixed render scale + Tesseract's non-stochastic default engine.

## Functions / Methods / Classes
| Name | Signature | Returns | Description |
| --- | --- | --- | --- |
| `OcrError` | `class OcrError(Exception)` | — | User-facing OCR error type. |
| `tesseract_available` | `tesseract_available() -> bool` | `bool` | True if pytesseract + the Tesseract binary are usable. |
| `available` | `available() -> bool` | `bool` | True if renderer **and** engine are present. |
| `unavailable_reason` | `unavailable_reason() -> str \| None` | `str \| None` | Why OCR can't run, or `None`. |
| `ocr_pages` | `ocr_pages(path, page_numbers, *, dpi=300, lang="eng") -> dict[int,str]` | `dict[int,str]` | Render + OCR the given 1-based pages. |

## Notes / gotchas
- **Determinism:** Tesseract is a fixed offline recogniser; same image + DPI → same text. This is why OCR is allowed despite the "no ML" rule — it recovers real glyphs, it does not *guess/generate*.
- **Three-part availability:** `pypdfium2` (pip wheel) + `pytesseract` (pip) + the **Tesseract engine binary** (OS package manager). The binary is the piece pip can't provide; `unavailable_reason()` calls it out explicitly.
- **Never partially mutates on failure:** callers (`pdf._apply_ocr`) treat any `OcrError` as "leave the page in `empty_pages`", so a failed OCR never produces nondeterministic partial output.
- **1-based page numbers** match `pdf.PdfText.empty_pages` and what users see in a viewer.
- **Install:** `pip install 'proofcheck[ocr]'` for the libs; the engine binary is separate (e.g. `apt install tesseract-ocr`, `choco install tesseract`).

## v0.2 changes (OCR diagnostics + source column)

Engine improvements: pages are now rendered then preprocessed deterministically by `_render_page` (flatten transparency onto white, convert to grayscale, autocontrast) before Tesseract, recognized with LSTM (`--oem 3`) and a configurable page-segmentation mode (`psm`, default 3). New `diagnose(path, pages, ..., save_dir=None)` returns `PageDiagnostic` (text, mean_confidence, word_count, image_path) for verifying OCR quality; `version()` reports the engine version. `ocr_pages` gained `psm`/`oem` params.


## v0.2 changes (robust multi-strategy engine)

OCR now tries several deterministic strategies per page and keeps the most confident result
(`_best_ocr`): two preprocessings — grayscale+autocontrast and **Otsu binarization**
(`_otsu_threshold`, pure-Python, no numpy) — times the requested `psm` plus single-block
(6) and columns (4) fallbacks. Selection is by amount of *confident* text (words with conf
>= 40), which fixes the failure mode where psm 3 returns nothing yet reports ~95% confidence
on a sparse page. `PageDiagnostic` gained a `strategy` label (e.g. `binary/psm6`) and
`diagnose` saves the winning preprocessed image. Note: up to ~6 Tesseract passes per page
(amortized by the OCR cache). Hard limit: heavily stylized display/logo fonts (3D, metallic,
outlined) are at/beyond Tesseract's ability regardless of preprocessing — low confidence is
the signal.

## v0.2 changes (image input + engine v3)

Engine v3: `_preprocess_variants` now also emits an **alpha** variant for transparent images (uses the alpha channel directly as a black-on-white text mask — nails outlined/gradient logo PNGs). Scoring switched from 'sum of high-confidence words' to **readable mass** (sum of word length x confidence) so a full lower-confidence name beats a short high-confidence fragment. `_best_ocr` loops page-segmentation-mode-outer with an **early exit** once a confident read (mean conf >= 80, >=1 word) is found, bounding passes. New `ocr_image_file` / `diagnose_image_file` / `_load_image_file` handle loose image files; `_render_page` now returns the raw render and `_flatten_to_gray` is shared. `PageDiagnostic` gained `name` (image filename).

## v0.3 changes (coloured-logo readability: channel-minimum + psm 6 default)

The biggest real-world accuracy fix for opaque **coloured** logo lettering (gold / gradient
fills with a thin dark outline on a white background — extremely common on certificate and
title pages). Two changes:

- **`_min_channel(image)` + a new `colormin` variant.** Standard luminance grayscale
  (`0.299R+0.587G+0.114B`) maps a bright, saturated fill (gold, yellow, cyan, light green)
  to a value *near white*, so the letters collapse to **hollow outlines** and Tesseract
  reads gibberish (e.g. `CR ENTERPRISES` → `CR ENT EReRiSe`). Taking the per-pixel
  **`min(R,G,B)`** instead maps any saturated colour to a low (dark) value while leaving a
  white background near 255 — turning coloured text into **solid dark glyphs**. For neutral
  (gray) pixels `min == luminance`, so ordinary black-on-white scans are unchanged; the
  variant is skipped entirely for true-grayscale images (`mode in L/1/I/F`). Implemented
  numpy-free with `PIL.ImageChops.darker`, then Otsu-binarized — same deterministic pipeline
  as the other variants.
- **`DEFAULT_PSM` is now `6`** (a single uniform text block) with `3`/`4` as fallbacks (was
  `3` primary). For this tool's domain — sparse, centred title/logo pages — psm 3 (automatic)
  often returns *nothing* or stops after the first line, while psm 6 reads the whole
  multi-line block. Leading the rotation with psm 6 also makes the conf>=80 early-exit fire
  on a *complete* read instead of a high-confidence partial. The CLI/web/`RunConfig` defaults
  were updated to match (`--ocr-psm` default 6).

Measured on a 17-page gold-logo proof (`PROOF1.pdf`): dealership-name matches went from
**0/17 → 12/17** and owner-name from **2/17 → 11/17**; the only remaining misses are
genuinely stylized 3D/metallic *display* fonts (still beyond Tesseract — the documented hard
limit). Cost: `colormin` adds one more preprocessing pass per psm round on colour images
(skipped on grayscale), amortized by the OCR cache on re-runs.

