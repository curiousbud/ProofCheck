# `proofcheck/normalize.py` — Explained

> Provides deterministic, repeatable text-normalization transforms applied to both the expected Excel value and the PDF text before they are compared.

## Purpose
This module is the canonicalization layer that makes ProofCheck's matching fair and reproducible. It applies predictable Unicode-aware transforms — NFKC normalization, casefolding, whitespace collapse, and optional digit folding / punctuation stripping — so the same input and flags always yield the same output. It contains no fuzzy or AI logic; that lives in `matcher.py`, which calls these helpers to produce comparison forms.

## Dependencies
- **Imports (external):**
  - `from __future__ import annotations` — defers annotation evaluation for forward-compatible typing.
  - `re` — used to compile `_WS_RE`, the regex that collapses runs of whitespace.
  - `unicodedata` — provides `normalize("NFKC", ...)` for compatibility decomposition+composition, `digit(ch, None)` to map Unicode digits to their numeric value, and `category(ch)` to classify characters as punctuation/symbol.
- **Imports (internal):** None.
- **Used by:**
  - `proofcheck/matcher.py` (imports `normalize`, `reverse_words`)
  - `tests/test_normalize.py` (imports `fold_digits`, `normalize`, `reverse_words`, `strip_punct`)

## Line-by-line / block-by-block breakdown

### Module docstring
```python
"""Deterministic text normalization.

No fuzzy/AI logic lives here — just predictable, repeatable transforms ...
"""
```
Declares the module's contract: deterministic transforms applied to both sides of a comparison, with identical output for identical input + flags.

### Imports and the whitespace regex
```python
from __future__ import annotations

import re
import unicodedata

# Collapse any run of unicode whitespace to a single ASCII space.
_WS_RE = re.compile(r"\s+")
```
`_WS_RE` is a module-level compiled regex matching one-or-more whitespace characters. With `re.UNICODE` semantics (the default for `str` patterns in Python 3), `\s` matches Unicode whitespace, so any run of tabs/newlines/non-breaking-ish whitespace collapses to a single ASCII space when substituted later. Compiling once at module load avoids recompiling on every call.

### `fold_digits`
```python
def fold_digits(text: str) -> str:
    """Map every unicode decimal digit (Arabic-Indic, Devanagari, fullwidth, …) to ASCII 0-9."""
    out = []
    for ch in text:
        if ch.isdigit():
            digit = unicodedata.digit(ch, None)
            out.append(str(digit) if digit is not None else ch)
        else:
            out.append(ch)
    return "".join(out)
```
Walks each character. For characters where `ch.isdigit()` is true, it asks `unicodedata.digit(ch, None)` for the integer value of that digit; the `None` default means "return None instead of raising" for characters that report as digit-like but have no decimal value. If a numeric value is found, the ASCII string form (`str(digit)`) is appended; otherwise the original character is kept. Non-digit characters pass through unchanged. The accumulated list is joined into the result string. This folds Arabic-Indic, Devanagari, fullwidth, and other Unicode digits into plain `0`–`9`.

### `strip_punct`
```python
def strip_punct(text: str) -> str:
    """Remove unicode punctuation and symbol characters, replacing them with a space."""
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        # P* = punctuation, S* = symbols
        out.append(" " if cat[0] in ("P", "S") else ch)
    return "".join(out)
```
For each character, `unicodedata.category(ch)` returns a two-letter Unicode general category (e.g. `Po`, `Sm`, `Ll`). The code inspects only the first letter (`cat[0]`): category groups starting with `P` (all punctuation classes) or `S` (all symbol classes) are replaced with a space; everything else is kept. Replacing with a space (rather than deleting) preserves word boundaries so that, e.g., `"a-b"` becomes `"a b"` rather than `"ab"`. The resulting spaces are later collapsed by `normalize`.

