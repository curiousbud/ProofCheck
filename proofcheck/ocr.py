"""Optional, deterministic OCR fallback for PDF pages with no text layer.

ProofCheck's defining rule is **100% deterministic, no AI/LLM/ML, offline**. Classic
Tesseract OCR fits that rule: it is a fixed, offline glyph recogniser, not a learned
generative model, and the same image rendered at the same DPI always yields the same
text. So OCR is a *recovery* step for scanned/image-only pages, not a guess.

It is an **optional feature**. Rendering needs ``pypdfium2`` (a pure-wheel dependency,
no system binary) and OCR needs ``pytesseract`` + ``Pillow`` plus the Tesseract engine
binary on ``PATH``. When any of those is missing, OCR is simply unavailable and pages
without a text layer stay warned + skipped, exactly as before. Install the engine and
the Python helpers with ``pip install 'proofcheck[ocr]'`` (and the Tesseract binary
from your OS package manager).
"""

from __future__ import annotations

import os
import shutil

# ---- Optional imports — the feature degrades gracefully when any are absent. -----
try:
    import pypdfium2 as _pdfium
except Exception:  # pragma: no cover - exercised only without the optional dep
    _pdfium = None

try:
    import pytesseract as _pytesseract
except Exception:  # pragma: no cover - exercised only without the optional dep
    _pytesseract = None


# Common locations the Tesseract engine lands in when it isn't on PATH (notably the
# Windows installer, whose PATH update doesn't reach an already-running shell).
_FALLBACK_TESSERACT_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
)


def _configure_tesseract_cmd() -> None:
    """Point pytesseract at the engine when it isn't resolvable on PATH.

    Honors a ``TESSERACT_CMD`` override, else probes well-known install locations. This
    keeps OCR working right after a fresh install without needing a new shell. No-op when
    pytesseract is absent or the binary is already on PATH.
    """
    if _pytesseract is None:
        return
    override = os.environ.get("TESSERACT_CMD")
    if override and os.path.isfile(override):
        _pytesseract.pytesseract.tesseract_cmd = override
        return
    if shutil.which(_pytesseract.pytesseract.tesseract_cmd) or shutil.which("tesseract"):
        return  # already resolvable — leave the default alone
    for candidate in _FALLBACK_TESSERACT_PATHS:
        if os.path.isfile(candidate):
            _pytesseract.pytesseract.tesseract_cmd = candidate
            return


_configure_tesseract_cmd()


DEFAULT_DPI = 300        # 300 DPI is the conventional sweet spot for Tesseract accuracy.
DEFAULT_LANG = "eng"     # Tesseract language pack(s); e.g. "eng", "ara", "eng+ara".
_PDF_POINTS_PER_INCH = 72.0


class OcrError(Exception):
    """Raised for user-facing OCR problems (bad render, engine failure)."""


def tesseract_available() -> bool:
    """True when pytesseract is importable *and* the Tesseract binary is callable."""
    if _pytesseract is None:
        return False
    try:
        _pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def available() -> bool:
    """True when both the renderer and a usable Tesseract engine are present."""
    return _pdfium is not None and tesseract_available()


def unavailable_reason() -> str | None:
    """Human-readable reason OCR can't run, or ``None`` when it can."""
    if _pdfium is None:
        return "PDF rendering library 'pypdfium2' is not installed (pip install 'proofcheck[ocr]')."
    if _pytesseract is None:
        return "'pytesseract'/'Pillow' are not installed (pip install 'proofcheck[ocr]')."
    if not tesseract_available():
        return "the Tesseract OCR engine binary was not found on PATH (install it from your OS package manager)."
    return None


def ocr_pages(
    path: str,
    page_numbers: list[int],
    *,
    dpi: int = DEFAULT_DPI,
    lang: str = DEFAULT_LANG,
) -> dict[int, str]:
    """Render and OCR the given 1-based ``page_numbers`` of the PDF at ``path``.

    Returns ``{page_number: extracted_text}``. Deterministic: a fixed render scale and
    Tesseract's default (non-stochastic) engine mean identical inputs yield identical
    text. Raises :class:`OcrError` if OCR is unavailable or a page cannot be processed.
    """
    if not available():
        raise OcrError(unavailable_reason() or "OCR is unavailable.")

    scale = dpi / _PDF_POINTS_PER_INCH
    out: dict[int, str] = {}
    try:
        document = _pdfium.PdfDocument(path)
    except Exception as exc:
        raise OcrError(f"Could not open PDF for OCR: {exc}") from exc

    try:
        page_count = len(document)
        for page_number in page_numbers:
            if page_number < 1 or page_number > page_count:
                continue
            try:
                page = document[page_number - 1]
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()
                text = _pytesseract.image_to_string(image, lang=lang)
            except Exception as exc:
                raise OcrError(f"OCR failed on page {page_number}: {exc}") from exc
            out[page_number] = text or ""
    finally:
        document.close()

    return out
