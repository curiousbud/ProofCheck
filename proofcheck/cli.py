"""ProofCheck command-line interface (click).

Thin wrapper: parse args -> build :class:`RunConfig` -> :func:`pipeline.run` ->
report writers. All real logic lives in the shared pipeline so the CLI and the web
API never diverge.
"""

from __future__ import annotations

import sys

import click

from . import __version__, excel
from .models import RunConfig, Status
from .pipeline import PipelineError, run as pipeline_run


def _fail(message: str) -> None:
    """Print a clean error (no traceback) and exit non-zero."""
    click.echo(f"Error: {message}", err=True)
    sys.exit(2)


@click.group()
@click.version_option(__version__, prog_name="proofcheck")
def cli() -> None:
    """ProofCheck — verify that Excel values appear in a PDF (deterministic, no AI)."""


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
@click.option("--fold-diacritics", is_flag=True,
              help="Fold accents/diacritics so accented names match their unaccented form.")
@click.option("--reverse", is_flag=True, help="Also try reversed word order (e.g. 'Last First').")
@click.option("--ocr", is_flag=True, help="OCR pages with no text layer (needs the optional OCR extra).")
@click.option("--ocr-dpi", default=300, show_default=True, type=click.IntRange(72, 1200),
              help="Render DPI used for OCR.")
@click.option("--ocr-lang", default="eng", show_default=True, help="Tesseract language(s), e.g. 'eng+ara'.")
@click.option("--html", "html_out", type=click.Path(dir_okay=False), help="Write an HTML report here.")
@click.option("--xlsx", "xlsx_out", type=click.Path(dir_okay=False), help="Write an xlsx report here.")
def check(
    excel_path: str,
    pdf_path: str,
    columns: tuple[str, ...],
    all_columns: bool,
    sheet: str | None,
    header_row: int,
    fuzzy_threshold: int,
    normalize_digits: bool,
    strip_punctuation: bool,
    fold_diacritics: bool,
    reverse: bool,
    ocr: bool,
    ocr_dpi: int,
    ocr_lang: str,
    html_out: str | None,
    xlsx_out: str | None,
) -> None:
    """Check EXCEL_PATH values against PDF_PATH and print a summary."""
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
        fold_diacritics=fold_diacritics,
        reverse=reverse,
        ocr=ocr,
        ocr_dpi=ocr_dpi,
        ocr_lang=ocr_lang,
    )
    try:
        result = pipeline_run(config)
    except PipelineError as exc:
        _fail(str(exc))

    s = result.summary
    click.echo(f"Total: {s.total}  Exact: {s.exact}  Fuzzy: {s.fuzzy}  "
               f"Missing: {s.missing}  Skipped: {s.skipped}  "
               f"Pass rate: {s.pass_rate * 100:.1f}%")
    for w in result.warnings:
        click.echo(f"  ! {w}", err=True)

    if html_out:
        from . import report_html
        report_html.write(result, html_out)
        click.echo(f"HTML report: {html_out}")
    if xlsx_out:
        from . import report_xlsx
        report_xlsx.write(result, xlsx_out)
        click.echo(f"xlsx report: {xlsx_out}")

    # Non-zero exit when anything is missing, so CI/scripts can gate on it.
    if s.missing:
        sys.exit(1)


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8000, show_default=True, type=int)
@click.option("--reload", is_flag=True, help="Auto-reload on code changes (dev only).")
def serve(host: str, port: int, reload: bool) -> None:
    """Launch the web UI / JSON API (uvicorn on proofcheck.web.app:app)."""
    import uvicorn
    uvicorn.run("proofcheck.web.app:app", host=host, port=port, reload=reload)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
