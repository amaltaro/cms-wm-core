"""Unit tests for file-oriented splitter helpers in ``file_common``."""

import pytest

from cms_wm_core.job_splitting.file_common import (
    estimates_for,
    exceeds_maximum,
    make_job,
    meets_soft_target,
    validate_file_basics,
)
from cms_wm_core.job_splitting.types import (
    ResourceBudgets,
    ResourceEstimates,
    ResourceRates,
    SplitFile,
)


def test_estimates_for_empty_file_list():
    estimates = estimates_for([], ResourceRates(time_per_event=2.0))
    assert estimates == ResourceEstimates()


def test_estimates_for_sums_events_and_sizes():
    files = [
        SplitFile(lfn="/store/a.root", events=10, size=100),
        SplitFile(lfn="/store/b.root", events=5, size=50),
    ]
    rates = ResourceRates(
        time_per_event=2.0,
        transient_output_size_per_event=3.0,
        persisted_output_size_per_event=4.0,
    )
    estimates = estimates_for(files, rates)
    assert estimates.walltime == 30.0
    assert estimates.scratch_disk == 105.0  # (3+4) * 15 events
    assert estimates.persisted_output == 60.0
    assert estimates.network == 150.0


def test_estimates_for_scratch_includes_transient_and_persisted():
    files = [SplitFile(lfn="/store/a.root", events=10, size=1)]
    rates = ResourceRates(
        transient_output_size_per_event=2.0,
        persisted_output_size_per_event=3.0,
    )
    estimates = estimates_for(files, rates)
    assert estimates.scratch_disk == 50.0
    assert estimates.persisted_output == 30.0


def test_estimates_for_zero_rates_still_reports_network_from_size():
    files = [SplitFile(lfn="/store/a.root", events=10, size=42)]
    estimates = estimates_for(files, ResourceRates())
    assert estimates.walltime == 0.0
    assert estimates.scratch_disk == 0.0
    assert estimates.persisted_output == 0.0
    assert estimates.network == 42.0


def test_exceeds_maximum_none_when_budgets_unset():
    estimates = ResourceEstimates(walltime=1e9, scratch_disk=1e9)
    assert exceeds_maximum(estimates, ResourceBudgets()) is None


def test_exceeds_maximum_walltime():
    reason = exceeds_maximum(
        ResourceEstimates(walltime=11.0),
        ResourceBudgets(max_job_walltime=10.0),
    )
    assert reason is not None
    assert "max_job_walltime" in reason
    assert "11.0" in reason


def test_exceeds_maximum_disk_when_walltime_ok():
    reason = exceeds_maximum(
        ResourceEstimates(walltime=1.0, scratch_disk=100.0),
        ResourceBudgets(max_job_walltime=10.0, max_job_disk=50.0),
    )
    assert reason is not None
    assert "max_job_disk" in reason


def test_exceeds_maximum_walltime_checked_before_disk():
    reason = exceeds_maximum(
        ResourceEstimates(walltime=100.0, scratch_disk=100.0),
        ResourceBudgets(max_job_walltime=10.0, max_job_disk=10.0),
    )
    assert reason is not None
    assert "max_job_walltime" in reason


def test_exceeds_maximum_equal_to_max_is_allowed():
    assert (
        exceeds_maximum(
            ResourceEstimates(walltime=10.0, scratch_disk=5.0),
            ResourceBudgets(max_job_walltime=10.0, max_job_disk=5.0),
        )
        is None
    )


def test_meets_soft_target_false_when_unset():
    assert meets_soft_target(ResourceEstimates(walltime=100.0), ResourceBudgets()) is False


def test_meets_soft_target_walltime_at_boundary():
    budgets = ResourceBudgets(target_job_walltime=10.0)
    assert meets_soft_target(ResourceEstimates(walltime=9.9), budgets) is False
    assert meets_soft_target(ResourceEstimates(walltime=10.0), budgets) is True
    assert meets_soft_target(ResourceEstimates(walltime=10.1), budgets) is True


def test_meets_soft_target_disk():
    budgets = ResourceBudgets(target_job_disk=20.0)
    assert meets_soft_target(ResourceEstimates(scratch_disk=19.0), budgets) is False
    assert meets_soft_target(ResourceEstimates(scratch_disk=20.0), budgets) is True


def test_make_job_sorts_lfns_and_computes_estimates():
    files = [
        SplitFile(lfn="/store/b.root", events=2, size=20),
        SplitFile(lfn="/store/a.root", events=3, size=30),
    ]
    job = make_job(files, ResourceRates(time_per_event=1.0))
    assert job.input_lfns == ("/store/a.root", "/store/b.root")
    assert job.estimates.walltime == 5.0
    assert job.estimates.network == 50.0
    assert job.unsplittable is False
    assert job.unsplittable_reason is None


def test_make_job_unsplittable_flags():
    files = [SplitFile(lfn="/store/a.root", events=1, size=10)]
    job = make_job(
        files,
        ResourceRates(),
        unsplittable=True,
        reason="too large",
    )
    assert job.unsplittable is True
    assert job.unsplittable_reason == "too large"


def test_validate_file_basics_accepts_zero_events_and_size():
    validate_file_basics(SplitFile(lfn="/store/a.root", events=0, size=0))


def test_validate_file_basics_rejects_negative_events():
    with pytest.raises(ValueError, match="negative events"):
        validate_file_basics(
            SplitFile(lfn="/store/a.root", events=-1, size=0)
        )


def test_validate_file_basics_rejects_negative_size():
    with pytest.raises(ValueError, match="negative size"):
        validate_file_basics(
            SplitFile(lfn="/store/a.root", events=0, size=-1)
        )
