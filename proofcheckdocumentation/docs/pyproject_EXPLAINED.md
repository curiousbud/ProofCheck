# `pyproject.toml` — Explained

> Packaging and tooling manifest for the `proofcheck` project: setuptools build backend, pinned runtime dependencies, dev (test) extras, the `proofcheck` console script, static web package-data, and pytest config.

## Purpose
This file declares how ProofCheck is built, installed, and tested. It pins every runtime dependency for reproducibility, separates test-only tools into a `dev` optional extra, registers the CLI entry point, ensures the web static assets ship inside the wheel, and points pytest at the `tests` directory.

## Dependencies
- **Imports (external):** N/A (this is a TOML manifest, not Python). It declares the project's external runtime deps (`click`, `openpyxl`, `pdfplumber`, `rapidfuzz`, `fastapi`, `uvicorn`, `python-multipart`, `pydantic`) and dev deps (`pytest`, `httpx`, `reportlab`).
- **Imports (internal):** None.
- **Used by:** `pip`/`setuptools` at build/install time; `pytest` reads `[tool.pytest.ini_options]`; the console-script entry point exposes `proofcheck.cli:main`.

## Line-by-line / block-by-block breakdown

### `[build-system]`
```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"
```
Declares the build dependencies (modern setuptools and wheel) and selects setuptools' PEP 517 build backend. This is what `pip install .` / `python -m build` invoke to produce the wheel/sdist.

### `[project]` core metadata
```toml
[project]
name = "proofcheck"
version = "0.1.0"
description = "Deterministic Excel-vs-PDF proof-reading (no AI/LLM/ML, offline)."
readme = "README.md"
requires-python = ">=3.10"
license = { text = "MIT" }
```
Standard PEP 621 metadata: package name, version, a one-line description emphasizing the deterministic/offline design, the README for the long description, a Python floor of 3.10, and the MIT license.

### `dependencies` (pinned runtime)
```toml
dependencies = [
    "click==8.4.1",
    "openpyxl==3.1.5",
    "pdfplumber==0.11.10",
    "rapidfuzz==3.14.5",
    "fastapi==0.138.0",
    "uvicorn[standard]==0.49.0",
    "python-multipart==0.0.32",
    "pydantic==2.13.4",
]
```
Exact (`==`) pins for reproducibility. Roles:
- `click` — CLI argument parsing for the `proofcheck` command.
- `openpyxl` — read `.xlsx` workbooks (sheets, headers, cell values).
- `pdfplumber` — extract the PDF text layer for matching.
- `rapidfuzz` — deterministic fuzzy string scoring (the FUZZY threshold engine).
- `fastapi` — the web API layer.
- `uvicorn[standard]` — ASGI server to run the web app.
- `python-multipart` — required by FastAPI to parse multipart file uploads (`/api/check`, `/api/inspect`).
- `pydantic` — request/response models and config validation (e.g., `RunConfig`).

The comment notes the core matching/normalization is deterministic while the web extras expose the same pipeline over a stable JSON contract.

### `[project.optional-dependencies]` — `dev`
```toml
[project.optional-dependencies]
dev = [
    "pytest==9.1.1",
    "httpx==0.28.1",
    "reportlab==5.0.0",
]
```
Test-only extras installed via `pip install ".[dev]"`:
- `pytest` — the test runner.
- `httpx` — HTTP client that backs FastAPI's `TestClient` in `test_api.py`.
- `reportlab` — generates the PDF fixture in `conftest.py` (paired with `openpyxl`, already a runtime dep, for the Excel fixture).

These are intentionally NOT runtime deps, so production installs stay lean.

### `[project.scripts]` — console entry point
```toml
[project.scripts]
proofcheck = "proofcheck.cli:main"
```
Installs a `proofcheck` command that calls `main()` in `proofcheck/cli.py`.

### `[tool.setuptools.packages.find]`
```toml
[tool.setuptools.packages.find]
include = ["proofcheck*"]
```
Auto-discovers and packages the `proofcheck` package and all its subpackages (e.g., `proofcheck.web`), excluding unrelated top-level dirs like `tests`.

### `[tool.setuptools.package-data]`
```toml
[tool.setuptools.package-data]
"proofcheck.web" = ["static/*"]
```
Ships the web UI's static files (everything under `proofcheck/web/static/`) inside the wheel, so the served index page and assets are present in an installed package — required for `GET /` in `test_api.py::test_index_served`.

### `[tool.pytest.ini_options]`
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```
Configures pytest to collect tests from the `tests` directory by default, so a bare `pytest` invocation runs the suite.

## Fixtures / Tests / Sections

| Section | What it configures |
| --- | --- |
| `[build-system]` | setuptools+wheel build backend (PEP 517). |
| `[project]` | Name, version, description, README, Python ≥3.10, MIT license. |
| `dependencies` | Pinned runtime deps (click, openpyxl, pdfplumber, rapidfuzz, fastapi, uvicorn, python-multipart, pydantic). |
| `[project.optional-dependencies].dev` | Test extras: pytest, httpx, reportlab. |
| `[project.scripts]` | `proofcheck` console script → `proofcheck.cli:main`. |
| `[tool.setuptools.packages.find]` | Discover `proofcheck*` packages. |
| `[tool.setuptools.package-data]` | Bundle `proofcheck/web/static/*` into the wheel. |
| `[tool.pytest.ini_options]` | `testpaths = ["tests"]`. |

## Notes / gotchas
- **Everything is exact-pinned (`==`)** for reproducible, offline-friendly builds — consistent with the "deterministic, no AI/ML" design.
- **`reportlab` and `httpx` are dev-only:** the PDF fixture generator and the API test client are not needed at runtime, so they live under the `dev` extra, keeping production installs minimal.
- **`uvicorn[standard]`** pulls the standard extra (e.g., websockets/uvloop bits) for the ASGI server; `python-multipart` is mandatory for FastAPI file uploads even though tests never import it directly.
- **package-data matters:** without `proofcheck.web = ["static/*"]`, an installed wheel would 404 on `GET /` and the static UI would be missing.
- **No linter/formatter config** is declared here (only build, deps, and pytest).

## v0.2 changes

Version bumped to 0.2.0. Added an optional `[ocr]` extra (pytesseract, Pillow, pypdfium2); the `[dev]` extra now includes those too so the test-suite can exercise the OCR wiring. The Tesseract engine binary is still a separate OS-level install. Auth/history need no new deps (stdlib sqlite3/hashlib/hmac).

