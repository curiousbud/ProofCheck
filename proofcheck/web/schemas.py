"""Pydantic models — **THE SWAP CONTRACT**.

These models define the stable JSON API. Any future frontend (a React/Vue SPA, a
mobile app, a CI integration) only needs to speak this contract; the HTML page in
``static/`` is just one disposable client of it. Treat changes here as API changes:
they must stay backward compatible or be versioned.

The shapes mirror :mod:`proofcheck.models` exactly — the web layer maps the internal
dataclasses onto these and adds nothing semantic.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    # Lets a frontend decide whether to show a login screen without a second request.
    auth_enabled: bool = False
    ocr_available: bool = False


class InspectResponse(BaseModel):
    """Sheets + per-sheet headers, used to populate the UI column picker."""

    sheets: list[str]
    headers: dict[str, list[str]]


class DiffPair(BaseModel):
    """One [op, text] diff fragment. op in {equal, insert, delete, replace}.

    Emitted as a 2-element JSON array so any frontend renders highlighting itself —
    the server never bakes in <del>/<ins> HTML.
    """

    op: str
    text: str


class MatchResultModel(BaseModel):
    row: int
    expected: str
    status: str = Field(description="EXACT | FUZZY | MISSING | SKIPPED")
    page: int | None = None
    best_match: str | None = None
    score: int = 0
    # Serialized as a list of [op, text] pairs (see module docstring / addendum spec).
    diff: list[tuple[str, str]] = Field(default_factory=list)
    # How the matched page's text was obtained: "text" | "OCR" | null (no matched page).
    source: str | None = None


class ColumnResultModel(BaseModel):
    name: str
    results: list[MatchResultModel] = Field(default_factory=list)


class MetaModel(BaseModel):
    excel: str
    pdf: str
    timestamp: str
    fuzzy_threshold: int
    flags: dict[str, bool]


class SummaryModel(BaseModel):
    total: int
    exact: int
    fuzzy: int
    missing: int
    skipped: int
    pass_rate: float


class ReportUrls(BaseModel):
    html: str
    xlsx: str


class CheckResponse(BaseModel):
    """Full result of POST /api/check — a direct serialization of RunResult."""

    meta: MetaModel
    summary: SummaryModel
    columns: list[ColumnResultModel]
    warnings: list[str] = Field(default_factory=list)
    report_urls: ReportUrls


class ErrorResponse(BaseModel):
    """Human-readable error envelope (never raw tracebacks)."""

    error: str


# ---- Auth (optional feature) ------------------------------------------------
class Credentials(BaseModel):
    username: str
    password: str


class AuthUser(BaseModel):
    """The currently-authenticated user (or the anonymous single-user identity)."""

    username: str
    authenticated: bool


# ---- Run history (optional feature) -----------------------------------------
class HistoryItem(BaseModel):
    """One past run's metadata. Report files may have expired; counts persist."""

    run_id: str
    created_at: str
    excel: str
    pdf: str
    summary: SummaryModel
    meta: MetaModel


class HistoryList(BaseModel):
    runs: list[HistoryItem] = Field(default_factory=list)
