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


@pytest.mark.parametrize("workers", [1, 2, 4, 8])
def test_workers_do_not_change_output(excel_path, pdf_path, workers):
    """Parallelism must be transparent: any worker count yields identical results."""
    base = run(RunConfig(
        excel_path=excel_path, pdf_path=pdf_path,
        all_columns=True, sheet="Delegates", reverse=True, workers=1,
    ))
    parallel = run(RunConfig(
        excel_path=excel_path, pdf_path=pdf_path,
        all_columns=True, sheet="Delegates", reverse=True, workers=workers,
    ))
    # Same columns, in the same order, with the same per-row results (order included).
    assert [c.name for c in parallel.columns] == [c.name for c in base.columns]
    for pc, bc in zip(parallel.columns, base.columns):
        assert [(r.row, r.expected, r.status, r.page, r.score) for r in pc.results] == \
               [(r.row, r.expected, r.status, r.page, r.score) for r in bc.results]
    assert parallel.summary == base.summary


def test_no_columns_raises(excel_path, pdf_path):
    with pytest.raises(PipelineError):
        run(RunConfig(excel_path=excel_path, pdf_path=pdf_path, sheet="Delegates"))


def test_unknown_column_raises(excel_path, pdf_path):
    with pytest.raises(PipelineError):
        run(RunConfig(excel_path=excel_path, pdf_path=pdf_path, columns=["Nope"], sheet="Delegates"))
