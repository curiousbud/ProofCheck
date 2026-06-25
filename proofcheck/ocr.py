"""Optional, deterministic OCR fallback for PDF pages with no text layer.

ProofCheck's defining rule is **100% deterministic, no AI/LLM/ML, offline**. Classic
Tesseract OCR fits that rule: it is a fixed, offline glyph recogniser, not a learned
generative model, and the same image rendered the same way always yields the same text.

**Engine (tuned for accuracy + robustness).** Each page is rendered with pypdfium2, then
OCR is attempted with several deterministic *strategies* and the most confident result is
kept:

  * two preprocessings — grayscale + auto-contrast, and Otsu **binarization** (clean
    black-on-white, which Tesseract reads best on noisy/low-contrast scans);
  * several page-segmentation modes (the requested ``--ocr-psm`` plus a single-block
    fallback) — important because automatic segmentation (psm 3) sometimes returns nothing
    on sparse pages.

The winner is chosen by how much *confident* text it produced, so a page that one strategy
fails on is recovered by another. All of this is deterministic (a fixed strategy set + a
deterministic tie-break), preserving same-input-same-output.

**Limits.** Tesseract is trained on ordinary document fonts. Heavily stylized **display /
logo lettering** (3D, metallic/gradient, outlined, decorative) is at or beyond its limits —
no preprocessing reliably reads it. Use :func:`diagnose` / ``proofcheck ocr`` to see the
per-page text + confidence (and the image fed to OCR) so you can tell a fixable scan issue
(low DPI, rotation, noise → improvable) from genuinely un-OCR-able artwork.

Optional feature: rendering needs ``pypdfium2``; OCR needs ``pytesseract`` + ``Pillow`` plus
the Tesseract binary on PATH. When any is missing, OCR is unavailable and no-text-layer
pages stay warned + skipped. Install: ``pip install 'proofcheck[ocr]'`` + the engine binary.
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
# Page-segmentation modes to fall back to (after the requested one). 6 = single uniform
# block, 4 = variable-size columns: between them they rescue most pages psm 3 misses.
_PSM_FALLBACKS = (6, 4)
_CONFIDENT = 40          # word confidence (0-100) counted as "confident text" when scoring.
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
    text: str                       # the recovered text (best strategy)
    mean_confidence: float          # 0-100 average Tesseract word confidence (0 = nothing read)
    word_count: int                 # number of non-empty words recognised
    strategy: str = ""              # which preprocessing/psm won (e.g. "binary/psm6")
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


def _otsu_threshold(image) -> int:
    """Otsu's method: the grayscale threshold maximising between-class variance (no numpy)."""
    hist = image.histogram()[:256]
    total = sum(hist)
    if total == 0:
        return 127
    sum_total = sum(i * hist[i] for i in range(256))
    sum_b = 0.0
    w_b = 0
    var_max = -1.0
    threshold = 127
    for i in range(256):
        w_b += hist[i]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += i * hist[i]
        m_b = sum_b / w_b
        m_f = (sum_total - sum_b) / w_f
        between = w_b * w_f * (m_b - m_f) ** 2
        if between > var_max:
            var_max = between
            threshold = i
    return threshold


def _render_page(document, page_index: int, *, dpi: int):
    """Render one page to a grayscale PIL image (flatten transparency onto white)."""
    scale = dpi / _PDF_POINTS_PER_INCH
    bitmap = document[page_index].render(scale=scale)
    image = bitmap.to_pil()
    if image.mode not in ("L", "RGB"):
        rgba = image.convert("RGBA")
        background = _Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    return image.convert("L")


def _preprocess_variants(gray):
    """Deterministic preprocessings to try, as ``(name, image)`` pairs.

    'contrast' suits clean digital renders; 'binary' (Otsu) suits noisy/low-contrast scans.
    """
    contrast = _ImageOps.autocontrast(gray)
    threshold = _otsu_threshold(contrast)
    binary = contrast.point(lambda p: 255 if p > threshold else 0)
    return [("contrast", contrast), ("binary", binary)]


def _data_to_result(data):
    """Reduce a pytesseract image_to_data dict to (text, mean_conf, word_count, strong)."""
    confs = [float(c) for c in data.get("conf", []) if str(c) not in ("-1", "-1.0")]
    words = [w for w in data.get("text", []) if w and w.strip()]
    text = " ".join(words)
    mean_conf = round(sum(confs) / len(confs), 1) if confs else 0.0
    strong = sum(c for c in confs if c >= _CONFIDENT)  # amount of confident text
    return text, mean_conf, len(words), strong


def _best_ocr(image, *, lang: str, psm: int, oem: int):
    """Run several (preprocess, psm) strategies; return the most confident result.

    Returns ``(text, mean_confidence, word_count, strategy_label, image_used)``. Choosing by
    confident-text amount avoids the trap where psm 3 returns nothing yet reports high
    confidence. Deterministic: fixed strategy order, first-wins tie-break.
    """
    from pytesseract import Output

    psms: list[int] = []
    for p in (psm, *_PSM_FALLBACKS):
        if p not in psms:
            psms.append(p)

    best = None  # (strong, words, text, mean_conf, label, image)
    for prep_name, prep_img in _preprocess_variants(image):
        for ps in psms:
            cfg = f"--oem {int(oem)} --psm {int(ps)}"
            data = _pytesseract.image_to_data(prep_img, lang=lang, config=cfg, output_type=Output.DICT)
            text, mean_conf, words, strong = _data_to_result(data)
            cand = (strong, words, text, mean_conf, f"{prep_name}/psm{ps}", prep_img)
            if best is None or (cand[0], cand[1]) > (best[0], best[1]):
                best = cand
    _strong, words, text, mean_conf, label, image_used = best
    return text, mean_conf, words, label, image_used


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

    Returns ``{page_number: extracted_text}`` using the best of several deterministic OCR
    strategies per page. Raises :class:`OcrError` on any failure.
    """
    if not available():
        raise OcrError(unavailable_reason() or "OCR is unavailable.")

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
                text, _, _, _, _ = _best_ocr(image, lang=lang, psm=psm, oem=oem)
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
    """Run OCR with full diagnostics: best-strategy text + mean confidence per page.

    Optionally writes the exact (preprocessed) image fed to Tesseract for each page into
    ``save_dir`` as ``page-N.png`` so you can see what the engine saw. Raises
    :class:`OcrError` if OCR is unavailable.
    """
    if not available():
        raise OcrError(unavailable_reason() or "OCR is unavailable.")

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
            text, mean_conf, words, label, image_used = _best_ocr(
                image, lang=lang, psm=psm, oem=oem
            )
            image_path = None
            if save_dir:
                image_path = os.path.join(save_dir, f"page-{page_number}.png")
                image_used.save(image_path)
            results.append(PageDiagnostic(
                page=page_number, text=text or "", mean_confidence=mean_conf,
                word_count=words, strategy=label, image_path=image_path,
            ))
    finally:
        document.close()

    return results
