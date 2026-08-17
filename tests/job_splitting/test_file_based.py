"""Tests for FileBasedSplitter."""

import pytest

from cms_wm_core.job_splitting import (
    FileBasedRequest,
    FileBasedSplitter,
    ResourceBudgets,
    ResourceEstimates,
    ResourceRates,
    SplitFile,
    SplitJob,
    SplitResult,
)


def _files(*specs: tuple[str, int, int]) -> tuple[SplitFile, ...]:
    """Build files from ``(lfn, events, size)`` triples."""
    return tuple(
        SplitFile(lfn=lfn, events=events, size=size)
        for lfn, events, size in specs
    )


def test_splitter_name():
    splitter = FileBasedSplitter()
    assert splitter.name == "FileBased"


def test_result_type_no_jobs():
    request = FileBasedRequest(
        files=(),
        files_per_job=1,
    )
    result = FileBasedSplitter().split(request)
    assert isinstance(result, SplitResult)
    assert isinstance(result.jobs, tuple)
    assert len(result.jobs) == 0


def test_result_type_one_job():
    request = FileBasedRequest(
        files=_files(("/store/a.root", 1, 10)),
        files_per_job=1,
    )
    result = FileBasedSplitter().split(request)
    assert isinstance(result, SplitResult)
    assert isinstance(result.jobs, tuple)
    assert len(result.jobs) == 1
    assert all(isinstance(job, SplitJob) for job in result.jobs)
    assert all(isinstance(job.input_lfns, tuple) for job in result.jobs)
    assert all(isinstance(job.estimates, ResourceEstimates) for job in result.jobs)
    assert all(isinstance(job.unsplittable, bool) for job in result.jobs)
    assert all(job.unsplittable_reason is None for job in result.jobs)


def test_packs_by_files_per_job_and_sorts_by_lfn():
    request = FileBasedRequest(
        files=_files(
            ("/store/c.root", 1, 100),
            ("/store/a.root", 2, 200),
            ("/store/b.root", 3, 300),
        ),
        files_per_job=2,
        rates=ResourceRates(time_per_event=1.0),
    )
    result = FileBasedSplitter().split(request)
    assert isinstance(result, SplitResult)

    jobs = result.jobs
    assert len(jobs) == 2
    assert jobs[0].input_lfns == ("/store/a.root", "/store/b.root")
    assert jobs[0].n_events == 5
    assert jobs[0].estimates.walltime == 5.0
    assert jobs[0].estimates.network == 500.0
    assert jobs[1].input_lfns == ("/store/c.root",)
    assert jobs[1].n_events == 1
    assert jobs[1].estimates.walltime == 1.0
    assert jobs[1].estimates.network == 100.0


def test_deterministic_for_same_input():
    request = FileBasedRequest(
        files=_files(("/store/b.root", 20, 200), ("/store/a.root", 10, 100)),
        files_per_job=10,
    )
    splitter = FileBasedSplitter()
    assert splitter.split(request) == splitter.split(request)
    assert splitter.name == "FileBased"


def test_files_per_job_must_be_positive():
    with pytest.raises(ValueError, match="files_per_job"):
        FileBasedSplitter().split(
            FileBasedRequest(
                files=_files(("/store/a.root", 1, 10)),
                files_per_job=0,
            )
        )


def test_negative_size_is_rejected():
    with pytest.raises(ValueError, match="negative size"):
        FileBasedSplitter().split(
            FileBasedRequest(
                files=(SplitFile(lfn="/store/a.root", events=1, size=-1),),
                files_per_job=1,
            )
        )


def test_resource_estimates_use_decomposed_rates():
    request = FileBasedRequest(
        files=(SplitFile(lfn="/store/a.root", events=10, size=1000),),
        files_per_job=1,
        rates=ResourceRates(
            time_per_event=2.0,
            transient_output_size_per_event=3.0,
            persisted_output_size_per_event=4.0,
        ),
    )
    job = FileBasedSplitter().split(request).jobs[0]
    assert job.estimates.walltime == 20.0
    assert job.estimates.scratch_disk == 70.0  # (3+4) * 10 events
    assert job.estimates.persisted_output == 40.0
    assert job.estimates.network == 1000.0


def test_single_file_over_max_walltime_is_unsplittable():
    request = FileBasedRequest(
        files=_files(
            ("/store/huge.root", 100, 1000),
            ("/store/ok.root", 5, 50),
        ),
        files_per_job=10,
        rates=ResourceRates(time_per_event=1.0),
        budgets=ResourceBudgets(max_job_walltime=50.0),
    )
    jobs = FileBasedSplitter().split(request).jobs
    assert len(jobs) == 2
    # Sorted: huge before ok
    assert jobs[0].input_lfns == ("/store/huge.root",)
    assert jobs[0].unsplittable is True
    assert "max_job_walltime" in (jobs[0].unsplittable_reason or "")
    assert jobs[1].input_lfns == ("/store/ok.root",)
    assert jobs[1].unsplittable is False


def test_closes_before_adding_file_that_would_exceed_max_disk():
    request = FileBasedRequest(
        files=_files(
            ("/store/a.root", 40, 400),
            ("/store/b.root", 50, 500),
            ("/store/c.root", 60, 600),
        ),
        files_per_job=10,
        rates=ResourceRates(transient_output_size_per_event=1.0),
        budgets=ResourceBudgets(max_job_disk=50.0),
    )
    jobs = FileBasedSplitter().split(request).jobs
    assert len(jobs) == 3
    assert jobs[0].input_lfns == ("/store/a.root",)
    print(jobs[0].estimates)
    assert jobs[0].estimates.scratch_disk == 40.0
    assert jobs[0].estimates.persisted_output == 0.0  # default value
    assert jobs[0].estimates.network == 400.0
    assert jobs[1].input_lfns == ("/store/b.root",)
    assert jobs[1].estimates.scratch_disk == 50.0
    assert jobs[1].estimates.persisted_output == 0.0  # default value
    assert jobs[1].estimates.network == 500.0
    assert jobs[1].unsplittable is False
    # 3rd job goes beyond the limits, so it is unsplittable
    assert jobs[2].input_lfns == ("/store/c.root",)
    assert jobs[2].estimates.scratch_disk == 60.0
    assert jobs[2].estimates.persisted_output == 0.0  # default value
    assert jobs[2].estimates.network == 600.0
    assert jobs[2].unsplittable is True


def test_soft_target_walltime_closes_job_early():
    request = FileBasedRequest(
        files=_files(
            ("/store/a.root", 10, 100),
            ("/store/b.root", 10, 100),
            ("/store/c.root", 10, 100),
        ),
        files_per_job=10,
        rates=ResourceRates(time_per_event=1.0),
        budgets=ResourceBudgets(target_job_walltime=10.0),
    )
    jobs = FileBasedSplitter().split(request).jobs
    assert len(jobs) == 3
    assert [job.input_lfns for job in jobs] == [
        ("/store/a.root",),
        ("/store/b.root",),
        ("/store/c.root",),
    ]
