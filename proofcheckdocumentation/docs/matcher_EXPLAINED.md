# `proofcheck/matcher.py` — Explained

> Deterministically classifies each expected spreadsheet value as EXACT / FUZZY / MISSING / SKIPPED against PDF page text, picking the best page and snippet and building a character-level diff.

## Purpose
This module is the deterministic matching core of ProofCheck. For a single expected value it normalizes the text, searches every PDF page for an exact substring hit, falls back to a rapidfuzz `partial_ratio` fuzzy score, and decides a `Status`. It also reconstructs the raw-text snippet that best aligns to the match and produces a `delete`/`insert` diff describing how the expected text differs from what was found. Nothing here uses AI/ML — `rapidfuzz` scoring and `difflib` are pure functions of their inputs, so results are reproducible.

## Dependencies
- **Imports (external):**
  - `difflib.SequenceMatcher` (stdlib) — produces the opcode-based character diff between expected and matched text.
  - `rapidfuzz.fuzz` — provides `partial_ratio` for the fuzzy 0–100 similarity score.
  - `rapidfuzz.fuzz.partial_ratio_alignment` — returns the source/dest index alignment of the best partial match so a snippet can be sliced out.
- **Imports (internal):** `proofcheck.models` (`DiffOp`, `MatchResult`, `Status`), `proofcheck.normalize` (`normalize`, `reverse_words`).
- **Used by:** `proofcheck/pipeline.py` (calls `match_value` per cell) and `tests/test_matcher.py`.

## Line-by-line / block-by-block breakdown

### Module docstring and imports

```python
from difflib import SequenceMatcher

from rapidfuzz import fuzz
from rapidfuzz.fuzz import partial_ratio_alignment

from .models import DiffOp, MatchResult, Status
from .normalize import normalize, reverse_words
```

The module docstring states the contract: per value decide EXACT / FUZZY / MISSING / SKIPPED, find the best page and snippet, build a character-level diff, all deterministically. `from __future__ import annotations` (above) defers annotation evaluation so `int | None`-style unions work on older runtimes.

### `_is_blank`

```python
def _is_blank(value: object) -> bool:
    return value is None or str(value).strip() == ""
```

Helper that treats `None` and whitespace-only values as "nothing to check". Used to route blank cells to `SKIPPED` before any normalization or scoring happens.

### `build_diff`

```python
def build_diff(expected: str, best_match: str) -> list[DiffOp]:
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
```

Computes a **character-level** diff (the `SequenceMatcher` operates over the strings character-by-character, comparing `a=expected` to `b=best_match`). `autojunk=False` disables difflib's heuristic that auto-marks frequently-repeated elements as "junk", which keeps the diff deterministic and faithful for short strings.

`get_opcodes()` yields tuples `(op, a1, a2, b1, b2)` describing how to turn `a` into `b`. The decomposition:
- **`equal`** → emit `("equal", expected[a1:a2])` (text unchanged between the two).
- **`delete`** → text exists in `expected` but not the match → `("delete", expected[a1:a2])`.
- **`insert`** → text exists in the match but not `expected` → `("insert", best_match[b1:b2])`.
- **`replace`** → a span differs on both sides. Rather than emit a `replace` op, it is **split into a `delete` of the expected span followed by an `insert` of the match span**. This lets any frontend render `<del>`/`<ins>` markup uniformly without special-casing a `replace` op. (`DiffOp` is the tuple type `(op, text)` defined in `models.py`; `replace` is reserved but never produced here.)

### `_adjacent_duplicate`

```python
def _adjacent_duplicate(cand: str, hay: str) -> str | None:
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
```

Detects a **duplicated trailing word** — typically a repeated surname — at a match site. `cand` is a normalized needle already known to occur in the normalized haystack `hay`. Both are split into word tokens; the function finds the run of `hay` tokens equal to `cand`, then walks forward while the following token keeps repeating `cand`'s **last** word. If at least one such repeat exists it returns the normalized `cand + repeated word(s)` string (e.g. `"jordan avery avery"`), otherwise `None`.

This is what makes a duplicated surname visible. A plain substring test treats `"jordan avery"` as found inside `"jordan avery avery"` and returns `EXACT`, silently accepting the extra word; `partial_ratio` doesn't help either because it scores by the *best-matching substring*, so trailing/duplicated text never lowers the score. Because an exact substring hit means `cand` appears contiguously, the only way a duplicate survives into this path is as a **trailing** repeat of the last word — an *internal* duplicate would break the contiguous match and already be scored as `FUZZY`. Token-based and fully deterministic — no scoring, no heuristics.

### `_best_snippet`

```python
def _best_snippet(needle_norm: str, haystack_raw: str, haystack_norm: str) -> str:
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
```

Recovers the slice of **raw** PDF page text that corresponds to the best fuzzy alignment so the user sees what actually appears in the PDF (with original casing/punctuation), not the normalized form.

