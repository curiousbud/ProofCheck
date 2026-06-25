"""Shared, deterministic test fixtures.

We generate the Excel and PDF on the fly (rather than committing binaries) so the
inputs are visible and reproducible. The fixtures are crafted to exercise every
status: EXACT, FUZZY, MISSING, SKIPPED, plus reverse matching and a no-text-layer
page warning.
"""

from __future__ import annotations

import pytest
from openpyxl import Workbook
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# Data row layout (header row is row 1; data starts at row 2):
#   Name              CC Code   City
#   Gauttam Sharma    CC-101    Mumbai      -> Name FUZZY  (PDF has "Gautam Sharma")
#   Priya Nair        CC-102    Delhi       -> Name EXACT
#   John Smith        CC-103    Bengaluru   -> Name MISSING; EXACT only with reverse ("Smith John")
#   Zzxqq Nobody      CC-999    Atlantis    -> Name MISSING
#   (blank)           CC-105    Chennai     -> Name SKIPPED
ROWS = [
    ("Gauttam Sharma", "CC-101", "Mumbai"),
    ("Priya Nair", "CC-102", "Delhi"),
    ("John Smith", "CC-103", "Bengaluru"),
    ("Zzxqq Nobody", "CC-999", "Atlantis"),
    (None, "CC-105", "Chennai"),
]

# Text placed on page 1 of the PDF (page 2 is left without any text layer).
PDF_LINES = [
    "Conference Delegate List",
    "Gautam Sharma   CC-101   Mumbai",
    "Priya Nair   CC-102   Delhi",
    "Smith John   CC-103   Bengaluru",
    "Other attendees from Chennai and elsewhere.",
]


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Point the web store at a throwaway SQLite file per test (auth/history isolation).

    Auth stays disabled by default (PROOFCHECK_AUTH unset), so the existing API tests are
    unaffected; tests that exercise auth opt in by setting the env var themselves.
    """
    monkeypatch.setenv("PROOFCHECK_DB", str(tmp_path / "proofcheck.db"))
    from proofcheck.web import store
    store.init_db()
    yield


@pytest.fixture(scope="session")
def excel_path(tmp_path_factory) -> str:
    path = tmp_path_factory.mktemp("fixtures") / "delegates.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Delegates"
    ws.append(["Name", "CC Code", "City"])
    for row in ROWS:
        ws.append(list(row))
    # A second sheet to prove /inspect reports multiple sheets.
    wb.create_sheet("Notes").append(["Field", "Value"])
    wb.save(path)
    return str(path)


@pytest.fixture(scope="session")
def pdf_path(tmp_path_factory) -> str:
    path = tmp_path_factory.mktemp("fixtures") / "program.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    y = 720
    for line in PDF_LINES:
        c.drawString(72, y, line)
        y -= 24
    c.showPage()
    # Page 2: a rectangle only, no text -> simulates a scanned/no-text-layer page.
    c.rect(72, 600, 200, 100, stroke=1, fill=0)
    c.showPage()
    c.save()
    return str(path)
