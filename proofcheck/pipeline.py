"""Shared orchestration: the single entry point both the CLI and the web API call.

``run(RunConfig) -> RunResult`` does load-excel -> extract-pdf -> match -> assemble.
There is intentionally **no** duplicate of this glue anywhere else; cli.py and
web/app.py are thin wrappers around it. Keeping the signature stable also leaves the
door open for a future background-job runner (arq/RQ) to call it unchanged.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from . import document, excel, pdf
from .matcher import match_value
from .models import (
    ColumnResult,
    Meta,
    RunConfig,
    RunResult,
    Status,
    Summary,
)

# Progress callback: ``progress(stage, current, total)`` where ``stage`` is "extract"
# (OCR of no-text-layer pages) or "match" (checking values), and ``current``/``total`` are
# unit counts. It is called with ``current == total`` when a stage finishes, so a renderer
# can show a definite 100%/done state. Purely observational — it never affects the result,
# so a run with no callback behaves exactly as before.
ProgressFn = Callable[[str, int, int], None]


class PipelineError(Exception):
    """User-facing error raised when a run cannot proceed (bad input, no columns)."""


def _summarize(columns: list[ColumnResult]) -> Summary:
    summary = Summary()
    for col in columns:
        for r in col.results:
            summary.total += 1
            if r.status is Status.EXACT:
                summary.exact += 1
            elif r.status is Status.FUZZY:
                summary.fuzzy += 1
            elif r.status is Status.MISSING:
                summary.missing += 1
            elif r.status is Status.SKIPPED:
                summary.skipped += 1
    checked = summary.total - summary.skipped
    summary.pass_rate = round((summary.exact + summary.fuzzy) / checked, 4) if checked else 0.0
    return summary


def run(config: RunConfig, *, progress: ProgressFn | None = None) -> RunResult:
    """Execute one check run and return a fully-assembled :class:`RunResult`.

    ``progress`` is an optional observer (see :data:`ProgressFn`) notified as the OCR and
    matching stages advance, so a caller (e.g. the CLI) can render a progress bar. It has no
    effect on the result.
    """
    if not config.all_columns and not config.columns:
        raise PipelineError("No columns selected. Pass column names or enable all-columns.")

    # 1. Load the requested Excel columns.
    try:
        column_data = excel.load_columns(
            config.excel_path,
            sheet=config.sheet,
            header_row=config.header_row,
            columns=config.columns,
            all_columns=config.all_columns,
        )
    except excel.ExcelError as exc:
        raise PipelineError(str(exc)) from exc

    if not column_data:
        raise PipelineError("No columns to check were found on the sheet.")

    # 2. Extract page text from the input (PDF text layer, or OCR for image input).
    # OCR is the slow stage, so it reports per-page progress under the "extract" stage.
    ocr_progress = (lambda done, total: progress("extract", done, total)) if progress else None
    try:
        pdf_text = document.extract(
            config.pdf_path,
            ocr=config.ocr,
            ocr_dpi=config.ocr_dpi,
            ocr_lang=config.ocr_lang,
            ocr_psm=config.ocr_psm,
            use_cache=config.ocr_cache,
            progress=ocr_progress,
        )
    except pdf.PdfError as exc:
        raise PipelineError(str(exc)) from exc

    # 3. Match every value in every selected column.
    # Pages recovered via OCR, so each match can report whether it came from the embedded
    # text layer or from OCR.
    ocr_page_set = set(pdf_text.ocr_pages)
    total_values = sum(len(cd.cells) for cd in column_data)
    if progress:
        try:
            progress("match", 0, total_values)  # announce the stage even before the first result
        except Exception:
            pass
    columns: list[ColumnResult] = []
    for cd in column_data:
        col_result = ColumnResult(name=cd.name)
        for row_num, value in cd.cells:
            mr = match_value(
                value,
                pdf_text.pages,
                fuzzy_threshold=config.fuzzy_threshold,
                normalize_digits=config.normalize_digits,
                strip_punctuation=config.strip_punctuation,
                fold_diacritics=config.fold_diacritics,
                reverse=config.reverse,
                row=row_num,
            )
            if mr.page is not None:
                mr.source = "OCR" if mr.page in ocr_page_set else "text"
            col_result.results.append(mr)
            matched += 1
            if progress:
                progress("match", matched, total_values)
        columns.append(col_result)

    # 4. Assemble the result.
    summary = _summarize(columns)
    meta = Meta(
        excel=os.path.basename(config.excel_path),
        pdf=os.path.basename(config.pdf_path),
        timestamp=Meta.now_iso(),
        fuzzy_threshold=config.fuzzy_threshold,
        flags={
            "normalize_digits": config.normalize_digits,
            "strip_punctuation": config.strip_punctuation,
            "fold_diacritics": config.fold_diacritics,
            "reverse": config.reverse,
            "all_columns": config.all_columns,
            "ocr": config.ocr,
            "ocr_cache": config.ocr_cache,
        },
    )
    return RunResult(
        meta=meta,
        summary=summary,
        columns=columns,
        warnings=pdf_text.warnings(),
    )
