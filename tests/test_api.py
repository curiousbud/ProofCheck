import io

import pytest
from fastapi.testclient import TestClient

from proofcheck.web import app as app_module
from proofcheck.web.app import app

client = TestClient(app)


def _excel_upload(excel_path):
    with open(excel_path, "rb") as fh:
        return io.BytesIO(fh.read())


def _pdf_upload(pdf_path):
    with open(pdf_path, "rb") as fh:
        return io.BytesIO(fh.read())


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_index_served():
    res = client.get("/")
    assert res.status_code == 200
    assert "ProofCheck" in res.text


def test_spa_static_assets_served():
    css = client.get("/static/app.css")
    js = client.get("/static/app.js")
    assert css.status_code == 200 and "ProofCheck" in css.text
    assert js.status_code == 200 and "/api/check" in js.text


def test_inspect_returns_sheets_and_headers(excel_path):
    res = client.post(
        "/api/inspect",
        files={"excel": ("delegates.xlsx", _excel_upload(excel_path),
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert res.status_code == 200
    data = res.json()
    assert "Delegates" in data["sheets"]
    assert data["headers"]["Delegates"][:3] == ["Name", "CC Code", "City"]


def test_check_returns_documented_shape_and_counts(excel_path, pdf_path):
    res = client.post(
        "/api/check",
        files={
            "excel": ("delegates.xlsx", _excel_upload(excel_path), "application/octet-stream"),
            "pdf": ("program.pdf", _pdf_upload(pdf_path), "application/pdf"),
        },
        data={"columns": "Name", "sheet": "Delegates", "fuzzy_threshold": "90"},
    )
    assert res.status_code == 200
    data = res.json()
    # Documented top-level keys.
    assert set(data) >= {"meta", "summary", "columns", "warnings", "report_urls"}
    s = data["summary"]
    assert s["exact"] == 1 and s["fuzzy"] == 1 and s["missing"] == 2 and s["skipped"] == 1
    # report_urls present and downloadable.
    assert data["report_urls"]["html"].endswith(".html")
    # diff is emitted as [op, text] pairs.
    fuzzy = [r for col in data["columns"] for r in col["results"] if r["status"] == "FUZZY"][0]
    assert all(len(pair) == 2 for pair in fuzzy["diff"])

    html_res = client.get(data["report_urls"]["html"])
    assert html_res.status_code == 200
    assert "ProofCheck report" in html_res.text


def test_bad_extension_returns_400(excel_path, pdf_path):
    res = client.post(
        "/api/check",
        files={
            "excel": ("notes.txt", io.BytesIO(b"nope"), "text/plain"),
            "pdf": ("program.pdf", _pdf_upload(pdf_path), "application/pdf"),
        },
        data={"columns": "Name", "sheet": "Delegates"},
    )
    assert res.status_code == 400


def test_oversize_returns_413(excel_path, pdf_path, monkeypatch):
    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 10)  # 10 bytes
    res = client.post(
        "/api/check",
        files={
            "excel": ("delegates.xlsx", _excel_upload(excel_path), "application/octet-stream"),
            "pdf": ("program.pdf", _pdf_upload(pdf_path), "application/pdf"),
        },
        data={"columns": "Name", "sheet": "Delegates"},
    )
    assert res.status_code == 413
