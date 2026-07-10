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
            use_cache: bool = True, workers: int = 0,
            progress: Callable[[int, int], None] | None = None) -> PdfText:
    """Build a :class:`PdfText` by OCR'ing the image(s) at ``path`` (file or directory).

    ``use_cache=False`` forces a fresh OCR of every image even if cached. ``workers`` controls
    how many images are OCR'd in parallel (0 = auto, 1 = sequential); each image is an
    independent page, so results are reassembled in filename order and are identical to the
    sequential path. ``progress`` is an optional ``(done, total)`` observer called as each image
    is processed.
    """
    from . import ocr as ocr_mod, ocr_cache
    from .concurrency import ordered_map, resolve_workers

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

    def _process(item: tuple[int, str]) -> tuple[int, str, bool, str | None]:
        """OCR one image (or reuse its cache). Pure per-image → safe to run concurrently.

        Returns ``(page_index, text, from_cache, error)``; the caller folds these into the
        shared result in order so the parallel path stays deterministic.
        """
        i, image_path = item
        digest = ocr_cache.file_sha256(image_path) if use_cache else None
        cached = ocr_cache.load(digest, dpi=0, lang=ocr_lang, psm=ocr_psm) if digest else None
        if cached is not None and 1 in cached:
            return i, cached[1], True, None
        error: str | None = None
        try:
            text = ocr_mod.ocr_image_file(image_path, lang=ocr_lang, psm=ocr_psm)
        except ocr_mod.OcrError as exc:
            error = str(exc)
            text = ""
        if digest is not None:
            ocr_cache.store(digest, dpi=0, lang=ocr_lang, pages={1: text}, psm=ocr_psm)
        return i, text, False, error

    items = list(enumerate(files, start=1))
    total = len(items)
    n_workers = resolve_workers(workers, total)

    all_cached = True
    done = 0
    for i, text, from_cache, error in ordered_map(_process, items, workers=n_workers):
        if error is not None:
            result.ocr_error = error
        if not from_cache:
            all_cached = False
        result.pages[i] = text
        if text.strip():
            result.ocr_pages.append(i)
        else:
            result.empty_pages.append(i)
        done += 1
        if progress:
            progress(done, total)

    result.ocr_from_cache = all_cached and bool(result.ocr_pages)
    return result
