"""Optional, deterministic OCR fallback for PDF pages with no text layer.

ProofCheck's defining rule is **100% deterministic, no AI/LLM/ML, offline**. Classic
Tesseract OCR fits that rule: it is a fixed, offline glyph recogniser, not a learned
generative model, and the same image rendered at the same DPI always yields the same
text. So OCR is a *recovery* step for scanned/image-only pages, not a guess.

**Engine tuning (for accuracy).** Pages are rendered with pypdfium2 and then preprocessed
deterministically before Tesseract sees them: flattened onto a white background, converted
to **grayscale**, and **auto-contrasted** — the clean, high-contrast input Tesseract works
best on. Recognition uses the LSTM engine (``--oem 3``) and a configurable page-segmentation
mode (``--psm``, default 3 = automatic). Raise the DPI for small text.

**Diagnostics.** Use :func:`diagnose` (or ``proofcheck ocr FILE``) to see exactly what OCR
extracted per page, the mean word **confidence**, and optionally the rendered images that
were fed to Tesseract — the fastest way to tell whether OCR is reading a page correctly.

It is an **optional feature**: rendering needs ``pypdfium2`` and OCR needs ``pytesseract`` +
``Pillow`` plus the Tesseract engine binary on ``PATH``. When any is missing, OCR is simply
unavailable and pages without a text layer stay warned + skipped. Install with
``pip install 'proofcheck[ocr]'`` plus the Tesseract binary from your OS package manager.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

# ---- Optional imports — the feature degrades gracefully when any are absent. -----
try:
    import pypdfium2 as _pdfium
except Exception:  # pragma: no cover - exercised only without the optional dep
    _pdfium = None

try:
    import pytesseract as _pytesseract
    from PIL import Image as _Image, ImageOps as _ImageOps
except Exception:  # pragma: no cover - exercised only without the optional dep
    _pytesseract = None
    _Image = None
    _ImageOps = None


DEFAULT_DPI = 300        # 300 DPI is the conventional sweet spot for Tesseract accuracy.
DEFAULT_LANG = "eng"     # Tesseract language pack(s); e.g. "eng", "ara", "eng+ara".
DEFAULT_PSM = 3          # page segmentation: 3 = fully automatic (Tesseract's default).
DEFAULT_OEM = 3          # OCR engine mode: 3 = default (LSTM neural engine).
_PDF_POINTS_PER_INCH = 72.0

# Common locations the Tesseract engine lands in when it isn't on PATH (notably the
# Windows installer, whose PATH update doesn't reach an already-running shell).
_FALLBACK_TESSERACT_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
)


class OcrError(Exception):
    """Raised for user-facing OCR problems (bad render, engine failure)."""


@dataclass
class PageDiagnostic:
    """What OCR produced for one page — for inspecting/verifying OCR quality."""

    page: int                       # 1-based page number
    text: str                       # the recovered text
    mean_confidence: float          # 0-100 average Tesseract word confidence (0 = nothing read)
    word_count: int                 # number of non-empty words recognised
    has_text_layer: bool = False    # True if the page already had embedded text (OCR not needed)
    image_path: str | None = None   # where the rendered page image was saved (if requested)


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
    return _pdfium is not None and _Image is not None and tesseract_available()


def unavailable_reason() -> str | None:
    """Human-readable reason OCR can't run, or ``None`` when it can."""
    if _pdfium is None:
        return "PDF rendering library 'pypdfium2' is not installed (pip install 'proofcheck[ocr]')."
    if _pytesseract is None or _Image is None:
        return "'pytesseract'/'Pillow' are not installed (pip install 'proofcheck[ocr]')."
    if not tesseract_available():
        return "the Tesseract OCR engine binary was not found on PATH (install it from your OS package manager)."
    return None


def version() -> str | None:
    """Tesseract engine version string, or ``None`` if unavailable (diagnostics)."""
    if not tesseract_available():
        return None
    try:
        return str(_pytesseract.get_tesseract_version())
    except Exception:
        return None


