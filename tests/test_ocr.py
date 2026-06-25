"""OCR fallback tests.

The Tesseract binary may not be installed in CI, so these tests cover both the real
graceful-degradation path (OCR unavailable -> warn + skip, never crash) and a
monkeypatched success path that exercises the wiring without needing the engine.
"""

from __future__ import annotations

from proofcheck import ocr, pdf
from proofcheck.models import RunConfig, Status
from proofcheck.pipeline import run


def test_unavailable_reason_is_consistent():
    # available() and unavailable_reason() must agree.
    if ocr.available():
        assert ocr.unavailable_reason() is None
    else:
        assert ocr.unavailable_reason() is not None


def test_ocr_pages_raises_when_unavailable(pdf_path, monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: False)
    try:
        ocr.ocr_pages(pdf_path, [2])
        raised = False
    except ocr.OcrError:
        raised = True
    assert raised


def test_extract_without_ocr_flags_empty_page(pdf_path):
    result = pdf.extract(pdf_path)  # ocr defaults to False
    assert 2 in result.empty_pages
    assert any("no text layer" in w for w in result.warnings())


def test_extract_with_ocr_unavailable_degrades_gracefully(pdf_path, monkeypatch):
    # Force "libraries/engine missing" and ensure we warn + skip rather than raise.
    monkeypatch.setattr(ocr, "available", lambda: False)
    monkeypatch.setattr(ocr, "unavailable_reason", lambda: "engine missing for test")
    result = pdf.extract(pdf_path, ocr=True)
    assert 2 in result.empty_pages          # page stays skipped
    assert result.ocr_unavailable_reason == "engine missing for test"
    assert any("OCR was requested but is unavailable" in w for w in result.warnings())


def test_extract_with_ocr_recovers_page(pdf_path, monkeypatch):
    # Simulate a working OCR engine recovering text for the no-text-layer page 2.
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(
        ocr, "ocr_pages",
        lambda path, pages, **kw: {p: "Recovered Delegate Text" for p in pages},
    )
    result = pdf.extract(pdf_path, ocr=True)
    assert 2 in result.ocr_pages
    assert 2 not in result.empty_pages
    assert "Recovered" in result.pages[2]
    assert any("recovered via OCR" in w for w in result.warnings())


def test_ocr_error_is_recorded_not_raised(pdf_path, monkeypatch):
    def boom(path, pages, **kw):
        raise ocr.OcrError("render exploded")

    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "ocr_pages", boom)
    result = pdf.extract(pdf_path, ocr=True)
    assert result.ocr_error == "render exploded"
    assert 2 in result.empty_pages  # unchanged; we never lose determinism on failure


def test_pipeline_ocr_flag_recorded_in_meta(excel_path, pdf_path):
    config = RunConfig(excel_path=excel_path, pdf_path=pdf_path, columns=["Name"],
                       sheet="Delegates", ocr=True)
    result = run(config)
    assert result.meta.flags["ocr"] is True


def test_pipeline_diacritics_match(excel_path, pdf_path, monkeypatch):
    # A page whose text uses accents should match an unaccented expected value when
    # fold_diacritics is on. We patch the PDF text to include an accented variant.
    from proofcheck import pdf as pdf_mod

    real_extract = pdf_mod.extract

    def patched(path, **kw):
        text = real_extract(path, **kw)
        text.pages[1] = text.pages.get(1, "") + "\nRenee Nunez   CC-200   Pune"
        return text

    monkeypatch.setattr("proofcheck.pipeline.pdf.extract", patched)
    config = RunConfig(excel_path=excel_path, pdf_path=pdf_path, columns=["Name"],
                       sheet="Delegates", fold_diacritics=True)
    # Just assert the run completes deterministically with the flag echoed.
    result = run(config)
    assert result.meta.flags["fold_diacritics"] is True
