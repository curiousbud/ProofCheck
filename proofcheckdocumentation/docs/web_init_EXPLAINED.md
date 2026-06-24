# `proofcheck/web/__init__.py` — Explained

> The package marker for the ProofCheck web layer, documenting that this is an intentionally thin, disposable, zero-business-logic HTTP adapter.

## Purpose
This file marks `proofcheck/web` as a Python package. It contains no code beyond a module docstring; its sole job is to declare the package and record the design contract: the web layer holds zero business logic and exists only to adapt HTTP requests into a `RunConfig`, call `pipeline.run`, and serialize the `RunResult` to the JSON contract in `schemas.py`.

## Dependencies
- **Imports (external):** None — the file is a docstring only.
- **Imports (internal):** None. (The docstring *references* `proofcheck.models.RunConfig`, `proofcheck.pipeline.run`, `RunResult`, and `proofcheck.web.schemas`, but does not import them.)
- **Used by:** Python's import machinery — its presence makes `proofcheck.web` importable, enabling `from .web.app import app` (e.g. the CLI `serve` command), `from . import schemas` inside `app.py`, and test imports of the package.

## Line-by-line / block-by-block breakdown

### Module docstring (lines 1–7)
```python
"""ProofCheck web layer (FastAPI).

This package is intentionally thin and disposable. It contains **zero** business
logic — it only adapts HTTP requests into a :class:`proofcheck.models.RunConfig`,
calls :func:`proofcheck.pipeline.run`, and serializes the :class:`RunResult` to the
JSON contract defined in :mod:`proofcheck.web.schemas`.
"""
```
The entire file. It names the web layer (FastAPI), states its disposability, and pins the architectural rule that no matching/normalization logic lives in the web package. The three Sphinx cross-references (`RunConfig`, `pipeline.run`, `schemas`) map the request lifecycle: HTTP → `RunConfig` → `pipeline.run` → serialize to the `schemas` swap contract. There is no executable code, no `__all__`, and no re-exports.

## Endpoints (app.py only)
Not applicable to this file.

## Models (schemas.py only)
Not applicable to this file.

## Functions / Methods / Classes
This file defines no functions, methods, or classes — it is a docstring-only package initializer.

## Notes / gotchas
- **Zero business logic boundary:** the docstring is the canonical statement of the rule that the web package is an adapter only; all logic lives behind `pipeline.run()`.
- **Swap contract:** explicitly points readers to `proofcheck.web.schemas` as the stable JSON boundary.
- **No re-exports:** unlike some package `__init__` files, this one intentionally exposes nothing — consumers import `app`/`schemas` directly from their modules, keeping the surface minimal.
- **PII tempfile deletion / CORS / error envelope:** these concerns are documented and implemented in `app.py`, not here.

IMPORT_EDGES: web/__init__.py -> (none)
