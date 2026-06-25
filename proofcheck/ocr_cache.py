"""Content-addressed cache for OCR results — never OCR the same file twice.

OCR (render + Tesseract) is the slowest part of a run. Because it is deterministic — the
same PDF bytes at the same DPI/language always yield the same text — the result can be
safely cached keyed by a **SHA-256 of the file's content**.

That content hash is also the *change detector* the feature needs: re-uploading the **same**
file produces the same hash → cache hit → no OCR (the engine isn't even needed). A file
whose data changed produces a **different** hash → cache miss → it is OCR'd fresh. So
"detect whether the upload changed" falls out of content-addressing for free.

Entries are small JSON files under ``$PROOFCHECK_OCR_CACHE`` (default
``<tempdir>/proofcheck/ocr_cache``). Set ``PROOFCHECK_OCR_CACHE=off`` (or ``0``/``false``)
to disable caching entirely. The cache is best-effort: any I/O error degrades to "no cache".
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

_DISABLED_VALUES = {"", "0", "off", "false", "no"}


def cache_dir() -> Path | None:
    """Resolve the cache directory, or ``None`` when caching is disabled."""
    val = os.environ.get("PROOFCHECK_OCR_CACHE")
    if val is not None:
        if val.strip().lower() in _DISABLED_VALUES:
            return None
        return Path(val)
    return Path(tempfile.gettempdir()) / "proofcheck" / "ocr_cache"


def enabled() -> bool:
    return cache_dir() is not None


def file_sha256(path: str, *, chunk: int = 1 << 20) -> str:
    """Stream a SHA-256 of the file's bytes (the content fingerprint / change key)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _entry_path(directory: Path, digest: str, dpi: int, lang: str) -> Path:
    # DPI and language change OCR output, so they are part of the key.
    safe_lang = "".join(c for c in lang if c.isalnum() or c in "+-_") or "eng"
    return directory / f"{digest}.{dpi}.{safe_lang}.json"


def load(digest: str, *, dpi: int, lang: str) -> dict[int, str] | None:
    """Return cached ``{page: text}`` for this content+dpi+lang, or ``None`` on miss."""
    directory = cache_dir()
    if directory is None:
        return None
    try:
        with open(_entry_path(directory, digest, dpi, lang), encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return None
    # JSON object keys are strings; restore int page numbers.
    return {int(k): v for k, v in raw.items()}


def store(digest: str, *, dpi: int, lang: str, pages: dict[int, str]) -> None:
    """Persist ``{page: text}`` for this content+dpi+lang. Best-effort (never raises)."""
    directory = cache_dir()
    if directory is None:
        return
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = _entry_path(directory, digest, dpi, lang)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({str(k): v for k, v in pages.items()}, fh)
        os.replace(tmp, path)  # atomic publish so readers never see a half-written file
    except OSError:
        pass