Step by step:
1. If the normalized haystack is empty, return `""` (nothing to show).
2. `partial_ratio_alignment(needle_norm, haystack_norm)` returns an alignment object whose `dest_start`/`dest_end` index into the **normalized** haystack. If there is no alignment, return `""`.
3. Because normalization can change string length, the normalized indices cannot be applied to the raw text directly. A proportional `ratio = len(raw) / len(norm)` is computed and the normalized indices are scaled: `start = int(dest_start * ratio)`, `end = int(dest_end * ratio)`. This is an approximate index remapping — fine for displaying a readable snippet.
4. Return the stripped raw slice. If that ends up empty (e.g. the scaled slice landed on whitespace), it **falls back to the normalized slice** so the snippet is never silently blank.

### `match_value`

```python
def match_value(
    expected: object,
    pages: dict[int, str],
    *,
    fuzzy_threshold: int = 90,
    normalize_digits: bool = False,
    strip_punctuation: bool = False,
    reverse: bool = False,
    row: int = 0,
) -> MatchResult:
```

The public entry point: matches one expected value against all PDF pages and returns a `MatchResult`. `pages` maps 1-based page number → raw page text. The matching flags mirror `RunConfig` fields and are keyword-only.

**1. Blank short-circuit.**
```python
    if _is_blank(expected):
        return MatchResult(row=row, expected="" if expected is None else str(expected),
                            status=Status.SKIPPED)
```
Blank/`None` cells return `SKIPPED` immediately (page/score/diff left at defaults). `None` is rendered as `""` for `expected`.

**2. Normalize the needle and build candidate forms.**
```python
    expected_str = str(expected)
    norm_kwargs = dict(normalize_digits=normalize_digits, strip_punctuation=strip_punctuation)
    needle = normalize(expected_str, **norm_kwargs)

    needles = [needle]
    if reverse:
        rev = reverse_words(needle)
        if rev != needle:
            needles.append(rev)
```
The expected value is normalized once. If `reverse` is on, a word-order-swapped variant (e.g. "First Last" → "Last First") is added as a second candidate, but only if it actually differs from the original (avoids redundant scoring for single-word values).

**3. Scan every page for exact substring and best fuzzy score.**
```python
    best_page: int | None = None
    best_score = -1.0
    best_snippet = ""
    exact_page: int | None = None
    dup_page: int | None = None
    dup_snippet = ""  # raw PDF text of the name INCLUDING the duplicated word

    for page_num, raw in pages.items():
        hay = normalize(raw, **norm_kwargs)
        if not hay:
            continue
        for cand in needles:
            if cand and cand in hay:
                dup = _adjacent_duplicate(cand, hay)
                if dup is None:
                    if exact_page is None or page_num < exact_page:
                        exact_page = page_num
                elif dup_page is None or page_num < dup_page:
                    dup_page = page_num
                    dup_snippet = _best_snippet(dup, raw, hay)
            score = fuzz.partial_ratio(cand, hay)
            if score > best_score:
                best_score = score
                best_page = page_num
                best_snippet = _best_snippet(cand, raw, hay)
```
Each page's raw text is normalized to `hay` (empty pages skipped). For every candidate needle:
- **Exact substring test** (`cand in hay`): if the normalized needle is a literal substring of the normalized page, check it for a duplicated trailing word via `_adjacent_duplicate`. A **clean** hit records the page as an exact hit (earliest page kept). A hit **with a duplicated surname** instead records `dup_page` and the raw snippet that *includes* the extra word (`_best_snippet(dup, …)`), so it can later be surfaced as a difference rather than a clean match.
- **Fuzzy score**: `fuzz.partial_ratio(cand, hay)` gives a 0–100 score for the best substring-like alignment. The global best score, its page, and the recovered raw snippet (`_best_snippet`) are tracked. Note both candidates compete for the single best score across all pages.

`best_score` starts at `-1.0` so any real score (≥0) wins on the first comparison.

**4. A clean exact match wins outright.**
```python
    if exact_page is not None:
        return MatchResult(
            row=row, expected=expected_str, status=Status.EXACT,
            page=exact_page, best_match=expected_str, score=100, diff=[],
        )
```
If any page contained the needle verbatim (post-normalization) **without** a duplicated trailing word, return `EXACT` immediately: score is forced to `100`, `best_match` is the expected text itself, and the diff is empty. A clean occurrence anywhere takes priority — the value genuinely appears as written — even over a page that duplicates it and over a numerically higher partial score elsewhere.

**4b. A duplicated surname is surfaced as a difference.**
```python
    if dup_page is not None:
        dup_norm = normalize(dup_snippet, **norm_kwargs)
        return MatchResult(
            row=row, expected=expected_str, status=Status.FUZZY,
            page=dup_page, best_match=dup_snippet or None,
            score=int(round(fuzz.ratio(needle, dup_norm))),
            diff=build_diff(needle, dup_norm),
        )
```
If the value was only ever found immediately followed by a repeat of its last word, it is reported as `FUZZY` ("Found with differences") instead of `EXACT`. `best_match` is the raw PDF snippet **including** the duplicated word, the diff (`needle` vs the normalized duplicated snippet) highlights the extra word as an `insert`, and the score is `fuzz.ratio` of the expected value against the duplicated text (so it honestly reflects the extra token, e.g. ~75–80 rather than 100). This branch is reached before the generic fuzzy/missing classification below.

