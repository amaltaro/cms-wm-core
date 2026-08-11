"""Tests for EventBasedSplitter."""

import pytest

from cms_wm_core.job_splitting import (
    EventBasedRequest,
    EventBasedSplitter,
    ResourceBudgets,
    ResourceRates,
)
from cms_wm_core.job_splitting.event_based import events_per_job


def _rates(**kwargs: float) -> ResourceRates:
    return ResourceRates(time_per_event=1.0, **kwargs)


def test_splitter_name():
    assert EventBasedSplitter().name == "EventBased"


def test_events_per_job_from_walltime_and_time_per_event():
    assert events_per_job(target_job_walltime=100.0, time_per_event=3.0) == 33


def test_events_per_job_rejects_non_positive_inputs():
    with pytest.raises(ValueError, match="time_per_event"):
        events_per_job(10.0, 0.0)
    with pytest.raises(ValueError, match="target_job_walltime"):
        events_per_job(0.0, 1.0)
    with pytest.raises(ValueError, match="events_per_job must be >= 1"):
        events_per_job(0.5, 1.0)


def test_empty_total_events_yields_no_jobs():
    result = EventBasedSplitter().split(
        EventBasedRequest(
            total_events=0,
            target_job_walltime=10.0,
            rates=_rates(),
        )
    )
    assert result.jobs == ()


def test_disjoint_half_open_ranges_and_unique_lumis():
    # events_per_job = floor(10/1) = 10 → 3 jobs for 25 events
    jobs = EventBasedSplitter().split(
        EventBasedRequest(
            total_events=25,
            target_job_walltime=10.0,
            rates=_rates(),
            first_event=1,
            first_lumi=1,
        )
    ).jobs

    assert len(jobs) == 3
    assert (jobs[0].first_event, jobs[0].n_events, jobs[0].lumi) == (1, 10, 1)
    assert (jobs[1].first_event, jobs[1].n_events, jobs[1].lumi) == (11, 10, 2)
    assert (jobs[2].first_event, jobs[2].n_events, jobs[2].lumi) == (21, 5, 3)
    assert all(j.input_lfns == () for j in jobs)
    assert all(j.unsplittable is False for j in jobs)


def test_custom_first_event_and_lumi_for_wms_slice():
    jobs = EventBasedSplitter().split(
        EventBasedRequest(
            total_events=5,
            target_job_walltime=2.0,
            rates=_rates(),
            first_event=1001,
            first_lumi=50,
        )
    ).jobs

    assert len(jobs) == 3
    assert (jobs[0].first_event, jobs[0].n_events, jobs[0].lumi) == (1001, 2, 50)
    assert (jobs[1].first_event, jobs[1].n_events, jobs[1].lumi) == (1003, 2, 51)
    assert (jobs[2].first_event, jobs[2].n_events, jobs[2].lumi) == (1005, 1, 52)
    assert all(j.input_lfns == () for j in jobs)
    assert all(j.unsplittable is False for j in jobs)


def test_resource_estimates_and_zero_network():
    jobs = EventBasedSplitter().split(
        EventBasedRequest(
            total_events=10,
            target_job_walltime=10.0,
            rates=ResourceRates(
                time_per_event=2.0,
                transient_output_size_per_event=3.0,
                persisted_output_size_per_event=4.0,
            ),
        )
    ).jobs
    assert len(jobs) == 2  # floor(10/2)=5 events/job → 2 jobs
    assert jobs[0].n_events == 5
    assert jobs[0].estimates.walltime == 10.0
    assert jobs[0].estimates.scratch_disk == 35.0
    assert jobs[0].estimates.persisted_output == 20.0
    assert jobs[0].estimates.network == 0.0


def test_max_walltime_marks_unsplittable_but_still_emits_range():
    jobs = EventBasedSplitter().split(
        EventBasedRequest(
            total_events=10,
            target_job_walltime=10.0,
            rates=_rates(),
            budgets=ResourceBudgets(max_job_walltime=5.0),
        )
    ).jobs
    assert len(jobs) == 1
    assert jobs[0].n_events == 10
    assert jobs[0].unsplittable is True
    assert "max_job_walltime" in (jobs[0].unsplittable_reason or "")


def test_deterministic():
    request = EventBasedRequest(
        total_events=7,
        target_job_walltime=3.0,
        rates=_rates(),
        first_event=10,
        first_lumi=4,
    )
    splitter = EventBasedSplitter()
    assert splitter.split(request) == splitter.split(request)


def test_rejects_invalid_first_event_or_lumi():
    with pytest.raises(ValueError, match="first_event"):
        EventBasedSplitter().split(
            EventBasedRequest(
                total_events=1,
                target_job_walltime=1.0,
                rates=_rates(),
                first_event=0,
            )
        )
    with pytest.raises(ValueError, match="first_lumi"):
        EventBasedSplitter().split(
            EventBasedRequest(
                total_events=1,
                target_job_walltime=1.0,
                rates=_rates(),
                first_lumi=0,
            )
        )
