"""ProofCheck command-line interface (click).

Thin wrapper: parse args -> build :class:`RunConfig` -> :func:`pipeline.run` ->
report writers. All real logic lives in the shared pipeline so the CLI and the web
API never diverge.
"""

from __future__ import annotations

import os
import sys

import click

from . import __version__, excel
from .models import RunConfig, Status
from .pipeline import PipelineError, run as pipeline_run


def _fail(message: str) -> None:
    """Print a clean error (no traceback) and exit non-zero."""
    click.echo(f"Error: {message}", err=True)
    sys.exit(2)


class _ProgressBar:
    """Render pipeline progress as a single, in-place updating line on stderr.

    Consumes the ``(stage, current, total)`` events emitted by :func:`pipeline.run`. Each
    stage ("OCR", "Matching") gets its own bar; redraws are throttled to whole-percent
    changes so a huge sheet doesn't flood the terminal. When a stage reaches ``current ==
    total`` the bar is completed with a "done" marker and a trailing newline, giving a
    definite completion indication before the next stage (or the final summary) prints.
    """

    _LABELS = {"extract": "Extract", "match": "Matching"}
    _WIDTH = 28

    def __init__(self) -> None:
        self._stage: str | None = None
        self._last_pct = -1

    def __call__(self, stage: str, current: int, total: int) -> None:
        if total <= 0:
            return
        # Starting a new stage resets the throttle so its first frame always draws.
        if stage != self._stage:
            self._stage = stage
            self._last_pct = -1
        pct = int(current * 100 / total)
        done = current >= total
        if pct == self._last_pct and not done:
            return
        self._last_pct = pct
        label = self._LABELS.get(stage, stage)
        filled = int(self._WIDTH * current / total)
        # ASCII bar (not unicode block glyphs) so it renders on legacy Windows consoles too.
        bar = "#" * filled + "-" * (self._WIDTH - filled)
        tail = "  done\n" if done else ""
        click.echo(f"\r{label:<9}[{bar}] {current}/{total} ({pct:3d}%){tail}",
                   nl=False, err=True)


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
@click.argument("pdf_path", type=click.Path(exists=True, dir_okay=True),
                metavar="PDF_OR_IMAGES")
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
@click.option("--ocr-psm", default=6, show_default=True, type=click.IntRange(0, 13),
              help="Tesseract page-segmentation mode (6=block, 3=auto, 4=columns, 11=sparse).")
@click.option("--no-ocr-cache", is_flag=True, help="Force fresh OCR (ignore the OCR cache).")
@click.option("--workers", "-j", default=0, show_default=True, type=click.IntRange(0, 64),
              help="Parallel workers for OCR and matching (0 = auto from CPU count, capped at 8; 1 = sequential).")
@click.option("--progress/--no-progress", "progress", default=None,
              help="Show a progress bar (default: on when stderr is a terminal).")
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
    ocr_psm: int,
    no_ocr_cache: bool,
    workers: int,
    progress: bool | None,
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
        ocr_psm=ocr_psm,
        ocr_cache=not no_ocr_cache,
        workers=workers,
    )
    # Auto-enable the bar for interactive terminals; suppress it when piped or with --no-progress.
    show_progress = sys.stderr.isatty() if progress is None else progress
    progress_cb = _ProgressBar() if show_progress else None
    try:
        result = pipeline_run(config, progress=progress_cb)
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


def _parse_pages(spec: str, page_count: int) -> list[int]:
    """Parse a page spec like '1,3,5-7' into a sorted list of valid 1-based page numbers."""
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, _, hi = part.partition("-")
            try:
                for p in range(int(lo), int(hi) + 1):
                    pages.add(p)
            except ValueError:
                continue
        elif part.isdigit():
            pages.add(int(part))
    return sorted(p for p in pages if 1 <= p <= page_count)


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--pages", default=None,
              help="Pages/images to OCR, e.g. '1,3,5-7'. Default: pages with no text layer (all, for images).")
