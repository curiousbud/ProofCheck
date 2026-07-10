import pytest

from proofcheck.models import RunConfig, Status
from proofcheck.pipeline import PipelineError, run


def _status_counts(result):
    counts = {s: 0 for s in Status}
    for col in result.columns:
        for r in col.results:
            counts[r.status] += 1
    return counts


def test_run_name_column(excel_path, pdf_path):
    config = RunConfig(
        excel_path=excel_path, pdf_path=pdf_path,
        columns=["Name"], sheet="Delegates", fuzzy_threshold=90,
    )
    result = run(config)
    counts = _status_counts(result)
    assert counts[Status.EXACT] == 1     # Priya Nair
    assert counts[Status.FUZZY] == 1     # Gauttam Sharma
    assert counts[Status.MISSING] == 2   # John Smith (no reverse) + Zzxqq Nobody
    assert counts[Status.SKIPPED] == 1   # blank cell
    assert result.summary.total == 5


def test_run_with_reverse(excel_path, pdf_path):
    config = RunConfig(
        excel_path=excel_path, pdf_path=pdf_path,
        columns=["Name"], sheet="Delegates", fuzzy_threshold=90, reverse=True,
    )
    counts = _status_counts(run(config))
    # John Smith now matches "Smith John".
    assert counts[Status.EXACT] == 2
    assert counts[Status.MISSING] == 1


def test_warning_for_no_text_layer(excel_path, pdf_path):
    config = RunConfig(excel_path=excel_path, pdf_path=pdf_path, columns=["Name"], sheet="Delegates")
    result = run(config)
    assert any("no text layer" in w for w in result.warnings)


def test_pass_rate_excludes_skipped(excel_path, pdf_path):
    config = RunConfig(excel_path=excel_path, pdf_path=pdf_path, columns=["Name"], sheet="Delegates")
    result = run(config)
    # checked = 4 (5 total - 1 skipped); pass = exact(1) + fuzzy(1) = 2 -> 0.5
    assert result.summary.pass_rate == 0.5


def test_all_columns(excel_path, pdf_path):
    config = RunConfig(excel_path=excel_path, pdf_path=pdf_path, all_columns=True, sheet="Delegates")
    result = run(config)
    assert {c.name for c in result.columns} == {"Name", "CC Code", "City"}


def test_progress_reports_match_completion(excel_path, pdf_path):
    """The match stage must emit monotonic progress ending exactly at (total, total)."""
    events = []
    config = RunConfig(excel_path=excel_path, pdf_path=pdf_path, columns=["Name"], sheet="Delegates")
    result = run(config, progress=lambda stage, cur, tot: events.append((stage, cur, tot)))

    match_events = [(cur, tot) for stage, cur, tot in events if stage == "match"]
    assert match_events, "expected at least one match progress event"
    total = result.summary.total
    # Announced up front at 0, advances one per value, and finishes at total/total.
    assert match_events[0] == (0, total)
    assert match_events[-1] == (total, total)
    assert all(tot == total for _, tot in match_events)
    # current is non-decreasing and never overshoots the total.
    currents = [cur for cur, _ in match_events]
    assert currents == sorted(currents)
    assert currents[-1] == total


def test_progress_is_optional(excel_path, pdf_path):
    """A run without a progress callback behaves exactly as before (no crash, same result)."""
    config = RunConfig(excel_path=excel_path, pdf_path=pdf_path, columns=["Name"], sheet="Delegates")
    assert run(config).summary.total == run(config, progress=None).summary.total


def test_no_columns_raises(excel_path, pdf_path):
    with pytest.raises(PipelineError):
        run(RunConfig(excel_path=excel_path, pdf_path=pdf_path, sheet="Delegates"))


def test_unknown_column_raises(excel_path, pdf_path):
    with pytest.raises(PipelineError):
        run(RunConfig(excel_path=excel_path, pdf_path=pdf_path, columns=["Nope"], sheet="Delegates"))
