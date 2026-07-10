"""Shared orchestration: the single entry point both the CLI and the web API call.

``run(RunConfig) -> RunResult`` does load-excel -> extract-pdf -> match -> assemble.
There is intentionally **no** duplicate of this glue anywhere else; cli.py and
web/app.py are thin wrappers around it. Keeping the signature stable also leaves the
door open for a future background-job runner (arq/RQ) to call it unchanged.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable

from . import document, excel, pdf
from .concurrency import ordered_map, resolve_workers
from .matcher import match_value, normalize_pages
from .models import (
    ColumnResult,
    Meta,
    RunConfig,
    RunResult,
    Status,
    Summary,
)

# Progress callback: ``progress(stage, current, total)`` where ``stage`` is "extract"
# (reading the PDF text layer + any OCR of no-text-layer pages) or "match" (checking values),
# and ``current``/``total`` are unit counts. It is called with ``current == total`` when a
# stage finishes, so a renderer can show a definite 100%/done state. Purely observational — it
# never affects the result, so a run with no callback behaves exactly as before.
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

    ``progress`` is an optional observer (see :data:`ProgressFn`) notified as the extraction
    and matching stages advance, so a caller (e.g. the CLI or the web stream) can render a
    progress bar. It has no effect on the result.
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
    # Extraction (text layer + any OCR) is the slow stage on large/scanned PDFs, so it reports
    # per-page progress under the "extract" stage; OCR of no-text-layer pages fans out over
    # ``config.workers``.
    ocr_progress = (lambda done, total: progress("extract", done, total)) if progress else None
    try:
        pdf_text = document.extract(
            config.pdf_path,
            ocr=config.ocr,
            ocr_dpi=config.ocr_dpi,
            ocr_lang=config.ocr_lang,
            ocr_psm=config.ocr_psm,
            use_cache=config.ocr_cache,
            workers=config.workers,
            progress=ocr_progress,
        )
    except pdf.PdfError as exc:
        raise PipelineError(str(exc)) from exc

    # 3. Match every value in every selected column.
    ocr_page_set = set(pdf_text.ocr_pages)

    # Normalize each page's text ONCE for the whole run. The normalization depends only on
    # the run-wide flags, so it is identical for every value; doing it here instead of inside
    # match_value turns an O(values x pages) pass over the full PDF text into an O(pages) one.
    pages_norm = normalize_pages(
        pdf_text.pages,
        normalize_digits=config.normalize_digits,
        strip_punctuation=config.strip_punctuation,
        fold_diacritics=config.fold_diacritics,
    )

    # Flatten to (column_index, row, value) tasks so results can be reassembled by position.
    # Every value is an independent, pure match against the same pages, so the work fans out
    # over a thread pool (rapidfuzz releases the GIL) and is reassembled in the original
    # column/row order — output is identical regardless of ``config.workers``.
    tasks = [
        (col_idx, row_num, value)
        for col_idx, cd in enumerate(column_data)
        for row_num, value in cd.cells
    ]
    total_values = len(tasks)
    if progress:
        progress("match", 0, total_values)  # announce the stage even before the first result

    # A lock-guarded counter so progress still advances monotonically (1, 2, ... total) even
    # when matches complete out of order across worker threads.
    matched = 0
    progress_lock = threading.Lock()

    def _match_task(task: tuple[int, int, object]):
        nonlocal matched
        col_idx, row_num, value = task
        mr = match_value(
            value,
            pdf_text.pages,
            fuzzy_threshold=config.fuzzy_threshold,
            normalize_digits=config.normalize_digits,
            strip_punctuation=config.strip_punctuation,
            fold_diacritics=config.fold_diacritics,
            reverse=config.reverse,
            row=row_num,
            pages_norm=pages_norm,
        )
        if mr.page is not None:
            mr.source = "OCR" if mr.page in ocr_page_set else "text"
        if progress:
            with progress_lock:
                matched += 1
                done = matched
            progress("match", done, total_values)
        return col_idx, mr

    workers = resolve_workers(config.workers, total_values)
    columns = [ColumnResult(name=cd.name) for cd in column_data]
    for col_idx, mr in ordered_map(_match_task, tasks, workers=workers):
        columns[col_idx].results.append(mr)

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
