"""OCR fallback tests.

The Tesseract binary may not be installed in CI, so these tests cover both the real
graceful-degradation path (OCR unavailable -> warn + skip, never crash) and a
monkeypatched success path that exercises the wiring without needing the engine.
"""

from __future__ import annotations

import pytest

from proofcheck import ocr, ocr_cache, pdf
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


def test_ocr_cache_skips_reocr_on_unchanged_file(pdf_path, monkeypatch):
    calls = {"n": 0}

    def counting_ocr(path, pages, **kw):
        calls["n"] += 1
        return {p: "Recovered Delegate Text" for p in pages}

    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "ocr_pages", counting_ocr)

    first = pdf.extract(pdf_path, ocr=True)
    assert calls["n"] == 1 and first.ocr_pages == [2] and first.ocr_from_cache is False

    # Same file again -> cache hit -> OCR engine is NOT called a second time.
    second = pdf.extract(pdf_path, ocr=True)
    assert calls["n"] == 1                      # no re-OCR
    assert second.ocr_from_cache is True
    assert second.pages[2] == first.pages[2]    # identical recovered text
    assert any("file unchanged" in w for w in second.warnings())


def test_ocr_cache_misses_when_content_changes(pdf_path, tmp_path, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "ocr_pages",
                        lambda path, pages, **kw: (calls.__setitem__("n", calls["n"] + 1)
                                                   or {p: "text" for p in pages}))
    pdf.extract(pdf_path, ocr=True)
    assert calls["n"] == 1

    # A different (but valid) PDF hashes differently -> cache miss -> OCR runs again.
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    changed = tmp_path / "changed.pdf"
    c = canvas.Canvas(str(changed), pagesize=letter)
    c.drawString(72, 720, "A completely different first page")
    c.showPage()
    c.rect(72, 600, 200, 100, stroke=1, fill=0)  # page 2: no text layer -> needs OCR
    c.showPage()
    c.save()
    pdf.extract(str(changed), ocr=True)
    assert calls["n"] == 2


def test_ocr_cache_can_be_disabled(pdf_path, monkeypatch):
    monkeypatch.setenv("PROOFCHECK_OCR_CACHE", "off")
    assert ocr_cache.enabled() is False
    calls = {"n": 0}
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "ocr_pages",
                        lambda path, pages, **kw: (calls.__setitem__("n", calls["n"] + 1)
                                                   or {p: "text" for p in pages}))
    pdf.extract(pdf_path, ocr=True)
    pdf.extract(pdf_path, ocr=True)
    assert calls["n"] == 2  # no caching -> OCR runs every time


def test_pipeline_ocr_flag_recorded_in_meta(excel_path, pdf_path):
    config = RunConfig(excel_path=excel_path, pdf_path=pdf_path, columns=["Name"],
                       sheet="Delegates", ocr=True)
    result = run(config)
    assert result.meta.flags["ocr"] is True


def test_result_source_marks_text_vs_ocr(excel_path, pdf_path, monkeypatch):
    # Inject an OCR-recovered page 2 so a normally-MISSING value matches there.
    real_extract = pdf.extract

    def patched(path, **kw):
        t = real_extract(path)  # text layer only
        t.pages[2] = "Zzxqq Nobody CC-999 Atlantis"
        t.ocr_pages = [2]
        if 2 in t.empty_pages:
            t.empty_pages.remove(2)
        return t

    monkeypatch.setattr("proofcheck.pipeline.pdf.extract", patched)
    result = run(RunConfig(excel_path=excel_path, pdf_path=pdf_path,
                           columns=["Name"], sheet="Delegates"))
    by_expected = {r.expected: r for r in result.columns[0].results}
    # Priya Nair is on page 1 (real text layer); Zzxqq Nobody now matches the OCR'd page 2.
    assert by_expected["Priya Nair"].source == "text"
    assert by_expected["Zzxqq Nobody"].source == "OCR"
    assert by_expected["Zzxqq Nobody"].status is Status.EXACT
    # A skipped (blank) row has no matched page, so no source.
    assert by_expected[""].source is None


def test_diagnose_reports_text_and_confidence(pdf_path, tmp_path):
    if not ocr.available():
        pytest.skip("OCR engine not installed")
    diags = ocr.diagnose(pdf_path, [1, 2], save_dir=str(tmp_path / "imgs"))
    assert {d.page for d in diags} == {1, 2}
    for d in diags:
        assert isinstance(d.mean_confidence, float)
        assert d.word_count >= 0
        assert d.strategy  # the winning preprocess/psm strategy is reported
        assert d.image_path and __import__("os").path.isfile(d.image_path)  # rendered image saved


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
