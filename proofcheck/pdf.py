"""PDF text-layer extraction (pdfplumber).

Pulls the embedded text layer of each page. Pages with no extractable text
(scanned images needing OCR) are reported so the caller can warn and skip them.
This stays fully deterministic — we never OCR or guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pdfplumber


class PdfError(Exception):
    """Raised for user-facing PDF problems (unreadable/corrupt file)."""


@dataclass
class PdfText:
    """Extracted PDF text, page by page."""

    # 1-based page number -> extracted text (already whitespace-joined by pdfplumber).
    pages: dict[int, str] = field(default_factory=dict)
    # 1-based page numbers that had no extractable text layer.
    empty_pages: list[int] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def warnings(self) -> list[str]:
        return [
            f"Page {p} has no text layer — OCR required, skipped."
            for p in self.empty_pages
        ]


def extract(path: str) -> PdfText:
    """Extract text from every page of the PDF at ``path``."""
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
    return result
