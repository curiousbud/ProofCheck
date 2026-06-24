# `tests/test_normalize.py` — Explained

> Unit tests for `proofcheck.normalize`, covering casefolding/whitespace collapse, determinism, Unicode digit folding, punctuation stripping, word reversal, and `None` handling.

## Purpose
These tests pin down the text-normalization helpers that the matcher relies on to compare Excel values against PDF text. They verify each public function (`normalize`, `fold_digits`, `reverse_words`, `strip_punct`) behaves deterministically and handles the tricky cases (Arabic-Indic digits, punctuation, `None`). Because matching is deterministic, normalization must be too.

## Dependencies
- **Imports (external):** None (pure unit tests; `pytest` is the runner but is not imported here).
- **Imports (internal):** `proofcheck.normalize` — `fold_digits`, `normalize`, `reverse_words`, `strip_punct`.
- **Used by:** Run by pytest. Uses no shared fixtures from `conftest.py`.

## Line-by-line / block-by-block breakdown

### Import
```python
from proofcheck.normalize import fold_digits, normalize, reverse_words, strip_punct
```
Pulls in the four functions under test.

### `test_baseline_casefold_and_whitespace`
```python
def test_baseline_casefold_and_whitespace():
    assert normalize("  John   SMITH ") == "john smith"
```
Verifies the default `normalize` lowercases (casefolds) and collapses leading/trailing/internal runs of whitespace to single spaces. `"  John   SMITH "` → `"john smith"`.

### `test_normalize_is_deterministic`
```python
def test_normalize_is_deterministic():
    a = normalize("Café  Núñez", normalize_digits=True, strip_punctuation=True)
    b = normalize("Café  Núñez", normalize_digits=True, strip_punctuation=True)
    assert a == b
```
Calls `normalize` twice with identical input and flags and asserts equal output. Guards against any nondeterminism (e.g., set ordering) in the Unicode/punctuation path; required because the whole tool is deterministic by design.

### `test_fold_digits_arabic_indic`
```python
def test_fold_digits_arabic_indic():
    # Arabic-Indic digits ١٢٣ -> 123
    assert fold_digits("١٢٣") == "123"
```
Asserts `fold_digits` maps Arabic-Indic numerals (U+0661 etc.) to ASCII `"123"`, so numeric codes match regardless of the original digit script.

### `test_normalize_digits_flag`
```python
def test_normalize_digits_flag():
    assert normalize("Room ١٠", normalize_digits=True) == "room 10"
    # Without the flag, digits are left as-is.
    assert normalize("Room ١٠", normalize_digits=False) != "room 10"
```
Confirms the `normalize_digits` flag controls digit folding: with it on, `"Room ١٠"` → `"room 10"`; with it off, the Arabic-Indic digits are preserved, so the result is NOT `"room 10"`.

### `test_strip_punct_replaces_with_space`
```python
def test_strip_punct_replaces_with_space():
    assert "cc 101" in normalize("CC-101", strip_punctuation=True)
    assert "-" not in strip_punct("CC-101")
```
Verifies punctuation handling: with `strip_punctuation=True`, the hyphen in `"CC-101"` becomes a space so `"cc 101"` is a substring of the normalized output. The second assert checks `strip_punct` directly removes the hyphen (no `"-"` remains). Note punctuation is replaced by a space rather than deleted (so tokens stay separated).

### `test_reverse_words`
```python
def test_reverse_words():
    assert reverse_words("john smith") == "smith john"
    assert reverse_words("madonna") == "madonna"
```
Confirms `reverse_words` swaps the order of space-separated tokens (`"john smith"` → `"smith john"`) — the mechanism behind reverse name matching — and that a single token is returned unchanged.

### `test_none_is_empty`
```python
def test_none_is_empty():
    assert normalize(None) == ""
```
Ensures `normalize(None)` returns the empty string rather than raising, so blank Excel cells flow through to a SKIPPED status downstream instead of crashing.

## Fixtures / Tests / Sections

| Name | What it verifies |
| --- | --- |
| `test_baseline_casefold_and_whitespace` | Default normalize casefolds and collapses whitespace. |
| `test_normalize_is_deterministic` | Same input + flags yields identical output. |
| `test_fold_digits_arabic_indic` | Arabic-Indic digits fold to ASCII `123`. |
| `test_normalize_digits_flag` | `normalize_digits` flag toggles digit folding on/off. |
| `test_strip_punct_replaces_with_space` | Punctuation becomes a space; `strip_punct` removes hyphens. |
| `test_reverse_words` | Reverses token order; single token unchanged. |
| `test_none_is_empty` | `normalize(None)` returns `""`. |

## Notes / gotchas
- **Determinism is a first-class property** here (`test_normalize_is_deterministic`); the matcher and pipeline assume normalization is stable.
- **Punctuation is replaced with a space, not deleted**, preserving token boundaries (e.g., `CC-101` → `cc 101`).
- **`None` safety** lets blank cells become SKIPPED rather than errors.
- These are pure unit tests with no I/O and no shared fixtures, so they are fast and isolated.