def _tess_config(psm: int, oem: int) -> str:
    return f"--oem {int(oem)} --psm {int(psm)}"


def _render_page(document, page_index: int, *, dpi: int):
    """Render one page to a clean grayscale PIL image tuned for OCR.

    Deterministic preprocessing: flatten any transparency onto white, convert to grayscale,
    and auto-contrast. This is the high-contrast input Tesseract reads most reliably.
    """
    scale = dpi / _PDF_POINTS_PER_INCH
    bitmap = document[page_index].render(scale=scale)
    image = bitmap.to_pil()
    if image.mode not in ("L", "RGB"):
        # Flatten alpha/palette onto white so text isn't OCR'd on a transparent background.
        rgba = image.convert("RGBA")
        background = _Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    image = image.convert("L")              # grayscale: Tesseract's preferred input
    image = _ImageOps.autocontrast(image)   # normalize faded/low-contrast scans (deterministic)
    return image


def ocr_pages(
    path: str,
    page_numbers: list[int],
    *,
    dpi: int = DEFAULT_DPI,
    lang: str = DEFAULT_LANG,
    psm: int = DEFAULT_PSM,
    oem: int = DEFAULT_OEM,
) -> dict[int, str]:
    """Render and OCR the given 1-based ``page_numbers`` of the PDF at ``path``.

    Returns ``{page_number: extracted_text}``. Deterministic: a fixed render scale,
    deterministic preprocessing, and Tesseract's default (non-stochastic) engine mean
    identical inputs yield identical text. Raises :class:`OcrError` on any failure.
    """
    if not available():
        raise OcrError(unavailable_reason() or "OCR is unavailable.")

    config = _tess_config(psm, oem)
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
                image = _render_page(document, page_number - 1, dpi=dpi)
                text = _pytesseract.image_to_string(image, lang=lang, config=config)
            except Exception as exc:
                raise OcrError(f"OCR failed on page {page_number}: {exc}") from exc
            out[page_number] = text or ""
    finally:
        document.close()

    return out


def diagnose(
    path: str,
    page_numbers: list[int],
    *,
    dpi: int = DEFAULT_DPI,
    lang: str = DEFAULT_LANG,
    psm: int = DEFAULT_PSM,
    oem: int = DEFAULT_OEM,
    save_dir: str | None = None,
) -> list[PageDiagnostic]:
    """Run OCR with full diagnostics: recovered text + mean confidence per page.

    Optionally writes the exact image fed to Tesseract for each page into ``save_dir`` (as
    ``page-N.png``) so you can see what the engine saw. Raises :class:`OcrError` if OCR is
    unavailable.
    """
    if not available():
        raise OcrError(unavailable_reason() or "OCR is unavailable.")

    from pytesseract import Output

    config = _tess_config(psm, oem)
    results: list[PageDiagnostic] = []
    if save_dir:
        os.makedirs(save_dir, exist_ok=True)

    document = _pdfium.PdfDocument(path)
    try:
        page_count = len(document)
        for page_number in page_numbers:
            if page_number < 1 or page_number > page_count:
                continue
            image = _render_page(document, page_number - 1, dpi=dpi)
            text = _pytesseract.image_to_string(image, lang=lang, config=config)
            data = _pytesseract.image_to_data(image, lang=lang, config=config, output_type=Output.DICT)
            confs = [float(c) for c in data.get("conf", []) if str(c) not in ("-1", "-1.0")]
            words = [w for w in data.get("text", []) if w and w.strip()]
            mean_conf = round(sum(confs) / len(confs), 1) if confs else 0.0
            image_path = None
            if save_dir:
                image_path = os.path.join(save_dir, f"page-{page_number}.png")
                image.save(image_path)
            results.append(PageDiagnostic(
                page=page_number, text=text or "", mean_confidence=mean_conf,
                word_count=len(words), image_path=image_path,
            ))
    finally:
        document.close()

    return results
