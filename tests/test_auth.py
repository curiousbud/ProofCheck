"""Auth + persistent run-history tests.

Auth is opt-in via PROOFCHECK_AUTH. The ``_isolated_db`` autouse fixture (conftest) gives
each test its own SQLite file, so users/history never leak between tests.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from proofcheck.web import auth
from proofcheck.web.app import app


@pytest.fixture
def client():
    # Fresh client per test => fresh cookie jar.
    return TestClient(app)


def _check(client, excel_path, pdf_path):
    with open(excel_path, "rb") as ex, open(pdf_path, "rb") as pf:
        return client.post(
            "/api/check",
            files={
                "excel": ("delegates.xlsx", io.BytesIO(ex.read()), "application/octet-stream"),
                "pdf": ("program.pdf", io.BytesIO(pf.read()), "application/pdf"),
            },
            data={"columns": "Name", "sheet": "Delegates"},
        )


# ---- auth disabled (default) ------------------------------------------------
def test_health_reports_auth_disabled_by_default(client):
    body = client.get("/api/health").json()
    assert body["auth_enabled"] is False
    assert "ocr_available" in body


def test_me_is_anonymous_when_auth_off(client):
    body = client.get("/api/auth/me").json()
    assert body["username"] == "anonymous"
    assert body["authenticated"] is False


def test_check_allowed_without_login_when_auth_off(client, excel_path, pdf_path):
    assert _check(client, excel_path, pdf_path).status_code == 200


# ---- auth enabled -----------------------------------------------------------
def test_protected_route_requires_login(client, excel_path, pdf_path, monkeypatch):
    monkeypatch.setenv("PROOFCHECK_AUTH", "on")
    assert client.get("/api/history").status_code == 401
    assert _check(client, excel_path, pdf_path).status_code == 401


def test_login_flow(client, monkeypatch):
    monkeypatch.setenv("PROOFCHECK_AUTH", "on")
    auth.register_user("alice", "supersecret")

    # Wrong password rejected.
    assert client.post("/api/auth/login", json={"username": "alice", "password": "nope"}).status_code == 401

    # Correct password sets a session cookie.
    res = client.post("/api/auth/login", json={"username": "alice", "password": "supersecret"})
    assert res.status_code == 200 and res.json()["authenticated"] is True
    assert auth.SESSION_COOKIE in res.cookies or auth.SESSION_COOKIE in client.cookies

    # /me now reflects the logged-in user, and protected routes work.
    me = client.get("/api/auth/me").json()
    assert me["username"] == "alice" and me["authenticated"] is True
    assert client.get("/api/history").status_code == 200

    # Logout clears the session.
    client.post("/api/auth/logout")
    assert client.get("/api/history").status_code == 401


def test_register_disabled_by_default(client, monkeypatch):
    monkeypatch.setenv("PROOFCHECK_AUTH", "on")
    res = client.post("/api/auth/register", json={"username": "bob", "password": "supersecret"})
    assert res.status_code == 403


def test_register_when_enabled(client, monkeypatch):
    monkeypatch.setenv("PROOFCHECK_AUTH", "on")
    monkeypatch.setenv("PROOFCHECK_ALLOW_REGISTER", "on")
    res = client.post("/api/auth/register", json={"username": "carol", "password": "supersecret"})
    assert res.status_code == 201
    assert client.get("/api/auth/me").json()["username"] == "carol"


# ---- history ----------------------------------------------------------------
def test_history_records_and_lists_runs(client, excel_path, pdf_path):
    # auth off -> attributed to "anonymous"
    res = _check(client, excel_path, pdf_path)
    run_id = res.json()["report_urls"]["html"].split("/")[-1].removesuffix(".html")

    listing = client.get("/api/history").json()
    assert any(r["run_id"] == run_id for r in listing["runs"])

    detail = client.get(f"/api/history/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["summary"]["exact"] == 1


def test_history_delete(client, excel_path, pdf_path):
    res = _check(client, excel_path, pdf_path)
    run_id = res.json()["report_urls"]["html"].split("/")[-1].removesuffix(".html")
    assert client.delete(f"/api/history/{run_id}").status_code == 200
    assert client.get(f"/api/history/{run_id}").status_code == 404


def test_history_is_per_user(client, excel_path, pdf_path, monkeypatch):
    monkeypatch.setenv("PROOFCHECK_AUTH", "on")
    auth.register_user("dave", "supersecret")
    client.post("/api/auth/login", json={"username": "dave", "password": "supersecret"})
    _check(client, excel_path, pdf_path)
    assert len(client.get("/api/history").json()["runs"]) == 1

    # A different user sees none of dave's runs.
    auth.register_user("erin", "supersecret")
    client.post("/api/auth/login", json={"username": "erin", "password": "supersecret"})
    assert client.get("/api/history").json()["runs"] == []
