"""Persistent storage for users and run history (stdlib ``sqlite3``).

Deliberately dependency-free and offline: SQLite ships with Python, needs no server,
and keeps ProofCheck installable with zero infrastructure. This backs two optional web
features — **auth** (a users table) and **persistent run history** (a runs table).

The database location is ``$PROOFCHECK_DB`` (default: ``<tempdir>/proofcheck/proofcheck.db``).
Every call opens its own short-lived connection, which is the simplest correct pattern
under FastAPI's threadpool (each worker thread gets its own connection). Schema creation
is idempotent (``CREATE TABLE IF NOT EXISTS``) so there is no separate migration step.

This module stores only **non-PII run metadata** (filenames + summary counts + flags) so
history survives the short-lived report cache. The uploaded spreadsheets/PDFs themselves
are still deleted immediately after each run, exactly as before.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path


def db_path() -> Path:
    """Resolve the SQLite file path from the environment (read fresh each call)."""
    env = os.environ.get("PROOFCHECK_DB")
    if env:
        return Path(env)
    return Path(tempfile.gettempdir()) / "proofcheck" / "proofcheck.db"


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    """Create the schema if it doesn't exist. Idempotent and safe to call repeatedly."""
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt          TEXT NOT NULL,
                created_at    TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                run_id       TEXT PRIMARY KEY,
                username     TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                excel        TEXT NOT NULL,
                pdf          TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                meta_json    TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_runs_user ON runs(username, created_at DESC);
            """
        )


# ---- Users ------------------------------------------------------------------
@dataclass
class User:
    username: str
    password_hash: str
    salt: str
    created_at: str


def count_users() -> int:
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


def get_user(username: str) -> User | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT username, password_hash, salt, created_at FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None:
        return None
    return User(row["username"], row["password_hash"], row["salt"], row["created_at"])


def create_user(username: str, password_hash: str, salt: str, created_at: str) -> None:
    """Insert a user. Raises ``ValueError`` if the username already exists."""
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)",
                (username, password_hash, salt, created_at),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"User {username!r} already exists.") from exc


# ---- Run history ------------------------------------------------------------
@dataclass
class RunRecord:
    run_id: str
    username: str
    created_at: str
    excel: str
    pdf: str
    summary: dict
    meta: dict


def add_run(
    *,
    run_id: str,
    username: str,
    created_at: str,
    excel: str,
    pdf: str,
    summary: dict,
    meta: dict,
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO runs "
            "(run_id, username, created_at, excel, pdf, summary_json, meta_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, username, created_at, excel, pdf, json.dumps(summary), json.dumps(meta)),
        )


def _row_to_record(row: sqlite3.Row) -> RunRecord:
    return RunRecord(
        run_id=row["run_id"],
        username=row["username"],
        created_at=row["created_at"],
        excel=row["excel"],
        pdf=row["pdf"],
        summary=json.loads(row["summary_json"]),
        meta=json.loads(row["meta_json"]),
    )


def list_runs(username: str, *, limit: int = 100) -> list[RunRecord]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM runs WHERE username = ? ORDER BY created_at DESC LIMIT ?",
            (username, limit),
        ).fetchall()
    return [_row_to_record(r) for r in rows]


def get_run(run_id: str, username: str) -> RunRecord | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE run_id = ? AND username = ?",
            (run_id, username),
        ).fetchone()
    return _row_to_record(row) if row else None


def delete_run(run_id: str, username: str) -> bool:
    """Delete a run owned by ``username``. Returns True if a row was removed."""
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM runs WHERE run_id = ? AND username = ?",
            (run_id, username),
        )
        return cur.rowcount > 0