**5. Otherwise classify by fuzzy threshold and build the diff.**
```python
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
```
The float best score is rounded to an int (or `0` if no page produced a score). The diff compares the **normalized needle** against the **normalized best snippet** so it reflects the same comparison basis the score used. The status is `FUZZY` when `score_int >= fuzzy_threshold`, otherwise `MISSING`. `best_match` is the human-readable raw snippet (or `None` if none found).

## Functions / Methods / Classes

| Name | Signature | Returns | Description |
| --- | --- | --- | --- |
| `_is_blank` | `_is_blank(value: object) -> bool` | `bool` | True for `None` or whitespace-only values; routes cells to `SKIPPED`. |
| `build_diff` | `build_diff(expected: str, best_match: str) -> list[DiffOp]` | `list[DiffOp]` | Character-level diff (`equal`/`delete`/`insert`); decomposes `replace` into delete+insert. |
| `_adjacent_duplicate` | `_adjacent_duplicate(cand: str, hay: str) -> str \| None` | `str \| None` | Token-based detector for a duplicated trailing word (repeated surname) at a match site; returns the `cand + repeat(s)` text or `None`. |
| `_best_snippet` | `_best_snippet(needle_norm: str, haystack_raw: str, haystack_norm: str) -> str` | `str` | Maps the fuzzy alignment indices from normalized space back onto raw page text to slice a readable snippet. |
| `match_value` | `match_value(expected, pages, *, fuzzy_threshold=90, normalize_digits=False, strip_punctuation=False, reverse=False, row=0) -> MatchResult` | `MatchResult` | Classifies one expected value vs all PDF pages and returns the full per-cell result. |

## Key variables / constants

| Name | Purpose |
| --- | --- |
| `needle` | Normalized form of the expected value being searched for. |
| `needles` | Candidate forms to try (the needle, plus a reversed-word-order variant when `reverse=True`). |
| `exact_page` | Earliest page number containing the needle as a **clean** literal substring (no duplicated trailing word); drives `EXACT`. |
| `dup_page` | Earliest page where the needle is found but immediately followed by a repeat of its last word; drives the duplicated-surname `FUZZY` result. |
| `dup_snippet` | Raw PDF text of the matched name **including** the duplicated word; becomes `best_match` for the duplicated-surname case. |
| `best_page` | Page with the highest fuzzy `partial_ratio`. |
| `best_score` | Highest fuzzy score seen (initialized to `-1.0` so any real score wins). |
| `best_snippet` | Raw-text snippet aligned to the best fuzzy match; becomes `best_match`. |
| `score_int` | Best score rounded to an int (`0` if no score); compared against `fuzzy_threshold`. |
| `fuzzy_threshold` | Inclusive cutoff (0–100); `>=` this score = `FUZZY`, below = `MISSING`. |
| `norm_kwargs` | Shared normalization options (`normalize_digits`, `strip_punctuation`) applied to both needle and haystacks. |

## Notes / gotchas
- **Determinism:** No AI/ML. `rapidfuzz` scoring and `difflib` are deterministic pure functions; the same Excel value + PDF text always yields the same `MatchResult`. `SequenceMatcher(..., autojunk=False)` avoids difflib's nondeterministic-feeling junk heuristic.
- **Exact beats fuzzy:** A *clean* verbatim substring hit returns `EXACT` (score 100, empty diff) regardless of any higher fuzzy score elsewhere; the earliest such page wins.
- **Duplicated surname ≠ exact:** if the needle is found only where the PDF immediately repeats its last word (e.g. `JORDAN AVERY AVERY` for `JORDAN AVERY`), the result is `FUZZY` ("Found with differences") with the extra word highlighted, not a clean `EXACT`. A plain `cand in hay` test would otherwise hide it, since the clean name is still a perfect substring. A clean occurrence on any page still wins as `EXACT`. Only a *trailing* duplicate reaches this path — an internal duplicate breaks the contiguous substring and is scored as ordinary `FUZZY`.
- **Threshold semantics:** `score_int >= fuzzy_threshold` → `FUZZY`; otherwise `MISSING`. The comparison is on the rounded integer score, so the boundary is inclusive (default 90).
- **`replace` decomposition:** `build_diff` never emits a `replace` op — replacements are split into a `delete` of the expected span plus an `insert` of the match span so frontends render `<del>`/`<ins>` uniformly.
- **Alignment → snippet is approximate:** `_best_snippet` proportionally rescales normalized indices onto raw text; when normalization changes length the snippet bounds are an approximation, with a fallback to the normalized slice if the raw slice is empty.
- **Normalization basis:** the score, the exact test, and the diff all operate on normalized text, so behavior depends on the `normalize_digits` / `strip_punctuation` flags; the displayed snippet, however, is raw.
- **Comparison basis for diff:** the diff compares the normalized needle to the normalized snippet, not the raw strings, keeping it consistent with the score.

## v0.2 changes

`match_value` gained a `fold_diacritics` keyword, threaded into the `norm_kwargs` passed to `normalize()` for both the needle and each page haystack. No change to scoring/diff logic.

