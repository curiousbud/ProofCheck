# `tests/test_matcher.py` — Explained

> Unit tests for `proofcheck.matcher.match_value` and `build_diff`, verifying EXACT/FUZZY/MISSING/SKIPPED classification, threshold enforcement, reverse matching, and diff op structure.

## Purpose
These tests exercise the core matching engine in isolation, using a small in-line `PAGES` dict instead of real PDFs. They confirm that a single expected value is correctly classified against page text given a fuzzy threshold and reverse flag, and that the diff helper produces well-formed op/text pairs. This is the deterministic heart of ProofCheck.

## Dependencies
- **Imports (external):** None directly (pytest is the runner).
- **Imports (internal):** `proofcheck.matcher` — `build_diff`, `match_value`; `proofcheck.models` — `Status` (the EXACT/FUZZY/MISSING/SKIPPED enum).
- **Used by:** Run by pytest. Uses no `conftest.py` fixtures; defines its own `PAGES` constant.

## Line-by-line / block-by-block breakdown

### Imports and `PAGES`
```python
from proofcheck.matcher import build_diff, match_value
from proofcheck.models import Status

PAGES = {1: "Gautam Sharma  CC-101  Mumbai\nPriya Nair  Delhi\nSmith John  Bengaluru", 2: ""}
```
`PAGES` maps page number → extracted text. Page 1 contains `Gautam Sharma` (target for fuzzy), `Priya Nair` (exact), and `Smith John` (reverse of `John Smith`). Page 2 is empty (no text layer). This mirrors the `conftest` PDF but is self-contained.

### `test_exact_match`
```python
def test_exact_match():
    r = match_value("Priya Nair", PAGES, row=3)
    assert r.status is Status.EXACT
    assert r.page == 1
    assert r.score == 100
```
`"Priya Nair"` appears verbatim on page 1, so the result is **EXACT**, located on `page == 1`, with a perfect `score == 100`.

### `test_fuzzy_match`
```python
def test_fuzzy_match():
    r = match_value("Gauttam Sharma", PAGES, fuzzy_threshold=90, row=2)
    assert r.status is Status.FUZZY
    assert r.score >= 90
    assert r.page == 1
    assert r.diff  # there should be a diff between expected and best match
```
`"Gauttam Sharma"` (extra `t`) is not exact but scores at/above the 90 threshold against `"Gautam Sharma"`, so the status is **FUZZY** with `score >= 90` on page 1. Because expected and matched text differ, `r.diff` is non-empty.

### `test_missing_match`
```python
def test_missing_match():
    r = match_value("Zzxqq Nobody", PAGES, fuzzy_threshold=90, row=4)
    assert r.status is Status.MISSING
```
`"Zzxqq Nobody"` is absent from `PAGES` and cannot clear the 90 threshold, so the status is **MISSING**.

### `test_blank_is_skipped`
```python
def test_blank_is_skipped():
    assert match_value(None, PAGES, row=6).status is Status.SKIPPED
    assert match_value("   ", PAGES, row=6).status is Status.SKIPPED
```
Both a `None` value and a whitespace-only string normalize to empty and are classified **SKIPPED** (not searched, not counted as failures).

### `test_reverse_matching`
```python
def test_reverse_matching():
    # "John Smith" only appears reversed as "Smith John" in the PDF.
    without = match_value("John Smith", PAGES, fuzzy_threshold=90, reverse=False, row=4)
    withrev = match_value("John Smith", PAGES, fuzzy_threshold=90, reverse=True, row=4)
    assert without.status is Status.MISSING
    assert withrev.status is Status.EXACT
```
The PDF only has `"Smith John"`. With `reverse=False`, `"John Smith"` is **MISSING**. With `reverse=True`, the matcher also tries the reversed token order and finds an exact hit, yielding **EXACT**.

### `test_threshold_is_respected`
```python
def test_threshold_is_respected():
    # A very high threshold turns a near-miss into MISSING.
    strict = match_value("Gauttam Sharma", PAGES, fuzzy_threshold=100, row=2)
    assert strict.status is Status.MISSING
```
Same near-miss input as the fuzzy test, but with `fuzzy_threshold=100` the only acceptable score is a perfect 100; since `"Gauttam Sharma"` is not exact, it falls through to **MISSING**. Confirms the threshold gate works.

### `test_build_diff_pairs`
```python
def test_build_diff_pairs():
    diff = build_diff("gauttam", "gautam")
    ops = {op for op, _ in diff}
    assert ops <= {"equal", "insert", "delete"}
    # Reconstruct "expected" from equal+delete fragments.
    rebuilt = "".join(t for op, t in diff if op in ("equal", "delete"))
    assert rebuilt == "gauttam"
```
`build_diff(expected, found)` returns a list of `(op, text)` pairs. The op set is constrained to `{"equal", "insert", "delete"}` (no `replace`). It also asserts the diff is faithful: concatenating the `equal` and `delete` fragments reconstructs the original **expected** string `"gauttam"` — i.e., `delete` marks characters present in expected but not in found, `insert` the reverse.

## Fixtures / Tests / Sections

| Name | What it verifies |
| --- | --- |
| `test_exact_match` | Verbatim hit → EXACT, page 1, score 100. |
| `test_fuzzy_match` | Near-miss ≥ threshold → FUZZY with non-empty diff. |
| `test_missing_match` | Absent value → MISSING. |
| `test_blank_is_skipped` | `None` and whitespace-only → SKIPPED. |
| `test_reverse_matching` | Reverse flag flips MISSING → EXACT for `Smith John`. |
| `test_threshold_is_respected` | Threshold 100 forces a near-miss to MISSING. |
| `test_build_diff_pairs` | Diff ops ⊆ {equal,insert,delete}; rebuilds expected from equal+delete. |

## Notes / gotchas
- **Self-contained `PAGES`:** these tests do not use the `conftest.py` PDF; they hand-build page text so the matcher is tested in true isolation.
- **`is` comparison** is used against `Status` enum members (identity), not `==`.
- **Threshold semantics:** an exact substring scores 100; fuzzy acceptance requires `score >= fuzzy_threshold`, so a threshold of 100 effectively disables fuzzy matching.
- **Diff invariant:** `equal + delete` fragments reconstruct the expected string, which is the property the HTML report relies on to highlight differences.
