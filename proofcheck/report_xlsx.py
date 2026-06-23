"""xlsx report generated from a :class:`RunResult` (openpyxl).

A Summary sheet plus one sheet per checked column, with status cells color-coded to
match the HTML report and web UI.
"""

from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .models import RunResult, Status

# Solid fills matching the shared status palette.
_FILLS = {
    Status.EXACT: PatternFill("solid", fgColor="2E7D32"),
    Status.FUZZY: PatternFill("solid", fgColor="F59E0B"),
    Status.MISSING: PatternFill("solid", fgColor="C62828"),
    Status.SKIPPED: PatternFill("solid", fgColor="9E9E9E"),
}
_WHITE = Font(color="FFFFFF", bold=True)
_HEADER = Font(bold=True)


def _flatten_diff(diff: list[tuple[str, str]]) -> str:
    """Render the diff as plain text since xlsx cells can't hold inline markup."""
    out = []
    for op, text in diff:
        if op == "equal":
            out.append(text)
        elif op == "delete":
            out.append(f"[-{text}-]")
        elif op == "insert":
            out.append(f"{{+{text}+}}")
        else:
            out.append(f"[-{text}-]")
    return "".join(out)


def _autosize(ws, max_width: int = 60) -> None:
    widths: dict[int, int] = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None:
                widths[cell.column] = min(max(widths.get(cell.column, 0), len(str(cell.value))), max_width)
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width + 2


def build(result: RunResult) -> Workbook:
    wb = Workbook()
    summary_ws = wb.active
    summary_ws.title = "Summary"

    s = result.summary
    rows = [
        ("ProofCheck report", ""),
        ("Excel", result.meta.excel),
        ("PDF", result.meta.pdf),
        ("Timestamp", result.meta.timestamp),
        ("Fuzzy threshold", result.meta.fuzzy_threshold),
        ("", ""),
        ("Total", s.total),
        ("Exact", s.exact),
        ("Fuzzy", s.fuzzy),
        ("Missing", s.missing),
        ("Skipped", s.skipped),
        ("Pass rate", f"{s.pass_rate * 100:.1f}%"),
    ]
    for label, value in rows:
        summary_ws.append([label, value])
    summary_ws["A1"].font = Font(bold=True, size=14)

    if result.warnings:
        summary_ws.append(["", ""])
        summary_ws.append(["Warnings", ""])
        for w in result.warnings:
            summary_ws.append(["", w])
    _autosize(summary_ws)

    for col in result.columns:
        # Sheet titles are capped at 31 chars and can't contain certain characters.
        title = col.name[:31] or "Column"
        ws = wb.create_sheet(title=title)
        ws.append(["Row", "Status", "Expected", "Best match", "Diff", "Page", "Score"])
        for cell in ws[1]:
            cell.font = _HEADER
        for r in col.results:
            ws.append([
                r.row, r.status.value, r.expected, r.best_match or "",
                _flatten_diff(r.diff), r.page if r.page is not None else "", r.score,
            ])
            status_cell = ws.cell(row=ws.max_row, column=2)
            status_cell.fill = _FILLS[r.status]
            status_cell.font = _WHITE
        _autosize(ws)

    return wb


def write(result: RunResult, path: str) -> None:
    build(result).save(path)
