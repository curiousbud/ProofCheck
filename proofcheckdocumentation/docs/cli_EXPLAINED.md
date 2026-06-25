# `proofcheck/cli.py` — Explained

> A thin [click](https://click.palletsclick.com/) wrapper that parses command-line arguments, builds a `RunConfig`, calls the shared `pipeline.run`, and emits human/CI-friendly output — without containing any verification logic of its own.

## Purpose

`cli.py` is the command-line front door to ProofCheck. It is deliberately a **thin wrapper**: each subcommand parses its arguments, constructs a `RunConfig` (or calls a small `excel` helper), delegates the real work to `proofcheck.pipeline.run`, and then prints results or writes report files. **No business logic lives here** — all matching, normalization, and PDF/Excel parsing happen in the shared pipeline, so the CLI and the web API (`proofcheck.web.app`) can never diverge in behaviour. It exposes three subcommands: `inspect`, `check`, and `serve`.

## Dependencies

- **Imports (external):**
  - `sys` — used by `_fail` and `check` to set process exit codes (`sys.exit(2)` / `sys.exit(1)`).
  - `click` — the CLI framework: group, commands, arguments, options, path validation, and `click.echo`.
  - `uvicorn` — imported **lazily** inside `serve` only, so the ASGI server is not a hard dependency for plain `check`/`inspect` usage.
- **Imports (internal):**
  - `from . import __version__, excel` — `__version__` feeds `--version`; `excel` provides `sheet_names`, `inspect`, and `ExcelError` for the `inspect` command.
  - `from .models import RunConfig, Status` — `RunConfig` is the config object passed to the pipeline. (`Status` is imported but not directly referenced in the command bodies.)
  - `from .pipeline import PipelineError, run as pipeline_run` — the shared engine and its error type.
  - **Lazy internal imports:** `from . import report_html` and `from . import report_xlsx` are imported *inside* the `check` body, only when `--html`/`--xlsx` is requested, keeping their (potentially heavier) dependencies optional.
- **Used by:** the `proofcheck` console script entry point, wired in `pyproject.toml` as `[project.scripts]` → `proofcheck = "proofcheck.cli:main"`.

## Line-by-line / block-by-block breakdown

### Module docstring & imports

```python
from __future__ import annotations

import sys

import click

from . import __version__, excel
from .models import RunConfig, Status
from .pipeline import PipelineError, run as pipeline_run
```

`from __future__ import annotations` allows the modern `str | None` union syntax in signatures on older Python. The imports pull in click, the version string, the `excel` helper module, the `RunConfig`/`Status` models, and the pipeline entry point (aliased to `pipeline_run` to avoid colliding with click command names).

### `_fail`

```python
def _fail(message: str) -> None:
    """Print a clean error (no traceback) and exit non-zero."""
    click.echo(f"Error: {message}", err=True)
    sys.exit(2)
```

Central error-exit helper. Prints `Error: <message>` to **stderr** (`err=True`) and exits with code **2**. This gives clean, user-facing errors with no Python traceback. It is called by `inspect` (on `excel.ExcelError`) and `check` (on `PipelineError`).

### `cli` (the group)

```python
@click.group()
@click.version_option(__version__, prog_name="proofcheck")
def cli() -> None:
    """ProofCheck — verify that Excel values appear in a PDF (deterministic, no AI)."""
```

The root command group. `@click.version_option` adds a `--version` flag that prints the package `__version__` under the program name `proofcheck`. The function body is empty — it exists only to host the subcommands.

### `inspect` command

```python
@cli.command()
@click.argument("excel_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--sheet", default=None, help="Sheet name (default: active sheet).")
@click.option("--header-row", default=1, show_default=True, help="1-based header row.")
def inspect(excel_path: str, sheet: str | None, header_row: int) -> None:
    """List sheets and column headers of an Excel file."""
    try:
        names = excel.sheet_names(excel_path)
        headers = excel.inspect(excel_path)
    except excel.ExcelError as exc:
        _fail(str(exc))
    click.echo(f"Sheets: {', '.join(names)}")
    for name, cols in headers.items():
        marker = " (active)" if sheet is None else ""
        click.echo(f"  [{name}]{marker}: {', '.join(c for c in cols if c)}")
```

Lists the sheets and column headers of an Excel workbook. `EXCEL_PATH` is validated by click as an existing file (`exists=True`, `dir_okay=False`). It calls `excel.sheet_names` and `excel.inspect`; any `excel.ExcelError` is funneled through `_fail` (clean stderr message, exit 2). It then echoes the sheet list and, per sheet, the non-empty column headers. The `--sheet`/`--header-row` options are accepted but only `sheet` lightly affects output (the `(active)` marker); `header_row` is currently not consumed in the body.

### `check` command

```python
@cli.command()
@click.argument("excel_path", type=click.Path(exists=True, dir_okay=False))
@click.argument("pdf_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--column", "-c", "columns", multiple=True, help="Column header to check (repeatable).")
@click.option("--all-columns", is_flag=True, help="Check every column on the sheet.")
@click.option("--sheet", default=None, help="Sheet name (default: active sheet).")
@click.option("--header-row", default=1, show_default=True, help="1-based header row.")
@click.option("--fuzzy-threshold", default=90, show_default=True, type=click.IntRange(0, 100))
@click.option("--normalize-digits", is_flag=True, help="Fold unicode digits to ASCII.")
@click.option("--strip-punctuation", is_flag=True, help="Ignore punctuation when matching.")
@click.option("--reverse", is_flag=True, help="Also try reversed word order (e.g. 'Last First').")
@click.option("--html", "html_out", type=click.Path(dir_okay=False), help="Write an HTML report here.")
@click.option("--xlsx", "xlsx_out", type=click.Path(dir_okay=False), help="Write an xlsx report here.")
def check(...) -> None:
```

The core command. It takes two positional, must-exist file arguments (`EXCEL_PATH`, `PDF_PATH`) and a set of options. Note the option-to-parameter remapping: `--column/-c` collects into the `columns` tuple (`multiple=True`), `--html` → `html_out`, `--xlsx` → `xlsx_out`. `--fuzzy-threshold` is constrained to `click.IntRange(0, 100)`.

```python
    config = RunConfig(
        excel_path=excel_path,
        pdf_path=pdf_path,
        columns=list(columns),
        all_columns=all_columns,
        sheet=sheet,
        header_row=header_row,
        fuzzy_threshold=fuzzy_threshold,
        normalize_digits=normalize_digits,
        strip_punctuation=strip_punctuation,
        reverse=reverse,
    )
    try:
        result = pipeline_run(config)
    except PipelineError as exc:
        _fail(str(exc))
```

All parsed flags are bundled into a single `RunConfig` (the `columns` tuple becomes a list). The shared `pipeline_run` does the actual work. Any `PipelineError` is converted to a clean error via `_fail` (exit 2).

```python
    s = result.summary
    click.echo(f"Total: {s.total}  Exact: {s.exact}  Fuzzy: {s.fuzzy}  "
               f"Missing: {s.missing}  Skipped: {s.skipped}  "
               f"Pass rate: {s.pass_rate * 100:.1f}%")
    for w in result.warnings:
        click.echo(f"  ! {w}", err=True)
```

Prints a one-line summary (counts plus pass rate as a percentage) to stdout, and any pipeline warnings to **stderr**.

```python
    if html_out:
        from . import report_html
        report_html.write(result, html_out)
        click.echo(f"HTML report: {html_out}")
    if xlsx_out:
        from . import report_xlsx
        report_xlsx.write(result, xlsx_out)
        click.echo(f"xlsx report: {xlsx_out}")
```

Optional report writers. The `report_html` and `report_xlsx` modules are **imported lazily** here, only when the corresponding flag is set, so their dependencies are not required for a basic check run.

```python
    # Non-zero exit when anything is missing, so CI/scripts can gate on it.
    if s.missing:
        sys.exit(1)
```

If the summary reports any missing values, the command exits with code **1**. This lets CI pipelines and scripts gate on verification failures (distinct from exit 2, which means an operational error).

### `serve` command

```python
@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8000, show_default=True, type=int)
@click.option("--reload", is_flag=True, help="Auto-reload on code changes (dev only).")
def serve(host: str, port: int, reload: bool) -> None:
    """Launch the web UI / JSON API (uvicorn on proofcheck.web.app:app)."""
    import uvicorn
    uvicorn.run("proofcheck.web.app:app", host=host, port=port, reload=reload)
```

Launches the web UI / JSON API. `uvicorn` is imported **lazily** inside the function. It runs the ASGI app at the import string `"proofcheck.web.app:app"`, binding to the given `--host`/`--port`, with optional `--reload` for development.

### `main` / `__main__`

```python
def main() -> None:
    cli()


if __name__ == "__main__":
    main()
```

`main` is the console-script entry point referenced by `pyproject.toml`; it simply invokes the click group. The `__main__` guard allows running the module directly with `python -m proofcheck.cli`.

## Commands & Options

### `inspect`

| Option/Arg | Type | Default | Maps to |
|---|---|---|---|
| `EXCEL_PATH` | `click.Path(exists=True, dir_okay=False)` | required | `excel_path` → `excel.sheet_names` / `excel.inspect` |
| `--sheet` | string | `None` (active sheet) | `sheet` (drives the `(active)` marker) |
| `--header-row` | int | `1` | `header_row` (accepted; not used in body) |

### `check`

| Option/Arg | Type | Default | Maps to |
|---|---|---|---|
| `EXCEL_PATH` | `click.Path(exists=True, dir_okay=False)` | required | `RunConfig.excel_path` |
| `PDF_PATH` | `click.Path(exists=True, dir_okay=False)` | required | `RunConfig.pdf_path` |
| `--column` / `-c` | string, `multiple=True` | `()` | `RunConfig.columns` (tuple → list) |
| `--all-columns` | flag | `False` | `RunConfig.all_columns` |
| `--sheet` | string | `None` | `RunConfig.sheet` |
| `--header-row` | int | `1` | `RunConfig.header_row` |
| `--fuzzy-threshold` | `click.IntRange(0, 100)` | `90` | `RunConfig.fuzzy_threshold` |
| `--normalize-digits` | flag | `False` | `RunConfig.normalize_digits` |
| `--strip-punctuation` | flag | `False` | `RunConfig.strip_punctuation` |
| `--reverse` | flag | `False` | `RunConfig.reverse` |
| `--html` | `click.Path(dir_okay=False)` | `None` | `html_out` → `report_html.write` |
| `--xlsx` | `click.Path(dir_okay=False)` | `None` | `xlsx_out` → `report_xlsx.write` |

### `serve`

| Option/Arg | Type | Default | Maps to |
|---|---|---|---|
| `--host` | string | `127.0.0.1` | `uvicorn.run(host=...)` |
| `--port` | int | `8000` | `uvicorn.run(port=...)` |
| `--reload` | flag | `False` | `uvicorn.run(reload=...)` |

### Group-level

| Option/Arg | Type | Default | Maps to |
|---|---|---|---|
| `--version` | flag | — | prints `__version__` (prog name `proofcheck`) |

## Functions / Methods

| Name | Signature | Returns | Description |
|---|---|---|---|
| `_fail` | `_fail(message: str) -> None` | never (exits) | Prints `Error: <message>` to stderr and `sys.exit(2)`. |
| `cli` | `cli() -> None` | `None` | The click command group (root); hosts subcommands and `--version`. |
| `inspect` | `inspect(excel_path, sheet, header_row) -> None` | `None` | Lists sheets and non-empty column headers; errors via `_fail`. |
| `check` | `check(excel_path, pdf_path, columns, all_columns, sheet, header_row, fuzzy_threshold, normalize_digits, strip_punctuation, reverse, html_out, xlsx_out) -> None` | `None` | Builds `RunConfig`, runs the pipeline, prints summary, writes optional reports, exits 1 if missing. |
| `serve` | `serve(host, port, reload) -> None` | `None` | Lazily imports uvicorn and serves `proofcheck.web.app:app`. |
| `main` | `main() -> None` | `None` | Console-script entry point; calls `cli()`. |

## Notes / gotchas

- **Clean error semantics:** all expected errors are surfaced via `_fail` as `Error: ...` on stderr with no Python traceback, keeping CLI output user-friendly.
- **Exit codes for CI gating:**
  - `2` — operational error (`excel.ExcelError` in `inspect`, `PipelineError` in `check`).
  - `1` — verification failure: `check` exits 1 whenever `summary.missing > 0`, so CI/scripts can gate on it.
  - `0` — success with no missing values.
- **Lazy imports keep deps optional:** `report_html` and `report_xlsx` are imported only when `--html`/`--xlsx` is passed; `uvicorn` is imported only inside `serve`. Plain `check`/`inspect` runs don't pull these in.
- **No divergence from web:** `check` does nothing but build a `RunConfig` and call `pipeline.run` — the exact same engine the web API uses — so CLI and web results stay identical.
- **`serve` target:** launches uvicorn against the import string `proofcheck.web.app:app` (host/port/reload from flags; `--reload` is dev-only).
- **Option remapping:** `--column/-c` accumulates into `columns`; `--html`/`--xlsx` map to `html_out`/`xlsx_out` to avoid clashing with built-ins/keywords.
- **Minor:** `inspect`'s `--header-row` (and largely `--sheet`) are accepted but barely influence its output; `Status` is imported at module level but not referenced in the command bodies.

IMPORT_EDGES: proofcheck.cli -> proofcheck (__version__); proofcheck.cli -> proofcheck.excel; proofcheck.cli -> proofcheck.models (RunConfig, Status); proofcheck.cli -> proofcheck.pipeline (PipelineError, run); proofcheck.cli -> proofcheck.report_html (lazy, in check); proofcheck.cli -> proofcheck.report_xlsx (lazy, in check); proofcheck.cli -> proofcheck.web.app:app (runtime import-string via uvicorn in serve)

## v0.2 changes

`check` gained `--fold-diacritics`, `--ocr`, `--ocr-dpi` (IntRange 72-1200), and `--ocr-lang` options, wired straight into `RunConfig`. No change to `inspect`/`serve`.


## v0.2 changes (OCR diagnostics + source column)

New `proofcheck ocr PDF` diagnostics command: prints recovered text + mean confidence per page (flags low-confidence), with `--pages`/`--all-pages`, `--ocr-lang/--ocr-dpi/--ocr-psm`, `--save-images DIR` (dump the images fed to Tesseract), and `--full-text`. `check` also gained `--ocr-psm` (page-segmentation mode).


## v0.2 changes (image input + engine v3)

`check` and `ocr` now accept a PDF, a single image, OR a directory of images (PDF_PATH arg is `dir_okay=True`). The `ocr` command branches on `images.is_image_input`: for images it lists files, labels each page with its filename, and uses `ocr.diagnose_image_file`; it prints a per-run low-confidence count. (`import os` added.)


## v0.2 changes (theme + OCR-cache toggle)

`check` gained `--no-ocr-cache` (force fresh OCR -> `RunConfig.ocr_cache=False`).