@click.option("--all-pages", is_flag=True, help="OCR every page, even those with a text layer.")
@click.option("--ocr-lang", default="eng", show_default=True, help="Tesseract language(s), e.g. 'eng+ara'.")
@click.option("--ocr-dpi", default=300, show_default=True, type=click.IntRange(72, 1200))
@click.option("--ocr-psm", default=6, show_default=True, type=click.IntRange(0, 13),
              help="Page-segmentation mode (6=block, 3=auto, 4=columns, 11=sparse).")
@click.option("--save-images", type=click.Path(file_okay=False),
              help="Directory to save the images fed to OCR (to see what Tesseract saw).")
@click.option("--full-text", is_flag=True, help="Print the full OCR text for every page.")
def ocr(
    path: str,
    pages: str | None,
    all_pages: bool,
    ocr_lang: str,
    ocr_dpi: int,
    ocr_psm: int,
    save_images: str | None,
    full_text: bool,
) -> None:
    """Diagnose OCR on a PDF, an image, or a folder of images: text + confidence per page.

    Use this to verify OCR quality. For a PDF it OCRs the no-text-layer pages by default
    (--pages / --all-pages to inspect others); for images every image is OCR'd.
    """
    from . import images as images_mod, ocr as ocr_mod, pdf as pdf_mod

    if not ocr_mod.available():
        _fail(ocr_mod.unavailable_reason() or "OCR is unavailable.")

    is_images = images_mod.is_image_input(path)
    empty: set[int] = set()
    labels: dict[int, str] = {}

    try:
        if is_images:
            files = images_mod.list_images(path)
            page_count = len(files)
            kind = f"images ({page_count})"
            empty = set(range(1, page_count + 1))  # images never have a text layer
            labels = {i: os.path.basename(f) for i, f in enumerate(files, start=1)}
            targets = _parse_pages(pages, page_count) if pages else list(range(1, page_count + 1))
        else:
            layer = pdf_mod.extract(path)  # text-layer pass: which pages need OCR
            page_count = len(layer.pages)
            kind = f"PDF, {page_count} page(s)"
            empty = set(layer.empty_pages)
            if pages:
                targets = _parse_pages(pages, page_count)
            elif all_pages:
                targets = list(range(1, page_count + 1))
            else:
                targets = sorted(empty)
    except pdf_mod.PdfError as exc:
        _fail(str(exc))

    click.echo(f"Input: {path}  ({kind}; Tesseract {ocr_mod.version()})")
    if not targets:
        click.echo("No pages to OCR — every page already has an embedded text layer. "
                   "Use --all-pages to OCR them anyway.")
        return

    try:
        if is_images:
            diags = [
                ocr_mod.diagnose_image_file(files[i - 1], lang=ocr_lang, psm=ocr_psm,
                                            save_dir=save_images, page=i)
                for i in targets
            ]
        else:
            diags = ocr_mod.diagnose(path, targets, dpi=ocr_dpi, lang=ocr_lang,
                                     psm=ocr_psm, save_dir=save_images)
    except ocr_mod.OcrError as exc:
        _fail(str(exc))

    low = 0
    for d in diags:
        label = f" [{labels[d.page]}]" if d.page in labels else ""
        layer_note = "" if (is_images or d.page in empty) else " (already has a text layer)"
        is_low = bool(d.word_count and d.mean_confidence < 60) or not d.text.strip()
        low += 1 if is_low else 0
        flag = "  [!] low confidence" if is_low else ""
        click.echo("")
        click.echo(f"-- Page {d.page}{label}{layer_note} -- confidence {d.mean_confidence:.1f}%, "
                   f"{d.word_count} word(s), strategy {d.strategy}{flag}")
        if d.image_path:
            click.echo(f"   image: {d.image_path}")
        snippet = d.text.strip()
        if not snippet:
            click.echo("   (no text recognised)")
        elif full_text:
            click.echo(snippet)
        else:
            preview = " ".join(snippet.split())
            click.echo("   " + (preview[:300] + (" ..." if len(preview) > 300 else "")))

    click.echo(f"\n{len(diags)} page(s) OCR'd, {low} low-confidence.")
    if not full_text:
        click.echo("Tip: add --full-text for complete text, or --save-images DIR to inspect what OCR saw.")


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
