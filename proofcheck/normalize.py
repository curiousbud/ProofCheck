"""Deterministic text normalization.

No fuzzy/AI logic lives here — just predictable, repeatable transforms applied to
both the expected (Excel) value and the PDF text before comparison. Given the same
input and flags this always yields the same output.
"""

from __future__ import annotations

import re
import unicodedata

# Collapse any run of unicode whitespace to a single ASCII space.
_WS_RE = re.compile(r"\s+")


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


def strip_punct(text: str) -> str:
    """Remove unicode punctuation and symbol characters, replacing them with a space."""
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        # P* = punctuation, S* = symbols
        out.append(" " if cat[0] in ("P", "S") else ch)
    return "".join(out)


def normalize(
    text: str,
    *,
    normalize_digits: bool = False,
    strip_punctuation: bool = False,
) -> str:
    """Return a canonical comparison form of ``text``.

    Baseline (always applied): NFKC unicode normalization, casefold (case-insensitive),
    and whitespace collapse/trim. Optional: digit folding and punctuation stripping.
    """
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


def reverse_words(text: str) -> str:
    """Reverse word order, e.g. 'john smith' -> 'smith john'. Used for reverse matching."""
    return " ".join(reversed(text.split()))
