"""Plain-language presentation helpers shared by the HTML and xlsx reports.

The data contract keeps the terse machine statuses (``EXACT``/``FUZZY``/``MISSING``/
``SKIPPED``) and numeric scores. Non-technical readers find those confusing, so this module
turns them into ordinary English: "Found", "Found with differences", "Not found", "Blank",
plus a one-sentence overview and a per-row explanation of where each value was (or wasn't)
found. Presentation only — it has no effect on matching and doesn't change the API.
"""

from __future__ import annotations

from .models import MatchResult, RunResult, Status

# status -> (friendly label, icon, one-line meaning)
LABELS: dict[Status, tuple[str, str, str]] = {
    Status.EXACT:   ("Found", "✓",
                     "Found in the PDF exactly."),
    Status.FUZZY:   ("Found with differences", "≈",
                     "Found in the PDF, but the text isn't an exact match — check the differences."),
    Status.MISSING: ("Not found", "✗",
                     "This value could not be found in the PDF."),
    Status.SKIPPED: ("Blank", "–",
                     "The spreadsheet cell was empty, so there was nothing to check."),
}


def label(status: Status) -> str:
    return LABELS[status][0]


def icon(status: Status) -> str:
    return LABELS[status][1]


def meaning(status: Status) -> str:
    return LABELS[status][2]


def summary_sentence(result: RunResult) -> str:
    """A single plain-English overview of the whole run."""
    s = result.summary
    checked = s.total - s.skipped
    parts: list[str] = []
    if s.exact:
        parts.append(f"{s.exact} found")
    if s.fuzzy:
        parts.append(f"{s.fuzzy} found with small differences")
    if s.missing:
        parts.append(f"{s.missing} not found")
    body = "; ".join(parts) if parts else "nothing needed checking"
    plural = "s" if checked != 1 else ""
    sentence = (
        f"We checked {checked} value{plural} from your spreadsheet against the PDF: {body}."
    )
    if s.skipped:
        bp = "s were" if s.skipped != 1 else " was"
        sentence += f" {s.skipped} blank cell{bp} skipped."
    return sentence


def source_label(source: str | None) -> str:
    """Where the matched page's text came from: 'OCR', 'Text layer', or '-' (none)."""
    if source == "OCR":
        return "OCR"
    if source == "text":
        return "Text layer"
    return "-"


def detail(r: MatchResult) -> str:
    """A plain-English explanation of one result (no markup)."""
    where = f"page {r.page}" if r.page else "the PDF"
    if r.status is Status.EXACT:
        return f"Found on {where}."
    if r.status is Status.FUZZY:
        found = r.best_match or ""
        return (
            f"Found on {where}, but not an exact match. "
            f"Your spreadsheet has “{r.expected}”; the PDF shows “{found}” "
            f"({r.score}% similar)."
        )
    if r.status is Status.MISSING:
        if r.best_match:
            return (
                f"Not found in the PDF. The closest text was “{r.best_match}” on "
                f"{where}, but it was too different ({r.score}% similar)."
            )
        return "Not found anywhere in the PDF."
    return "The spreadsheet cell was empty, so there was nothing to check."