### `normalize`
```python
def normalize(
    text: str,
    *,
    normalize_digits: bool = False,
    strip_punctuation: bool = False,
) -> str:
    """Return a canonical comparison form of ``text``. ..."""
    if text is None:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    if normalize_digits:
        text = fold_digits(text)
    if strip_punctuation:
        text = strip_punct(text)
    text = text.casefold()
    text = _WS_RE.sub(" ", text).strip()
    return text
```
The central canonicalizer. Notable points:
- The two flags are keyword-only (`*` in the signature), forcing callers to name `normalize_digits=`/`strip_punctuation=` explicitly.
- Despite the `text: str` annotation, the body guards `if text is None: return ""`, so `None` inputs (e.g. blank cells) become an empty string rather than raising.
- `str(text)` coerces non-string inputs (numbers, dates from Excel) to text before `unicodedata.normalize("NFKC", ...)` applies compatibility normalization — folding ligatures, fullwidth forms, etc., into canonical equivalents.
- Digit folding and punctuation stripping run only if their flags are set, and in that order (digits before punctuation).
- `text.casefold()` does aggressive, locale-independent lowercasing for case-insensitive comparison (stronger than `.lower()`).
- `_WS_RE.sub(" ", text).strip()` collapses every whitespace run to a single space and trims leading/trailing whitespace.

The order matters: NFKC → optional digit fold → optional punct strip → casefold → whitespace collapse/trim. Casefolding after punctuation stripping ensures the inserted spaces are also normalized by the final whitespace pass.

### `reverse_words`
```python
def reverse_words(text: str) -> str:
    """Reverse word order, e.g. 'john smith' -> 'smith john'. Used for reverse matching."""
    return " ".join(reversed(text.split()))
```
Splits on whitespace (`text.split()` with no args splits on any whitespace and drops empties), reverses the resulting token list, and rejoins with single spaces. Supports the `reverse` matching flag so a name like "John Smith" can also match "Smith John".

## Functions / Methods / Classes

| Name | Signature | Returns | Description |
| --- | --- | --- | --- |
| `fold_digits` | `fold_digits(text: str) -> str` | `str` | Maps every Unicode decimal digit to its ASCII `0`–`9` equivalent; non-digits unchanged. |
| `strip_punct` | `strip_punct(text: str) -> str` | `str` | Replaces all Unicode punctuation (`P*`) and symbol (`S*`) characters with a space. |
| `normalize` | `normalize(text: str, *, normalize_digits: bool = False, strip_punctuation: bool = False) -> str` | `str` | Returns the canonical comparison form: NFKC, optional digit fold, optional punct strip, casefold, whitespace collapse/trim. |
| `reverse_words` | `reverse_words(text: str) -> str` | `str` | Reverses word order, joining tokens with single spaces. |

## Key variables / constants

| Name | Purpose |
| --- | --- |
| `_WS_RE` | Module-level compiled regex `\s+` used to collapse any run of Unicode whitespace into a single ASCII space. |
| `out` (local, in `fold_digits`/`strip_punct`) | Accumulator list of per-character outputs, joined into the result string. |
| `digit` (local, in `fold_digits`) | Numeric value returned by `unicodedata.digit(ch, None)`; `None` when the char has no decimal value. |
| `cat` (local, in `strip_punct`) | Two-letter Unicode general category from `unicodedata.category(ch)`; only `cat[0]` is inspected. |

## Notes / gotchas
- **Determinism:** Every transform is pure and side-effect-free; given the same input string and flags the output is byte-for-byte identical, upholding ProofCheck's no-AI guarantee.
- **`None` handling:** `normalize(None)` returns `""` despite the `str` type hint — important for blank Excel cells. The standalone helpers (`fold_digits`, `strip_punct`, `reverse_words`) do **not** guard against `None` and will raise on it.
- **Non-string coercion:** `normalize` calls `str(text)`, so numbers/dates are stringified using their default Python repr before normalization — Excel numeric formatting nuances are not applied here.
- **Transform order is significant:** NFKC first (so subsequent steps see canonical forms), punctuation→space before casefold, and whitespace collapse last (so spaces introduced by `strip_punct` are squeezed/trimmed).
- **Punctuation becomes a space, not nothing:** This deliberately preserves token boundaries; combined with the final whitespace collapse it avoids accidentally gluing words together.
- **`fold_digits` guards `None` from `unicodedata.digit`:** Characters that satisfy `ch.isdigit()` but lack a decimal value (rare) are kept as-is rather than crashing.
- **`casefold` vs `lower`:** `casefold` is used for more aggressive, internationally correct case-insensitive matching (e.g. German ß → ss).

## v0.2 changes

Added a `fold_diacritics` option and a `fold_diacritics(text)` helper (NFKD-decompose, drop combining marks) so accented forms (cafe vs cafe) compare equal. `normalize()` gained the `fold_diacritics` keyword; an internal `_fold_diacritics` alias is used inside `normalize` because the keyword shadows the public function name. Digit folding already covered all unicode scripts.

