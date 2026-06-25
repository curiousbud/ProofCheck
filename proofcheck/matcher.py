"""Deterministic matching of expected values against PDF text.

For each expected value we decide EXACT / FUZZY / MISSING / SKIPPED, find the best
page and snippet, and build a character-level diff. Everything here is deterministic:
rapidfuzz scoring is a pure function of its inputs, and difflib is stdlib.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from rapidfuzz import fuzz
from rapidfuzz.fuzz import partial_ratio_alignment

from .models import DiffOp, MatchResult, Status
from .normalize import normalize, reverse_words


def _is_blank(value: object) -> bool:
    return value is None or str(value).strip() == ""


def build_diff(expected: str, best_match: str) -> list[DiffOp]:
    """Character-level diff describing how to turn ``expected`` into ``best_match``.

    Emits ``equal`` / ``delete`` / ``insert`` pairs. ``replace`` spans are decomposed
    into a delete (of the expected text) followed by an insert (of the match text) so
    any frontend can render <del>/<ins> without special-casing replace.
    """
    sm = SequenceMatcher(a=expected, b=best_match, autojunk=False)
    diff: list[DiffOp] = []
    for op, a1, a2, b1, b2 in sm.get_opcodes():
        if op == "equal":
            diff.append(("equal", expected[a1:a2]))
        elif op == "delete":
            diff.append(("delete", expected[a1:a2]))
        elif op == "insert":
            diff.append(("insert", best_match[b1:b2]))
        elif op == "replace":
            diff.append(("delete", expected[a1:a2]))
            diff.append(("insert", best_match[b1:b2]))
    return diff


def _best_snippet(needle_norm: str, haystack_raw: str, haystack_norm: str) -> str:
    """Return the slice of the raw page text aligned to the best fuzzy match.

    rapidfuzz alignment indexes into the normalized haystack; since normalization can
    change length, we proportionally map those indices back onto the raw text so the
    snippet shown to the user reflects what's actually in the PDF.
    """
    if not haystack_norm:
        return ""
    align = partial_ratio_alignment(needle_norm, haystack_norm)
    if align is None:
        return ""
    n = len(haystack_norm)
    ratio = len(haystack_raw) / n if n else 1.0
    start = int(align.dest_start * ratio)
    end = int(align.dest_end * ratio)
    return haystack_raw[start:end].strip() or haystack_norm[align.dest_start:align.dest_end]


def match_value(
    expected: object,
    pages: dict[int, str],
    *,
    fuzzy_threshold: int = 90,
    normalize_digits: bool = False,
    strip_punctuation: bool = False,
    fold_diacritics: bool = False,
    reverse: bool = False,
    row: int = 0,
) -> MatchResult:
    """Match a single expected value against all PDF pages."""
    if _is_blank(expected):
        return MatchResult(row=row, expected="" if expected is None else str(expected),
                            status=Status.SKIPPED)

    expected_str = str(expected)
    norm_kwargs = dict(
        normalize_digits=normalize_digits,
        strip_punctuation=strip_punctuation,
        fold_diacritics=fold_diacritics,
    )
    needle = normalize(expected_str, **norm_kwargs)

    # The candidate forms we'll try; reverse adds the swapped-word-order variant.
    needles = [needle]
    if reverse:
        rev = reverse_words(needle)
        if rev != needle:
            needles.append(rev)

    best_page: int | None = None
    best_score = -1.0
    best_snippet = ""
    exact_page: int | None = None

    for page_num, raw in pages.items():
        hay = normalize(raw, **norm_kwargs)
        if not hay:
            continue
        for cand in needles:
            if cand and cand in hay:
                # Exact substring hit — record the earliest page and stop refining.
                if exact_page is None or page_num < exact_page:
                    exact_page = page_num
            score = fuzz.partial_ratio(cand, hay)
            if score > best_score:
                best_score = score
                best_page = page_num
                best_snippet = _best_snippet(cand, raw, hay)

    if exact_page is not None:
        return MatchResult(
            row=row, expected=expected_str, status=Status.EXACT,
            page=exact_page, best_match=expected_str, score=100, diff=[],
        )

    score_int = int(round(best_score)) if best_score >= 0 else 0
    diff = build_diff(needle, normalize(best_snippet, **norm_kwargs)) if best_snippet else []

    if score_int >= fuzzy_threshold:
        status = Status.FUZZY
    else:
        status = Status.MISSING

    return MatchResult(
        row=row, expected=expected_str, status=status,
        page=best_page, best_match=best_snippet or None, score=score_int, diff=diff,
    )
