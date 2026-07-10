"""Optional, deterministic OCR fallback for PDF pages with no text layer.

ProofCheck's defining rule is **100% deterministic, no AI/LLM/ML, offline**. Classic
Tesseract OCR fits that rule: it is a fixed, offline glyph recogniser, not a learned
generative model, and the same image rendered the same way always yields the same text.

**Engine (tuned for accuracy + robustness).** Each page is rendered with pypdfium2, then
OCR is attempted with several deterministic *strategies* and the most confident result is
kept:

  * several preprocessings — grayscale + auto-contrast, Otsu **binarization** (clean
    black-on-white, which Tesseract reads best on noisy/low-contrast scans), an Otsu over
    the **channel-minimum** (``min(R,G,B)``) that turns *coloured* logo lettering — gold /
    gradient / outlined fills that luminance grayscale washes almost white — into solid
    dark glyphs, and (for transparent images) the alpha channel used directly as the text
    mask;
  * several page-segmentation modes — the default is **psm 6** (a single uniform text
    block), which reads multi-line title/logo pages whole; ``--ocr-psm`` overrides it and
    psm 3/4 are tried as fallbacks, important because automatic segmentation (psm 3)
    sometimes returns nothing on sparse, centred pages.

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
from collections.abc import Callable
from dataclasses import dataclass

# ---- Optional imports — the feature degrades gracefully when any are absent. -----
try:
    import pypdfium2 as _pdfium
except Exception:  # pragma: no cover - exercised only without the optional dep
    _pdfium = None

try:
    import pytesseract as _pytesseract
    from PIL import Image as _Image, ImageChops as _ImageChops, ImageOps as _ImageOps
except Exception:  # pragma: no cover - exercised only without the optional dep
    _pytesseract = None
    _Image = None
    _ImageChops = None
    _ImageOps = None


DEFAULT_DPI = 300        # 300 DPI is the conventional sweet spot for Tesseract accuracy.
DEFAULT_LANG = "eng"     # Tesseract language pack(s); e.g. "eng", "ara", "eng+ara".
DEFAULT_PSM = 6          # page segmentation: 6 = a single uniform block of text. For this
                         # tool's domain (no-text-layer pages: certificates, logo/title
                         # pages, simple scans) psm 6 reads multi-line blocks whole, whereas
                         # Tesseract's automatic mode (3) often returns nothing on sparse,
                         # centred pages or stops after the first line. 3/4 stay as fallbacks.
DEFAULT_OEM = 3          # OCR engine mode: 3 = default (LSTM neural engine).
# Page-segmentation modes to fall back to (after the requested one). 3 = fully automatic,
# 4 = variable-size columns: between them they rescue pages the primary mode misses.
_PSM_FALLBACKS = (3, 4)
_GOOD_CONF = 80          # a result this confident (with text) ends the strategy search early.
_ENOUGH_WORDS = 2        # after the primary psm round, this many words ends the search too
                         # (the fallback psm modes only help pages the primary read nothing on).
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
    name: str = ""                  # source label for the page (e.g. an image filename)


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


def _flatten_to_gray(image):
    """Flatten transparency onto white and return a grayscale ('L') image."""
    if image.mode not in ("L", "RGB"):
        rgba = image.convert("RGBA")
        background = _Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    return image.convert("L")


def _min_channel(image):
    """Per-pixel ``min(R, G, B)`` as a grayscale ('L') image, transparency flattened on white.

    Standard luminance grayscale (0.299R+0.587G+0.114B) makes bright, saturated fills — gold,
    yellow, cyan, light green — almost as light as a white background, so coloured *logo*
    lettering with a thin dark outline collapses to hollow outlines that Tesseract reads
    poorly. Taking the channel minimum instead maps any saturated colour to a low (dark)
    value while leaving white near 255, turning coloured text on a light background into
    solid dark glyphs. For neutral (gray) pixels min == the gray level, so ordinary
    black-on-white scans are unaffected. Deterministic and numpy-free.
    """
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        background = _Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    r, g, b = image.convert("RGB").split()
    return _ImageChops.darker(_ImageChops.darker(r, g), b)


def _render_page(document, page_index: int, *, dpi: int):
    """Render one PDF page to a PIL image (RGB on white; pdfium has no alpha)."""
    scale = dpi / _PDF_POINTS_PER_INCH
    return document[page_index].render(scale=scale).to_pil()


def _load_image_file(path: str):
    """Open an image file as a PIL image, preserving its mode (incl. any alpha channel)."""
    try:
        with _Image.open(path) as im:
            im.load()
            return im.copy()
    except Exception as exc:
        raise OcrError(f"Could not open image {os.path.basename(path)}: {exc}") from exc


def ocr_image_file(
    path: str,
    *,
    lang: str = DEFAULT_LANG,
    psm: int = DEFAULT_PSM,
    oem: int = DEFAULT_OEM,
) -> str:
    """OCR a single image file (PNG/JPG/TIFF/...). Returns the recovered text."""
    if not available():
        raise OcrError(unavailable_reason() or "OCR is unavailable.")
    text, _, _, _, _ = _best_ocr(_load_image_file(path), lang=lang, psm=psm, oem=oem)
    return text or ""


def diagnose_image_file(
    path: str,
    *,
    lang: str = DEFAULT_LANG,
    psm: int = DEFAULT_PSM,
    oem: int = DEFAULT_OEM,
    save_dir: str | None = None,
    page: int = 1,
) -> PageDiagnostic:
    """Diagnose OCR on one image file: best text + confidence + winning strategy."""
    if not available():
        raise OcrError(unavailable_reason() or "OCR is unavailable.")
    text, mean_conf, words, label, image_used = _best_ocr(
        _load_image_file(path), lang=lang, psm=psm, oem=oem
    )
    image_path = None
    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
        image_path = os.path.join(save_dir, f"page-{page}.png")
        image_used.save(image_path)
    return PageDiagnostic(
        page=page, text=text or "", mean_confidence=mean_conf, word_count=words,
        strategy=label, image_path=image_path, name=os.path.basename(path),
    )


def _preprocess_variants(image):
    """Deterministic preprocessings to try, as ``(name, image)`` pairs.

    'contrast' suits clean digital renders; 'binary' (Otsu) suits noisy/low-contrast scans;
    'colormin' (Otsu over the channel-minimum) rescues *coloured* lettering on a light
    background — gold/gradient/outlined logos that luminance grayscale would wash out to
    hollow outlines (see :func:`_min_channel`); 'alpha' uses a transparent image's alpha
    channel directly as the text mask — the cleanest possible input for logos/PNGs with a
    transparent background (e.g. gradient/outlined text), independent of the fill colour.
    """
    gray = _flatten_to_gray(image)
    contrast = _ImageOps.autocontrast(gray)
    # NB: compute the Otsu threshold ONCE and capture it; calling it inside the point()
    # lambda would re-scan the whole (multi-megapixel) histogram for all 256 LUT entries.
    contrast_thr = _otsu_threshold(contrast)
    binary = contrast.point(lambda p, t=contrast_thr: 255 if p > t else 0)
    variants = []

    # Coloured text on a light background: only meaningful when the image actually has
    # colour (channel min differs from luminance), so skip it for true grayscale scans.
    # Listed FIRST for colour images: it is the most likely winner for coloured/logo text,
    # so the per-pass confidence early-exit can stop after a single Tesseract pass.
    if image.mode not in ("L", "1", "I", "F"):
        mn = _min_channel(image)
        mn_thr = _otsu_threshold(mn)
        mn_binary = mn.point(lambda p, t=mn_thr: 255 if p > t else 0)
        variants.append(("colormin", mn_binary))

    variants += [("contrast", contrast), ("binary", binary)]

    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        alpha = image.convert("RGBA").split()[-1]
        lo, _hi = alpha.getextrema()
        if lo < 250:  # alpha actually varies (genuine transparency) -> usable text mask
            variants.append(("alpha", alpha.point(lambda a: 0 if a > 128 else 255)))
    return variants


def _data_to_result(data):
    """Reduce a pytesseract image_to_data dict to (text, mean_conf, word_count, mass)."""
    pairs = [
        (t.strip(), float(c))
        for t, c in zip(data.get("text", []), data.get("conf", []))
        if t and t.strip() and str(c) not in ("-1", "-1.0")
    ]
    words = [t for t, _ in pairs]
    confs = [c for _, c in pairs]
    text = " ".join(words)
    mean_conf = round(sum(confs) / len(confs), 1) if confs else 0.0
    # "Readable mass": characters weighted by confidence. Prefers substantial readable text
    # over a short high-confidence fragment, while still down-weighting low-confidence noise.
    mass = sum(len(w) * c for w, c in pairs)
    return text, mean_conf, len(words), mass


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
    variants = _preprocess_variants(image)

    best = None  # (mass, words, text, mean_conf, label, image)
    # Outer loop over page-segmentation modes so the requested (primary) mode is tried across
    # every preprocessing first; the fallback modes are only an escalation for pages the
    # primary mode read (almost) nothing on. Two deterministic stop conditions keep the
    # common case to a single psm round (one pass per variant) instead of the full product:
    #   * a confident read (conf >= _GOOD_CONF) in any round — clearly done;
    #   * after the primary round, ANY substantial read (>= _ENOUGH_WORDS words) — the
    #     fallback modes essentially never beat a primary mode that already produced real
    #     text, and re-running them on every page is what made OCR slow.
    confident = False
    for round_index, ps in enumerate(psms):
        for prep_name, prep_img in variants:
            cfg = f"--oem {int(oem)} --psm {int(ps)}"
            data = _pytesseract.image_to_data(prep_img, lang=lang, config=cfg, output_type=Output.DICT)
            text, mean_conf, words, mass = _data_to_result(data)
            cand = (mass, words, text, mean_conf, f"{prep_name}/psm{ps}", prep_img)
            if best is None or (cand[0], cand[1]) > (best[0], best[1]):
                best = cand
            if best[3] >= _GOOD_CONF and best[1] >= 1:
                confident = True
                break  # a confident read — stop immediately, even mid-round
        if confident:
            break
        if round_index == 0 and best is not None and best[1] >= _ENOUGH_WORDS:
            break  # primary mode already produced substantial text — fallbacks won't help
    _mass, words, text, mean_conf, label, image_used = best
    return text, mean_conf, words, label, image_used


def ocr_pages(
    path: str,
    page_numbers: list[int],
    *,
    dpi: int = DEFAULT_DPI,
    lang: str = DEFAULT_LANG,
    psm: int = DEFAULT_PSM,
    oem: int = DEFAULT_OEM,
    workers: int = 0,
    progress: Callable[[int, int], None] | None = None,
) -> dict[int, str]:
    """Render and OCR the given 1-based ``page_numbers`` of the PDF at ``path``.

    Returns ``{page_number: extracted_text}`` using the best of several deterministic OCR
    strategies per page. Raises :class:`OcrError` on any failure.

    ``workers`` controls parallelism (0 = auto, 1 = sequential). Pages are *rendered*
    sequentially in this thread — a single pdfium document is not safe to render from many
    threads at once — and then the slow part, Tesseract OCR, runs in parallel. To keep peak
    memory bounded we render and OCR in chunks of ``workers`` pages rather than rendering every
    page up front. Per-page results are pure, so output is identical to sequential. ``progress``
    is an optional ``(done, total)`` observer called as each page is OCR'd (``total`` counts the
    valid, in-range target pages), so a caller can render OCR progress.
    """
    from .concurrency import ordered_map, resolve_workers

    if not available():
        raise OcrError(unavailable_reason() or "OCR is unavailable.")

    out: dict[int, str] = {}
    try:
        document = _pdfium.PdfDocument(path)
    except Exception as exc:
        raise OcrError(f"Could not open PDF for OCR: {exc}") from exc

    try:
        page_count = len(document)
        targets = [p for p in page_numbers if 1 <= p <= page_count]
        total = len(targets)
        n_workers = resolve_workers(workers, total)
        done = 0

        def _ocr_rendered(item: tuple[int, object]) -> tuple[int, str]:
            page_number, image = item
            try:
                text, _, _, _, _ = _best_ocr(image, lang=lang, psm=psm, oem=oem)
            except Exception as exc:
                raise OcrError(f"OCR failed on page {page_number}: {exc}") from exc
            return page_number, text or ""

        # Chunk so at most ``n_workers`` rendered page images are held in memory at once.
        for start in range(0, total, max(1, n_workers)):
            chunk = targets[start:start + max(1, n_workers)]
            rendered: list[tuple[int, object]] = []
            for page_number in chunk:
                try:
                    rendered.append((page_number, _render_page(document, page_number - 1, dpi=dpi)))
                except Exception as exc:
                    raise OcrError(f"OCR failed on page {page_number}: {exc}") from exc
            for page_number, text in ordered_map(_ocr_rendered, rendered, workers=n_workers):
                out[page_number] = text
                done += 1
                if progress:
                    progress(done, total)
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
