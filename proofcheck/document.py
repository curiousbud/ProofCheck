"""Input dispatcher — extract page text from a PDF *or* image input.

``pipeline.run`` calls :func:`extract` instead of ``pdf.extract`` directly, so the same
run works whether the input is a PDF, a single image file, or a folder of images. PDFs use
the text layer (with optional OCR fallback); image inputs always go through OCR (they have
no text layer). Both return the same :class:`~proofcheck.pdf.PdfText`.
"""

from __future__ import annotations

from . import images, pdf
from .pdf import PdfError, PdfText


def is_image_input(path: str) -> bool:
    return images.is_image_input(path)


def extract(
    path: str,
    *,
    ocr: bool = False,
    ocr_dpi: int = 300,
    ocr_lang: str = "eng",
    ocr_psm: int = 3,
) -> PdfText:
    """Route to the image OCR path or the PDF path based on ``path``."""
    if images.is_image_input(path):
        # Images have no text layer, so OCR is implied regardless of the ``ocr`` flag.
        return images.extract(path, ocr_lang=ocr_lang, ocr_psm=ocr_psm)
    return pdf.extract(path, ocr=ocr, ocr_dpi=ocr_dpi, ocr_lang=ocr_lang, ocr_psm=ocr_psm)


__all__ = ["extract", "is_image_input", "PdfError", "PdfText"]
