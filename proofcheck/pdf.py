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
            msgs.append(f"Page {p} had no text layer — text recovered via OCR.")
        for p in self.empty_pages:
            msgs.append(f"Page {p} has no text layer — OCR required, skipped.")
        return msgs


def extract(
    path: str,
    *,
    ocr: bool = False,
    ocr_dpi: int = 300,
    ocr_lang: str = "eng",
) -> PdfText:
    """Extract text from every page of the PDF at ``path``.

    With ``ocr=True``, pages that have no embedded text layer are OCR'd as a fallback
    (when the optional OCR support is installed); otherwise they are reported as empty.
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
        _apply_ocr(result, path, dpi=ocr_dpi, lang=ocr_lang)

    return result


def _apply_ocr(result: PdfText, path: str, *, dpi: int, lang: str) -> None:
    """Recover no-text-layer pages via OCR, mutating ``result`` in place.

    Never raises: any unavailability/failure is recorded on the result as a warning so a
    run still completes deterministically on whatever text could be extracted.
    """
    from . import ocr as ocr_mod

    if not ocr_mod.available():
        result.ocr_unavailable_reason = ocr_mod.unavailable_reason()
        return

    try:
        recovered = ocr_mod.ocr_pages(path, list(result.empty_pages), dpi=dpi, lang=lang)
    except ocr_mod.OcrError as exc:
        result.ocr_error = str(exc)
        return

    still_empty: list[int] = []
    for p in result.empty_pages:
        text = recovered.get(p, "")
        if text.strip():
            result.pages[p] = text
            result.ocr_pages.append(p)
        else:
            still_empty.append(p)
    result.empty_pages = still_empty
