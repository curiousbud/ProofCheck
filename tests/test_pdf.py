import pytest

from proofcheck import pdf
from proofcheck.models import RunConfig
from proofcheck.pipeline import run


def _verdicts(result):
    return [
        (r.row, r.expected, r.status, r.page, r.score, r.best_match, r.diff, r.source)
        for col in result.columns
        for r in col.results
    ]


def test_default_engine_is_pdfium_when_available(monkeypatch):
    monkeypatch.delenv("PROOFCHECK_PDF_ENGINE", raising=False)
    # pypdfium2 is a core dependency, so auto-selection prefers the fast engine.
    assert pdf._resolve_engine() == "pdfium"


def test_engine_override(monkeypatch):
    monkeypatch.setenv("PROOFCHECK_PDF_ENGINE", "pdfplumber")
    assert pdf._resolve_engine() == "pdfplumber"
    monkeypatch.setenv("PROOFCHECK_PDF_ENGINE", "pdfium")
    assert pdf._resolve_engine() == "pdfium"


@pytest.mark.parametrize("engine", ["pdfium", "pdfplumber"])
def test_engine_extracts_text_layer_and_flags_empty_page(pdf_path, engine, monkeypatch):
    monkeypatch.setenv("PROOFCHECK_PDF_ENGINE", engine)
    text = pdf.extract(pdf_path)
    # Page 1 carries the delegate lines; page 2 is a rectangle only (no text layer).
    assert "Priya Nair" in text.pages[1]
    assert text.empty_pages == [2]


def test_engines_produce_identical_verdicts(excel_path, pdf_path, monkeypatch):
    """PDFium and pdfplumber read the same text layer -> identical match results."""
    monkeypatch.setenv("PROOFCHECK_PDF_ENGINE", "pdfium")
    pdfium = run(RunConfig(excel_path=excel_path, pdf_path=pdf_path,
                           all_columns=True, sheet="Delegates", reverse=True))
    monkeypatch.setenv("PROOFCHECK_PDF_ENGINE", "pdfplumber")
    plumber = run(RunConfig(excel_path=excel_path, pdf_path=pdf_path,
                            all_columns=True, sheet="Delegates", reverse=True))
    assert _verdicts(pdfium) == _verdicts(plumber)
    assert pdfium.summary == plumber.summary
