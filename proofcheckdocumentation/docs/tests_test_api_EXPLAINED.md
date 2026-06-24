# `tests/test_api.py` — Explained

> Integration tests for the FastAPI web layer (`proofcheck.web.app`) using Starlette's `TestClient`, covering health, the served index page, `/api/inspect`, `/api/check` (response shape, counts, diff pairs, downloadable report), and the 400/413 error paths.

## Purpose
These tests drive the HTTP API in-process via `TestClient`, uploading the generated fixture files as multipart form data. They confirm the JSON contract (`meta`, `summary`, `columns`, `warnings`, `report_urls`), that summary counts match the deterministic pipeline, that diffs serialize as `[op, text]` pairs, that a generated HTML report is retrievable, and that bad file extensions and oversize uploads are rejected with 400/413.

## Dependencies
- **Imports (external):** `io` (wrap file bytes in `BytesIO` for upload); `pytest` (runner + `monkeypatch`); `fastapi.testclient.TestClient` (in-process HTTP client, backed by `httpx`, a dev dependency).
- **Imports (internal):** `proofcheck.web.app` — the `app` ASGI instance (mounted on `TestClient`), and the `app as app_module` module handle (used to monkeypatch `MAX_UPLOAD_BYTES`).
- **Used by:** Run by pytest. Consumes the `excel_path` and `pdf_path` fixtures from `conftest.py`.

## Line-by-line / block-by-block breakdown

### Imports, client, and upload helpers
```python
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
```
A single module-level `client` wraps the ASGI `app`. The two helpers read a fixture file fully into memory and return a `BytesIO`, the form-upload payload. Importing both `app_module` (the module) and `app` (the instance) is deliberate: the module handle is needed to monkeypatch its `MAX_UPLOAD_BYTES` constant.

### `test_health`
```python
def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
```
`GET /api/health` returns 200 with JSON `{"status": "ok"}` — a liveness check.

### `test_index_served`
```python
def test_index_served():
    res = client.get("/")
    assert res.status_code == 200
    assert "ProofCheck" in res.text
```
`GET /` serves the static index page (200) containing the string `"ProofCheck"`, confirming the static asset mount works.

### `test_inspect_returns_sheets_and_headers`
```python
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
```
Uploads just the Excel file to `/api/inspect`. The response lists sheet names (must include `"Delegates"` — the `Notes` sheet from the fixture proves multi-sheet support) and per-sheet headers, where `Delegates`' first three headers are exactly `["Name", "CC Code", "City"]`.

### `test_check_returns_documented_shape_and_counts`
```python
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
```
The main happy-path integration. Posts both files plus form fields (`columns=Name`, `sheet=Delegates`, `fuzzy_threshold=90`). Asserts:
- The JSON contains (at least) the documented keys `meta`, `summary`, `columns`, `warnings`, `report_urls`.
- `summary` counts match the deterministic pipeline: **exact 1, fuzzy 1, missing 2, skipped 1** (same fixture math as `test_pipeline.py`).
- `report_urls["html"]` ends in `.html`.
- Each FUZZY result's `diff` serializes as 2-element `[op, text]` pairs (JSON form of the matcher diff tuples).
- The HTML report at that URL is downloadable (200) and contains `"ProofCheck report"`.

### `test_bad_extension_returns_400`
```python
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
```
Uploads a `.txt` file in the `excel` slot. The API validates the extension and returns **400 Bad Request** rather than attempting to parse it.

### `test_oversize_returns_413`
```python
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
```
Uses `monkeypatch` to shrink `MAX_UPLOAD_BYTES` to 10 bytes (auto-restored after the test), so the fixture uploads exceed the limit and the API returns **413 Payload Too Large**. Patching the constant is far simpler than fabricating a multi-megabyte file.

## Fixtures / Tests / Sections

| Name | What it verifies |
| --- | --- |
| `_excel_upload` / `_pdf_upload` (helpers) | Read a fixture into a `BytesIO` for multipart upload. |
| `test_health` | `GET /api/health` → 200, `{"status":"ok"}`. |
| `test_index_served` | `GET /` → 200 HTML containing "ProofCheck". |
| `test_inspect_returns_sheets_and_headers` | `/api/inspect` lists sheets (incl. Delegates) and headers. |
| `test_check_returns_documented_shape_and_counts` | `/api/check` JSON shape, counts (1/1/2/1), `[op,text]` diffs, downloadable HTML report. |
| `test_bad_extension_returns_400` | Wrong file extension → 400. |
| `test_oversize_returns_413` | Upload over `MAX_UPLOAD_BYTES` → 413 (via monkeypatch). |

## Notes / gotchas
- **`TestClient` runs the app in-process** over ASGI (no real socket); it is backed by `httpx`, declared in the `dev` optional dependencies.
- **Two imports of the web module:** `app` (the instance) is mounted on the client; `app_module` (the module) is the monkeypatch target for `MAX_UPLOAD_BYTES`.
- **`monkeypatch` for the 413 test** shrinks the size limit instead of creating a huge payload, keeping the test fast and deterministic; the patch is reverted automatically at test teardown.
- **Counts mirror the pipeline tests** because the same `conftest.py` fixtures and the same deterministic engine feed both layers.
- **Diff serialization:** matcher `(op, text)` tuples become JSON 2-element arrays `[op, text]`.
