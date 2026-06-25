"""Core data structures for ProofCheck.
These dataclasses are the **stable internal contract**. The pipeline produces a
``RunResult``; CLI report writers and the web JSON layer both consume it without
re-deriving anything. Keep these deterministic and free of any presentation
concerns (no HTML, no colors) so every client can render them its own way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Status(str, Enum):
    """Outcome of matching a single expected value against the PDF."""

    EXACT = "EXACT"      # found verbatim (after normalization)
    FUZZY = "FUZZY"      # found a close match at/above the fuzzy threshold
    MISSING = "MISSING"  # no match at/above the threshold
    SKIPPED = "SKIPPED"  # nothing to check (blank cell)


# A single diff operation: (op, text) where op is one of equal|insert|delete|replace.
# Diffs describe how to turn ``expected`` into ``best_match``:
#   equal  -> text is unchanged
#   delete -> text is present in expected but absent from the match
#   insert -> text is present in the match but absent from expected
#   replace-> reserved (the matcher decomposes replacements into delete+insert)
DiffOp = tuple[str, str]


@dataclass
class MatchResult:
    """Result of checking one spreadsheet cell against the PDF."""

    row: int                      # 1-based spreadsheet row of the value
    expected: str                 # the original cell value
    status: Status
    page: int | None = None       # 1-based PDF page where the (best) match was found
    best_match: str | None = None # the closest snippet found in the PDF
    score: int = 0                # fuzzy score 0-100 (100 for EXACT)
    diff: list[DiffOp] = field(default_factory=list)


@dataclass
class ColumnResult:
    """All match results for a single spreadsheet column."""

    name: str
    results: list[MatchResult] = field(default_factory=list)


@dataclass
class RunConfig:
    """Everything needed to perform one check run.

    ``columns`` lists the column headers to check. When ``all_columns`` is True
    the pipeline checks every column found on the sheet and ``columns`` is ignored.
    """

    excel_path: str
    pdf_path: str
    columns: list[str] = field(default_factory=list)
    all_columns: bool = False
    sheet: str | None = None          # None -> first/active sheet
    header_row: int = 1               # 1-based row containing column headers
    fuzzy_threshold: int = 90         # 0-100; >= this score counts as FUZZY
    normalize_digits: bool = False    # fold Arabic-Indic & other unicode digits to ASCII
    strip_punctuation: bool = False   # drop punctuation before comparing
    fold_diacritics: bool = False     # fold accents/diacritics (café -> cafe) before comparing
    reverse: bool = False             # also try reversed word order (e.g. "Last First")
    ocr: bool = False                 # OCR no-text-layer pages as a fallback (deterministic Tesseract)
    ocr_dpi: int = 300                # render DPI for OCR (higher = slower, more accurate)
    ocr_lang: str = "eng"             # Tesseract language pack(s), e.g. "eng" or "eng+ara"


@dataclass
class Summary:
    """Aggregate counts across every checked value."""

    total: int = 0
    exact: int = 0
    fuzzy: int = 0
    missing: int = 0
    skipped: int = 0
    pass_rate: float = 0.0  # (exact + fuzzy) / checked, rounded to 4 dp; checked excludes skipped


@dataclass
class Meta:
    """Provenance / configuration echo for a run."""

    excel: str
    pdf: str
    timestamp: str
    fuzzy_threshold: int
    flags: dict[str, bool]

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


@dataclass
class RunResult:
    """Complete, self-describing result of a check run."""

    meta: Meta
    summary: Summary
    columns: list[ColumnResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
