# `proofcheck/document.py` — Explained

> The input dispatcher: extract page text from a **PDF or image input** behind one function, so the pipeline doesn't care which it was given.

## Purpose
`pipeline.run` shouldn't branch on input type. This thin module exposes `extract(path, …)`
that routes to the **image** OCR path (`images.extract`) for an image file or a folder of
images, and to the **PDF** path (`pdf.extract`) otherwise. Both return the same
`pdf.PdfText`, so everything downstream is identical.

## Dependencies
- **Internal:** `from . import images, pdf`; re-exports `PdfError`, `PdfText`.
- **Used by:** `proofcheck/pipeline.py` (calls `document.extract` instead of `pdf.extract`).

## Functions
| Name | Signature | Description |
| --- | --- | --- |
| `is_image_input` | `(path) -> bool` | True for an image file or a directory of images. |
| `extract` | `(path, *, ocr=False, ocr_dpi=300, ocr_lang="eng", ocr_psm=3) -> PdfText` | Route + extract. |

## Behavior
```python
if images.is_image_input(path):
    return images.extract(path, ocr_lang=ocr_lang, ocr_psm=ocr_psm)   # OCR implied
return pdf.extract(path, ocr=ocr, ocr_dpi=ocr_dpi, ocr_lang=ocr_lang, ocr_psm=ocr_psm)
```
- For **image input**, OCR is implied regardless of the `ocr` flag (images have no text layer),
  so `ocr_dpi` is irrelevant there.
- For **PDFs**, behavior is exactly as before: text layer + optional OCR fallback.

## Notes / gotchas
- This is a routing seam only — no business logic. Add new input kinds (e.g. a different
  container) here, keeping the `PdfText` return contract.
- The CLI also calls `images.is_image_input` directly to decide how to present the `ocr`
  diagnostics; the web layer validates the upload's extension against PDF + image types.
