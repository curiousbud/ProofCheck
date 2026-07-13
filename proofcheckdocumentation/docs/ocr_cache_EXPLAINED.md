# `proofcheck/ocr_cache.py` — Explained

> Content-addressed cache so an unchanged file is never OCR'd twice. The SHA-256 of the file's bytes is both the cache key and the "did this upload change?" detector.

## Purpose
OCR (render + Tesseract) is the slowest part of a run. Because OCR is deterministic — the same PDF bytes at the same DPI/language always produce the same text — the result can be cached safely. This module caches `{page: text}` keyed by `sha256(file) + dpi + lang`. A re-uploaded **identical** file is a cache hit (no OCR, the engine isn't even needed); a file whose data **changed** hashes differently → cache miss → it is OCR'd fresh and stored. So change-detection falls out of content-addressing for free.

## Dependencies
- **External:** `hashlib`, `json`, `os`, `tempfile`, `pathlib.Path` (all stdlib).
- **Internal:** none (leaf).
- **Used by:** `proofcheck/pdf.py` (`_apply_ocr` consults the cache before invoking OCR).

## Configuration
- `PROOFCHECK_OCR_CACHE` — cache directory. Unset → `<tempdir>/proofcheck/ocr_cache`.
  Set to `off`/`0`/`false`/`no`/empty → caching disabled.

## Functions

| Name | Signature | Description |
| --- | --- | --- |
| `cache_dir` | `cache_dir() -> Path \| None` | Resolve dir from env, or `None` when disabled. |
| `enabled` | `enabled() -> bool` | Whether caching is on. |
| `file_sha256` | `file_sha256(path, *, chunk=1<<20) -> str` | Streamed content hash (the change key). |
| `load` | `load(digest, *, dpi, lang) -> dict[int,str] \| None` | Cached pages, or `None` on miss/disabled. |
| `store` | `store(digest, *, dpi, lang, pages) -> None` | Persist pages (best-effort, atomic). |

## Line-by-line notes
- **Key includes dpi + lang** (`_entry_path`) because both change OCR output; `lang` is
  sanitized to keep the filename safe (e.g. `eng+ara` is fine, odd chars are stripped).
- **`load`** reads the JSON entry and converts string keys back to `int` page numbers; any
  `OSError`/`ValueError` (missing/corrupt entry) returns `None` — a clean miss.
- **`store`** writes to a `.tmp` sibling then `os.replace()`s it into place, so a concurrent
  reader never sees a half-written file. All errors are swallowed: the cache is an
  optimization and must never fail a run.

## Notes / gotchas
- **Determinism preserved:** caching only ever returns text that OCR itself would have
  produced for those exact bytes, so cached and fresh runs are identical.
- **Works for CLI and web:** it lives in the core, so both benefit. In the web flow uploads
  are deleted after each run, but the *content hash* persists, so re-uploading the same PDF
  still hits the cache.
- **Engine not required on a hit:** a cached file is recovered even if Tesseract is missing.
- **Privacy:** entries contain OCR'd page text keyed by an opaque hash. Point
  `PROOFCHECK_OCR_CACHE` at a private/ephemeral location, or set it `off`, if that matters.
