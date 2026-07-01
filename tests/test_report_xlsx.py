"""Regression tests for the xlsx report writer (proofcheck/report_xlsx.py)."""

import pytest

from proofcheck import report_xlsx
from proofcheck.models import (
    ColumnResult,
    MatchResult,
    Meta,
    RunResult,
    Status,
    Summary,
)

openpyxl = pytest.importorskip("openpyxl")


def _result_with(best_match: str, warning: str) -> RunResult:
    mr = MatchResult(
        row=1,
        expected="MR KESHAVALU NAIDU",
        status=Status.FUZZY,
        page=48,
        best_match=best_match,
        score=94,
        diff=[],
        source="OCR",
    )
    return RunResult(
        meta=Meta(excel="a.xlsx", pdf="b.pdf", timestamp="now", fuzzy_threshold=90, flags={}),
        summary=Summary(total=1, exact=0, fuzzy=1, missing=0, skipped=0, pass_rate=0.0),
        columns=[ColumnResult(name="Name", results=[mr])],
        warnings=[warning],
    )


def test_illegal_control_chars_do_not_crash_and_are_stripped(tmp_path):
    # OCR text can contain control chars (\x0b/\x0c) that openpyxl forbids in cells.
    # The writer must strip them instead of raising IllegalCharacterError.
    result = _result_with(best_match="KESHAVALU\x0bNAIDU\nPODILI", warning="warn\x0cline")
    path = tmp_path / "report.xlsx"

    report_xlsx.write(result, str(path))  # must not raise

    wb = openpyxl.load_workbook(str(path))
    all_text = "".join(
        str(c.value)
        for ws in wb.worksheets
        for row in ws.iter_rows()
        for c in row
        if c.value is not None
    )
    assert "\x0b" not in all_text and "\x0c" not in all_text
    assert "KESHAVALUNAIDU" in all_text.replace("\n", "")  # stripped, not mangled otherwise
    assert "\n" in all_text  # legal newline is preserved


def test_ordinary_text_is_untouched(tmp_path):
    result = _result_with(best_match="KESHAVALU NAIDU", warning="a normal note")
    path = tmp_path / "report.xlsx"

    report_xlsx.write(result, str(path))

    wb = openpyxl.load_workbook(str(path))
    all_text = "".join(
        str(c.value)
        for ws in wb.worksheets
        for row in ws.iter_rows()
        for c in row
        if c.value is not None
    )
    assert "KESHAVALU NAIDU" in all_text
    assert "a normal note" in all_text
