# `proofcheck/web/store.py` — Explained

> Dependency-free, offline persistence (stdlib `sqlite3`) for the two optional web features: **auth** (a users table) and **persistent run history** (a runs table). Stores only non-PII run metadata.

## Purpose
SQLite ships with Python, needs no server, and keeps ProofCheck installable with zero infrastructure — a perfect fit for the project's offline/no-CDN ethos. This module owns the database: schema creation, user CRUD, and run-history CRUD. It deliberately stores only **non-PII** run metadata (filenames + summary counts + flags) so history can outlive the short-lived report cache, while the uploaded spreadsheets/PDFs are still deleted immediately after each run by `web/app.py`.

## Dependencies
- **Imports (external):** `json` (serialize summary/meta dicts), `os` (read `$PROOFCHECK_DB`), `sqlite3` (the database), `tempfile` (default DB location), `dataclasses.dataclass`, `pathlib.Path`.
- **Imports (internal):** None — leaf module.
- **Used by:** `proofcheck/web/auth.py` (users) and `proofcheck/web/app.py` (history + startup `init_db`).

## Line-by-line / block-by-block breakdown

### `db_path()`
```python
def db_path() -> Path:
    env = os.environ.get("PROOFCHECK_DB")
    if env:
        return Path(env)
    return Path(tempfile.gettempdir()) / "proofcheck" / "proofcheck.db"
```
Resolves the SQLite file path **fresh on every call** (not cached), so tests can point `$PROOFCHECK_DB` at a throwaway file per test (`tests/conftest.py::_isolated_db`) and have it take effect immediately.

### `_connect()`
Opens a new connection, ensures the parent directory exists, sets `row_factory = sqlite3.Row` (dict-like rows), and enables WAL journal mode for better read/write concurrency. **One short-lived connection per call** is the simplest correct pattern under FastAPI's threadpool — each worker thread gets its own connection instead of sharing one across threads.

### `init_db()`
Runs an idempotent `CREATE TABLE IF NOT EXISTS` script for `users` and `runs` plus an index on `runs(username, created_at DESC)`. Safe to call repeatedly; there is no separate migration step. Called at import time and startup by `web/app.py`.

### Users — `count_users` / `get_user` / `create_user`
- `count_users()` → used by `auth.bootstrap_admin()` to only seed an admin when the table is empty.
- `get_user(username)` → returns a `User` dataclass (`username`, `password_hash`, `salt`, `created_at`) or `None`.
- `create_user(...)` → inserts; translates `sqlite3.IntegrityError` (duplicate username) into a clean `ValueError`.

### Run history — `add_run` / `list_runs` / `get_run` / `delete_run`
- `add_run(...)` uses `INSERT OR REPLACE` keyed on `run_id`; `summary` and `meta` dicts are stored as JSON text.
- `_row_to_record` rehydrates a row into a `RunRecord` (with `json.loads` for summary/meta).
- `list_runs(username, limit=100)` returns the user's runs newest-first (uses the index).
- `get_run(run_id, username)` enforces **ownership** in the query (`WHERE run_id=? AND username=?`) so users can't read each other's runs.
- `delete_run(run_id, username)` deletes by owner and returns whether a row was removed (`rowcount > 0`).

## Functions / Methods / Classes
| Name | Signature | Returns | Description |
| --- | --- | --- | --- |
| `db_path` | `db_path() -> Path` | `Path` | DB file path from `$PROOFCHECK_DB` (or tempdir default). |
| `init_db` | `init_db() -> None` | — | Idempotent schema creation. |
| `User` | `@dataclass User(username, password_hash, salt, created_at)` | — | A stored user. |
| `count_users` | `count_users() -> int` | `int` | Number of users (for admin bootstrap). |
| `get_user` | `get_user(username) -> User \| None` | `User \| None` | Lookup by username. |
| `create_user` | `create_user(username, password_hash, salt, created_at) -> None` | — | Insert; `ValueError` on duplicate. |
| `RunRecord` | `@dataclass RunRecord(run_id, username, created_at, excel, pdf, summary, meta)` | — | A persisted run. |
| `add_run` | `add_run(*, run_id, username, created_at, excel, pdf, summary, meta) -> None` | — | Upsert a run record. |
| `list_runs` | `list_runs(username, *, limit=100) -> list[RunRecord]` | list | A user's runs, newest first. |
| `get_run` | `get_run(run_id, username) -> RunRecord \| None` | record | Owner-scoped fetch. |
| `delete_run` | `delete_run(run_id, username) -> bool` | `bool` | Owner-scoped delete. |

## Notes / gotchas
- **Non-PII only:** only filenames + summary counts + flags are persisted; the spreadsheets/PDFs themselves are never stored.
- **Ownership in the query:** `get_run`/`delete_run` filter by `username`, so isolation is enforced at the SQL layer, not just the route.
- **Anonymous mode:** when auth is off, every run is attributed to the `anonymous` user (see `web/auth.py`), so history still works single-user.
- **Connection-per-call** avoids SQLite's "objects created in a thread can only be used in that same thread" pitfall under FastAPI's threadpool.
- **Path read fresh each call** is what makes per-test DB isolation possible.
