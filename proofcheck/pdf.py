"""PDF text extraction (pdfplumber) with an optional, deterministic OCR fallback.

The primary path pulls each page's embedded text layer — fully deterministic, no
guessing. Pages with no extractable text (scanned/image-only) are reported so the
caller can warn and skip them.

When ``ocr=True`` those no-text-layer pages are handed to :mod:`proofcheck.ocr`, which
renders and runs Tesseract over them. OCR is optional and deterministic (same image +
DPI -> same text); if the OCR libraries/engine are missing the pages stay warned +
skipped exactly as before. We still never *guess* — OCR only recovers real glyphs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pdfplumber


class PdfError(Exception):
    """Raised for user-facing PDF problems (unreadable/corrupt file)."""


@dataclass
class PdfText:
    """Extracted PDF text, page by page."""

    # 1-based page number -> extracted text (already whitespace-joined by pdfplumber,
    # or recovered via OCR when that page had no text layer and OCR was enabled).
    pages: dict[int, str] = field(default_factory=dict)
    # 1-based page numbers that still have no usable text (after any OCR attempt).
    empty_pages: list[int] = field(default_factory=list)
    # 1-based page numbers whose text was recovered via OCR.
    ocr_pages: list[int] = field(default_factory=list)
    # True when the OCR text was reused from cache (identical file seen before).
    ocr_from_cache: bool = False
    # Set when OCR was requested but the engine/libraries were unavailable.
    ocr_unavailable_reason: str | None = None
    # Set when OCR was attempted but failed.
    ocr_error: str | None = None

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def warnings(self) -> list[str]:
        msgs: list[str] = []
        if self.ocr_unavailable_reason:
            msgs.append(
                "OCR was requested but is unavailable: " + self.ocr_unavailable_reason
            )
        if self.ocr_error:
            msgs.append("OCR error: " + self.ocr_error)
        for p in self.ocr_pages:
            if self.ocr_from_cache:
                msgs.append(
                    f"Page {p} had no text layer - reused OCR text from an earlier run of "
                    f"this identical file (file unchanged, so OCR was skipped)."
                )
            else:
                msgs.append(f"Page {p} had no text layer - text recovered via OCR.")
        for p in self.empty_pages:
            msgs.append(f"Page {p} has no text layer - OCR required, skipped.")
        return msgs


def extract(
    path: str,
    *,
    ocr: bool = False,
    ocr_dpi: int = 300,
    ocr_lang: str = "eng",
    ocr_psm: int = 3,
    use_cache: bool = True,
) -> PdfText:
    """Extract text from every page of the PDF at ``path``.

    With ``ocr=True``, pages that have no embedded text layer are OCR'd as a fallback
    (when the optional OCR support is installed); otherwise they are reported as empty.
    ``use_cache=False`` forces a fresh OCR even if a cached result exists.
    """
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

    if ocr and result.empty_pages:
        _apply_ocr(result, path, dpi=ocr_dpi, lang=ocr_lang, psm=ocr_psm, use_cache=use_cache)

    return result


def _apply_ocr(result: PdfText, path: str, *, dpi: int, lang: str, psm: int = 3,
               use_cache: bool = True) -> None:
    """Recover no-text-layer pages via OCR, mutating ``result`` in place.

    Uses the content-addressed OCR cache first: an identical file (same bytes, dpi, lang)
    reuses its previous OCR text with no re-OCR — and doesn't even need the engine. Only a
    new/changed file (different content hash) is OCR'd fresh, then cached.

    Never raises: any unavailability/failure is recorded on the result as a warning so a
    run still completes deterministically on whatever text could be extracted.
    """
    from . import ocr as ocr_mod, ocr_cache

    use_cache = use_cache and ocr_cache.enabled()
    digest = ocr_cache.file_sha256(path) if use_cache else None
    recovered = ocr_cache.load(digest, dpi=dpi, lang=lang, psm=psm) if use_cache else None

    if recovered is not None:
        result.ocr_from_cache = True  # cache hit: unchanged file, skip OCR entirely
    else:
        if not ocr_mod.available():
            result.ocr_unavailable_reason = ocr_mod.unavailable_reason()
            return
        try:
            recovered = ocr_mod.ocr_pages(path, list(result.empty_pages), dpi=dpi, lang=lang, psm=psm)
        except ocr_mod.OcrError as exc:
            result.ocr_error = str(exc)
            return
        if use_cache and digest is not None:
            ocr_cache.store(digest, dpi=dpi, lang=lang, pages=recovered, psm=psm)

    still_empty: list[int] = []
    for p in result.empty_pages:
        text = recovered.get(p, "")
        if text.strip():
            result.pages[p] = text
            result.ocr_pages.append(p)
        else:
            still_empty.append(p)
    result.empty_pages = still_empty
