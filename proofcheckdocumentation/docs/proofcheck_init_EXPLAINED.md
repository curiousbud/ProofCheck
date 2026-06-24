# `proofcheck/__init__.py` — Explained

> Marks the `proofcheck` directory as a Python package and declares the package version while restating its core deterministic, offline design promise.

## Purpose
This is the package initializer for `proofcheck`. Its job is minimal: make the directory importable as a package and expose `__version__`. It intentionally contains no logic, imports, or re-exports, keeping import of the package cheap and free of side effects.

## Dependencies
- **Imports (external):** None.
- **Imports (internal):** None.
- **Used by:** Implicitly used by every module imported as `proofcheck.*` (e.g. `proofcheck/cli.py`, `proofcheck/pipeline.py`, `proofcheck/matcher.py`, `proofcheck/models.py`, `proofcheck/normalize.py`, `proofcheck/web/app.py`) and by the test suite (`tests/`). Any code or packaging tooling that reads `proofcheck.__version__` consumes it directly.

## Line-by-line / block-by-block breakdown

### Module docstring
```python
"""ProofCheck — deterministic Excel-vs-PDF proof-reading.

100% deterministic. No AI / LLM / ML anywhere, offline, no network at runtime.
"""
```
The package-level docstring documents what ProofCheck is (a deterministic Excel-vs-PDF proof-reader) and restates the central guarantee: 100% deterministic, with no AI/LLM/ML, offline, and no network access at runtime. As the package docstring it is what `help(proofcheck)` and `proofcheck.__doc__` surface.

### Version declaration
```python
__version__ = "0.1.0"
```
Defines the package version string following semantic-versioning style (`MAJOR.MINOR.PATCH`). `__version__` is the conventional attribute tools and humans read to identify the installed release; here it is hard-coded rather than derived from packaging metadata.

## Functions / Methods / Classes
| Name | Signature | Returns | Description |
| --- | --- | --- | --- |
| — | — | — | This file defines no functions, methods, or classes. |

## Key variables / constants
| Name | Purpose |
| --- | --- |
| `__version__` | Package version string (`"0.1.0"`), the canonical value other code/tooling reads to identify the release. |

## Notes / gotchas
- **No side effects on import:** The file performs no imports and runs no logic, so `import proofcheck` is fast and cannot fail due to optional dependencies — submodules are imported explicitly where needed (e.g. `from proofcheck.pipeline import run`).
- **No re-exports:** Unlike some packages, this `__init__.py` does not lift submodule symbols into the package namespace; callers must import from the specific submodule (`from proofcheck.models import RunConfig`, etc.).
- **Hard-coded version:** `__version__` is a literal. If the project also declares a version in `pyproject.toml`/packaging metadata, the two must be kept in sync manually since neither is derived from the other.
- **Determinism statement lives here:** This file is the canonical place the no-AI/offline promise is asserted at the package level; it has no enforcement logic — it is documentation only.
