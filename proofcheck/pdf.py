"""PDF text extraction with an optional, deterministic OCR fallback.

The primary path pulls each page's embedded text layer — fully deterministic, no
guessing. Pages with no extractable text (scanned/image-only) are reported so the
caller can warn and skip them.

**Engine.** Text is extracted with **PDFium** (via ``pypdfium2`` — Google's Chrome PDF
engine), which is dramatically faster than pdfminer/pdfplumber on image-heavy PDFs: a
scanned 150-page file whose pages carry only a thin text layer drops from ~7.6 s/page to
~0.15 s/page (~50x), because PDFium doesn't crawl every embedded image just to recover a
few characters. ``pdfplumber`` (pdfminer) is kept as an automatic fallback for when PDFium
isn't importable, and can be forced with ``PROOFCHECK_PDF_ENGINE=pdfplumber``. Both read the
same embedded text layer, so results are equivalent and deterministic either way.

When ``ocr=True`` those no-text-layer pages are handed to :mod:`proofcheck.ocr`, which
renders and runs Tesseract over them. OCR is optional and deterministic (same image +
DPI -> same text); if the OCR libraries/engine are missing the pages stay warned +
skipped exactly as before. We still never *guess* — OCR only recovers real glyphs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:  # PDFium is the fast primary engine; pdfplumber is the fallback below.
    import pypdfium2 as _pdfium
except Exception:  # pragma: no cover - exercised only without the optional dep
    _pdfium = None


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


def _normalize_newlines(text: str) -> str:
    """Fold CRLF/CR to LF so snippets are consistent across engines (PDFium emits CRLF)."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _extract_pages_pdfium(path: str) -> dict[int, str]:
    """Extract the text layer of every page with PDFium. Fast, and robust on image-heavy PDFs."""
    out: dict[int, str] = {}
    document = _pdfium.PdfDocument(path)
    try:
        for i in range(len(document)):
            page = document[i]
            textpage = page.get_textpage()
            try:
                text = textpage.get_text_range() or ""
            finally:
                textpage.close()
                page.close()
            out[i + 1] = _normalize_newlines(text)
    finally:
        document.close()
    return out


def _extract_pages_pdfplumber(path: str) -> dict[int, str]:
    """Extract the text layer of every page with pdfplumber (pdfminer). The fallback engine."""
    import pdfplumber

    out: dict[int, str] = {}
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            out[i] = _normalize_newlines(page.extract_text() or "")
    return out


def _resolve_engine() -> str:
    """Pick the text-extraction engine: PROOFCHECK_PDF_ENGINE override, else auto (PDFium first)."""
    choice = (os.environ.get("PROOFCHECK_PDF_ENGINE") or "auto").strip().lower()
    if choice == "pdfplumber":
        return "pdfplumber"
    if choice == "pdfium":
        return "pdfium"
    # auto: PDFium when available (much faster), otherwise pdfplumber.
    return "pdfium" if _pdfium is not None else "pdfplumber"


def extract(
    path: str,
    *,
    ocr: bool = False,
    ocr_dpi: int = 300,
    ocr_lang: str = "eng",
    ocr_psm: int = 6,
    use_cache: bool = True,
) -> PdfText:
    """Extract text from every page of the PDF at ``path``.

    Uses PDFium by default (fast; see the module docstring) and falls back to pdfplumber when
    PDFium isn't available or is explicitly disabled via ``PROOFCHECK_PDF_ENGINE=pdfplumber``.
    With ``ocr=True``, pages that have no embedded text layer are OCR'd as a fallback (when the
    optional OCR support is installed); otherwise they are reported as empty. ``use_cache=False``
    forces a fresh OCR even if a cached result exists.
    """
    engine = _resolve_engine()
    try:
        if engine == "pdfium":
            pages = _extract_pages_pdfium(path)
        else:
            pages = _extract_pages_pdfplumber(path)
    except Exception as exc:
        # If PDFium chokes on an unusual file, retry once with pdfplumber before giving up.
        if engine == "pdfium":
            try:
                pages = _extract_pages_pdfplumber(path)
            except Exception as fallback_exc:
                raise PdfError(f"Could not read PDF file: {fallback_exc}") from fallback_exc
        else:
            raise PdfError(f"Could not read PDF file: {exc}") from exc

    result = PdfText()
    for i, text in pages.items():
        result.pages[i] = text
        if not text.strip():
            result.empty_pages.append(i)

    if ocr and result.empty_pages:
        _apply_ocr(result, path, dpi=ocr_dpi, lang=ocr_lang, psm=ocr_psm, use_cache=use_cache)

    return result


def _apply_ocr(result: PdfText, path: str, *, dpi: int, lang: str, psm: int = 6,
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
