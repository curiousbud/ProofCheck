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


def test_duplicated_surname_is_flagged_not_exact():
    # The PDF repeats the surname ("Jordan Avery Avery"). The clean spreadsheet
    # value is still a perfect substring, but a duplicated surname must NOT pass as
    # EXACT — it should surface as a difference with the extra word highlighted.
    pages = {1: "JORDAN AVERY AVERY DEL-01"}
    r = match_value("Jordan Avery", pages, fuzzy_threshold=90, row=1)
    assert r.status is Status.FUZZY
    assert r.page == 1
    assert r.score < 100
    # The diff keeps the expected name and flags the repeated surname as inserted.
    inserted = "".join(t for op, t in r.diff if op == "insert")
    assert "avery" in inserted.lower()


def test_clean_match_still_exact_when_no_duplicate():
    # A single, non-repeated occurrence stays EXACT even when other rows share a surname.
    pages = {1: "MORGAN BLAKE ID-11", 2: "CASEY MORGAN BLAKE ID-20"}
    assert match_value("Morgan Blake", pages, row=1).status is Status.EXACT
    assert match_value("Casey Morgan Blake", pages, row=2).status is Status.EXACT


def test_clean_occurrence_elsewhere_wins_over_duplicate():
    # If the value appears cleanly on one page and duplicated on another, the clean
    # verbatim occurrence takes priority (the value genuinely appears as written).
    pages = {1: "RILEY QUINN QUINN AMD-01", 2: "RILEY QUINN MUM-09"}
    assert match_value("Riley Quinn", pages, row=1).status is Status.EXACT


def test_build_diff_pairs():
    diff = build_diff("gauttam", "gautam")
    ops = {op for op, _ in diff}
    assert ops <= {"equal", "insert", "delete"}
    # Reconstruct "expected" from equal+delete fragments.
    rebuilt = "".join(t for op, t in diff if op in ("equal", "delete"))
    assert rebuilt == "gauttam"
