"""Image-file input — OCR loose images (PNG/JPG/TIFF/…) as if each were a scanned page.

Images never have an embedded text layer, so this path always uses OCR. A single image
file is a one-page document; a **directory** of images is a multi-page document (one page
per image, in sorted filename order for deterministic page numbers). The result is the same
:class:`~proofcheck.pdf.PdfText` the PDF path produces, so everything downstream (matching,
reports, the "Matched via" column) works unchanged.

OCR results are cached per image (content hash), so re-running over a folder only OCRs the
images that are new or changed.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from .pdf import PdfText

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}


def is_image_file(path: str) -> bool:
    return os.path.isfile(path) and os.path.splitext(path)[1].lower() in IMAGE_EXTS


def is_image_dir(path: str) -> bool:
    """True for a directory that contains at least one supported image."""
    if not os.path.isdir(path):
        return False
    try:
        return any(os.path.splitext(f)[1].lower() in IMAGE_EXTS for f in os.listdir(path))
    except OSError:
        return False


def is_image_input(path: str) -> bool:
    return is_image_file(path) or is_image_dir(path)


def list_images(path: str) -> list[str]:
    """The image file(s) for ``path`` — a single file, or a directory's images sorted."""
    if os.path.isdir(path):
        return [
            os.path.join(path, f)
            for f in sorted(os.listdir(path))
            if os.path.splitext(f)[1].lower() in IMAGE_EXTS
        ]
    return [path] if is_image_file(path) else []


def extract(path: str, *, ocr_lang: str = "eng", ocr_psm: int = 6,
            use_cache: bool = True,
            progress: Callable[[int, int], None] | None = None) -> PdfText:
    """Build a :class:`PdfText` by OCR'ing the image(s) at ``path`` (file or directory).

    ``use_cache=False`` forces a fresh OCR of every image even if cached. ``progress`` is an
    optional ``(done, total)`` observer called after each image is processed.
    """
    from . import ocr as ocr_mod, ocr_cache

    result = PdfText()
    files = list_images(path)
    if not files:
        return result

    if not ocr_mod.available():
        # No engine: every image becomes an empty page with a clear reason.
        for i in range(1, len(files) + 1):
            result.pages[i] = ""
            result.empty_pages.append(i)
        result.ocr_unavailable_reason = ocr_mod.unavailable_reason()
        return result

    use_cache = use_cache and ocr_cache.enabled()
    total = len(files)
    all_cached = True
    for i, image_path in enumerate(files, start=1):
        digest = ocr_cache.file_sha256(image_path) if use_cache else None
        cached = ocr_cache.load(digest, dpi=0, lang=ocr_lang, psm=ocr_psm) if digest else None
        if cached is not None and 1 in cached:
            text = cached[1]
        else:
            all_cached = False
            try:
                text = ocr_mod.ocr_image_file(image_path, lang=ocr_lang, psm=ocr_psm)
            except ocr_mod.OcrError as exc:
                result.ocr_error = str(exc)
                text = ""
            if digest is not None:
                ocr_cache.store(digest, dpi=0, lang=ocr_lang, pages={1: text}, psm=ocr_psm)
        result.pages[i] = text
        if text.strip():
            result.ocr_pages.append(i)
        else:
            result.empty_pages.append(i)
        if progress:
            progress(i, total)

    result.ocr_from_cache = all_cached and bool(result.ocr_pages)
    return result
