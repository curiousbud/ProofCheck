# `proofcheck/images.py` — Explained

> Image-file input — OCR loose images (PNG/JPG/TIFF/…) as if each were a scanned page. A single image is a one-page document; a folder of images is a multi-page document (one page per image, sorted).

## Purpose
ProofCheck originally accepted only PDFs. This module lets the *same* run work on **images** — a single image file, or a whole **directory** of images — which is exactly what you have when names/labels were exported as individual pictures. Images never carry an embedded text layer, so this path always uses OCR. It returns the same `pdf.PdfText` the PDF path produces, so matching, the reports, and the "Matched via" column all work unchanged.

## Dependencies
- **External:** `os` only (PIL is used indirectly via `ocr`).
- **Internal:** `from .pdf import PdfText`; lazily `from . import ocr, ocr_cache` inside `extract`.
- **Used by:** `proofcheck/document.py` (the dispatcher) and the CLI (`check` / `ocr`).

## Functions
| Name | Signature | Description |
| --- | --- | --- |
| `is_image_file` | `(path) -> bool` | File with a supported image extension. |
| `is_image_dir` | `(path) -> bool` | Directory containing at least one image. |
| `is_image_input` | `(path) -> bool` | Either of the above. |
| `list_images` | `(path) -> list[str]` | The image(s): one file, or a directory's images **sorted** (deterministic page order). |
| `extract` | `(path, *, ocr_lang="eng", ocr_psm=3) -> PdfText` | OCR each image into a `PdfText`. |

## How `extract` works
- Gathers the image file(s); empty input → empty `PdfText`.
- If the OCR engine is unavailable, every image becomes an **empty page** and
  `ocr_unavailable_reason` is set (graceful — the run still completes, all values MISSING).
- Otherwise, for each image (1-based page index):
  - **Per-image content cache:** hash the image (`ocr_cache.file_sha256`, with `dpi=0` since
    images aren't rendered); a cache hit reuses the stored text (no re-OCR), a miss calls
    `ocr.ocr_image_file` and stores the result. So re-running over a folder only OCRs new/
    changed images.
  - The page is added to `ocr_pages` if it produced text, else to `empty_pages`.
- `ocr_from_cache` is set when every page was served from cache.

## Notes / gotchas
- **Sorted order** gives deterministic page numbers across runs/platforms.
- **Byte-identical images share a cache entry** (same content hash) — correct behavior, but
  surprising if you make throwaway identical test images.
- **OCR is mandatory** for images; install `proofcheck[ocr]` + the Tesseract binary. Quality
  depends on the artwork — verify with `proofcheck ocr <file-or-folder>`.
- Supported extensions: `.png .jpg .jpeg .tif .tiff .bmp .webp .gif`.
