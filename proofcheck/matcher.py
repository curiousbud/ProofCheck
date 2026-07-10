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


def _adjacent_duplicate(cand: str, hay: str) -> str | None:
    """Detect a duplicated trailing word (e.g. a repeated surname) at a match site.

    ``cand`` is a normalized needle that occurs verbatim in ``hay``. If the run of
    words matching ``cand`` is *immediately followed* by one or more repeats of its
    last word, return the normalized ``cand + repeated word(s)`` text (e.g.
    ``"jordan avery avery"``); otherwise return ``None``.

    This is what makes a duplicated surname visible: a plain substring test treats
    ``"jordan avery"`` as found inside ``"jordan avery avery"`` and reports EXACT,
    hiding the extra word. Token-based and deterministic — no scoring, no heuristics.
    """
    n = cand.split()
    h = hay.split()
    if not n:
        return None
    span = len(n)
    for i in range(len(h) - span + 1):
        if h[i:i + span] == n:
            j = i + span
            while j < len(h) and h[j] == n[-1]:
                j += 1
            if j > i + span:
                return " ".join(h[i:j])
    return None


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


def normalize_pages(
    pages: dict[int, str],
    *,
    normalize_digits: bool = False,
    strip_punctuation: bool = False,
    fold_diacritics: bool = False,
) -> dict[int, str]:
    """Pre-normalize every page's text once, for reuse across many :func:`match_value` calls.

    Page normalization depends only on the run-wide flags, not on the expected value, so
    it is identical for every value checked in a run. Computing it once here and passing
    the result into ``match_value(..., pages_norm=...)`` avoids re-normalizing the full text
    of every page for every single value — the difference between a run finishing in
    seconds and one that appears to hang on a large spreadsheet + multi-page PDF.
    """
    return {
        page_num: normalize(
            raw,
            normalize_digits=normalize_digits,
            strip_punctuation=strip_punctuation,
            fold_diacritics=fold_diacritics,
        )
        for page_num, raw in pages.items()
    }


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
    pages_norm: dict[int, str] | None = None,
) -> MatchResult:
    """Match a single expected value against all PDF pages.

    ``pages_norm`` is an optional map of ``{page_num: normalized_text}`` produced by
    :func:`normalize_pages` with the same flags. When supplied it is reused verbatim so the
    expensive page normalization runs once per run instead of once per value; when omitted
    (e.g. a standalone/test call) each page is normalized inline as before.
    """
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
    dup_page: int | None = None
    dup_snippet = ""  # raw PDF text of the name INCLUDING the duplicated word

    for page_num, raw in pages.items():
        hay = pages_norm[page_num] if pages_norm is not None else normalize(raw, **norm_kwargs)
        if not hay:
            continue
        for cand in needles:
            if cand and cand in hay:
                dup = _adjacent_duplicate(cand, hay)
                if dup is None:
                    # Clean exact substring hit — record the earliest page.
                    if exact_page is None or page_num < exact_page:
                        exact_page = page_num
                elif dup_page is None or page_num < dup_page:
                    # Found, but the PDF repeats a trailing word (e.g. a duplicated
                    # surname). Keep the raw snippet so the report shows the extra text.
                    dup_page = page_num
                    dup_snippet = _best_snippet(dup, raw, hay)
            score = fuzz.partial_ratio(cand, hay)
            if score > best_score:
                best_score = score
                best_page = page_num
                best_snippet = _best_snippet(cand, raw, hay)

    # A clean match anywhere wins: the value genuinely appears verbatim.
    if exact_page is not None:
        return MatchResult(
            row=row, expected=expected_str, status=Status.EXACT,
            page=exact_page, best_match=expected_str, score=100, diff=[],
        )

    # Otherwise, if the only match had a duplicated trailing word, surface it as a
    # difference ("Found with differences") with a diff that highlights the extra word.
    if dup_page is not None:
        dup_norm = normalize(dup_snippet, **norm_kwargs)
        return MatchResult(
            row=row, expected=expected_str, status=Status.FUZZY,
            page=dup_page, best_match=dup_snippet or None,
            score=int(round(fuzz.ratio(needle, dup_norm))),
            diff=build_diff(needle, dup_norm),
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
