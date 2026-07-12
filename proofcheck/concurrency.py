"""Shared helpers for optional, deterministic parallelism.

Parallelism here only changes *how fast* a run completes, never *what* it produces.
Every parallel path returns results in their original input order and each unit of work
(matching one value, OCR'ing one page) is a pure function of its input, so
same-input-same-output holds for any worker count — ProofCheck's determinism guarantee is
untouched.

Threads (not processes) because the hot inner functions release the GIL: rapidfuzz scoring
runs in C, and Tesseract OCR shells out to a separate binary. Threads get real speedup there
without the pickling/spawn cost — and without forcing every argument (PIL images, page dicts)
to be picklable.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")

# Auto mode stays modest: past a handful of threads the shared work (Tesseract processes,
# memory bandwidth) stops scaling, and a runaway thread count just adds contention.
_MAX_AUTO_WORKERS = 8
# Explicit mode needs a hard cap too: web/API callers could otherwise request thousands of
# threads and exhaust local or server resources.
_MAX_REQUESTED_WORKERS = 64


def resolve_workers(requested: int, n_items: int) -> int:
    """Resolve an effective worker count for ``n_items`` units of work.

    ``requested`` semantics: ``0`` -> auto (a modest cap derived from CPU count), ``1`` ->
    force sequential, ``N`` -> at most ``N`` (capped to a safe maximum). The result never
    exceeds ``n_items`` (idle threads help nobody) and is always at least 1.
    """
    if n_items <= 1:
        return 1
    if requested and requested > 0:
        return max(1, min(requested, _MAX_REQUESTED_WORKERS, n_items))
    cpu = os.cpu_count() or 1
    return max(1, min(cpu, _MAX_AUTO_WORKERS, n_items))


def ordered_map(fn: Callable[[T], R], items: Iterable[T], *, workers: int) -> list[R]:
    """Apply ``fn`` to every item and return the results in input order.

    Runs inline (no pool, no thread overhead) when ``workers <= 1`` or there is at most one
    item; otherwise fans the work out over a :class:`ThreadPoolExecutor`. Either way the
    returned list is ordered to match ``items``, so callers get deterministic output without
    caring whether it ran in parallel.
    """
    materialized = list(items)
    if workers <= 1 or len(materialized) <= 1:
        return [fn(x) for x in materialized]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(fn, materialized))
