from proofcheck.matcher import build_diff, match_value
from proofcheck.models import Status

PAGES = {1: "Gautam Sharma  CC-101  Mumbai\nPriya Nair  Delhi\nSmith John  Bengaluru", 2: ""}


def test_exact_match():
    r = match_value("Priya Nair", PAGES, row=3)
    assert r.status is Status.EXACT
    assert r.page == 1
    assert r.score == 100


def test_fuzzy_match():
    r = match_value("Gauttam Sharma", PAGES, fuzzy_threshold=90, row=2)
    assert r.status is Status.FUZZY
    assert r.score >= 90
    assert r.page == 1
    assert r.diff  # there should be a diff between expected and best match


def test_missing_match():
    r = match_value("Zzxqq Nobody", PAGES, fuzzy_threshold=90, row=4)
    assert r.status is Status.MISSING


def test_blank_is_skipped():
    assert match_value(None, PAGES, row=6).status is Status.SKIPPED
    assert match_value("   ", PAGES, row=6).status is Status.SKIPPED


def test_reverse_matching():
    # "John Smith" only appears reversed as "Smith John" in the PDF.
    without = match_value("John Smith", PAGES, fuzzy_threshold=90, reverse=False, row=4)
    withrev = match_value("John Smith", PAGES, fuzzy_threshold=90, reverse=True, row=4)
    assert without.status is Status.MISSING
    assert withrev.status is Status.EXACT


def test_threshold_is_respected():
    # A very high threshold turns a near-miss into MISSING.
    strict = match_value("Gauttam Sharma", PAGES, fuzzy_threshold=100, row=2)
    assert strict.status is Status.MISSING


def test_build_diff_pairs():
    diff = build_diff("gauttam", "gautam")
    ops = {op for op, _ in diff}
    assert ops <= {"equal", "insert", "delete"}
    # Reconstruct "expected" from equal+delete fragments.
    rebuilt = "".join(t for op, t in diff if op in ("equal", "delete"))
    assert rebuilt == "gauttam"
