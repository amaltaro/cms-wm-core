"""Unit tests for EventAwareLumiSplitter."""

import pytest

from cms_wm_core.job_splitting.event_aware_lumi import (
    EventAwareLumiRequest,
    EventAwareLumiSplitter,
    _compact_mask,
)
from cms_wm_core.job_splitting.types import (
    ResourceBudgets,
    ResourceRates,
    RunLumiEvents,
    RunLumiRange,
    SplitFile,
)


def _file(
    lfn: str,
    *,
    events: int,
    size: int = 100,
    run_lumis: tuple[RunLumiEvents, ...],
) -> SplitFile:
    return SplitFile(lfn=lfn, events=events, size=size, run_lumis=run_lumis)


def _rates(time_per_event: float = 1.0) -> ResourceRates:
    return ResourceRates(
        time_per_event=time_per_event,
        transient_output_size_per_event=2.0,
        persisted_output_size_per_event=1.0,
    )


def test_compact_mask_merges_contiguous_lumis():
    assert _compact_mask([(1, 1), (1, 2), (1, 4), (2, 1)]) == (
        RunLumiRange(run=1, first_lumi=1, last_lumi=2),
        RunLumiRange(run=1, first_lumi=4, last_lumi=4),
        RunLumiRange(run=2, first_lumi=1, last_lumi=1),
    )
    assert _compact_mask([]) == ()


def test_known_events_closest_to_target():
    """Target 100 events: pack (40,40) then close before 40 → two jobs."""
    # events_per_job = floor(100 / 1) = 100
    # |80-100|=20 < |120-100|=20 is False for >= so 40+40+40: check
    # After 80, adding 40: |120-100|=20 >= |80-100|=20 → close, start with 40
    files = (
        _file(
            "/store/a.root",
            events=120,
            run_lumis=(
                RunLumiEvents(1, 1, 40),
                RunLumiEvents(1, 2, 40),
                RunLumiEvents(1, 3, 40),
            ),
        ),
    )
    result = EventAwareLumiSplitter().split(
        EventAwareLumiRequest(
            files=files,
            target_job_walltime=100.0,
            rates=_rates(1.0),
        )
    )
    assert len(result.jobs) == 2
    assert result.jobs[0].n_events == 80
    assert result.jobs[0].run_lumi_mask == (
        RunLumiRange(run=1, first_lumi=1, last_lumi=2),
    )
    assert result.jobs[0].input_lfns == ("/store/a.root",)
    assert result.jobs[1].n_events == 40
    assert result.jobs[1].run_lumi_mask == (
        RunLumiRange(run=1, first_lumi=3, last_lumi=3),
    )
    assert result.jobs[1].input_lfns == ("/store/a.root",)
    # estimate checks; note that scratch = n_events × (transient 2.0 + persisted 1.0)
    assert result.jobs[0].estimates.walltime == 80.0
    assert result.jobs[0].estimates.scratch_disk == 240.0
    assert result.jobs[0].estimates.persisted_output == 80.0
    assert result.jobs[0].estimates.network == 100.0
    assert result.jobs[1].estimates.walltime == 40.0
    assert result.jobs[1].estimates.scratch_disk == 120.0
    assert result.jobs[1].estimates.persisted_output == 40.0
    assert result.jobs[1].estimates.network == 100.0


def test_known_events_overshoot_when_closer_to_target():
    """Target 101: same (40,40,40) stays in one job — 120 is closer than 80."""
    # After 80, adding 40: |120-101|=19 < |80-101|=21 → keep (do not close)
    files = (
        _file(
            "/store/a.root",
            events=120,
            run_lumis=(
                RunLumiEvents(1, 1, 40),
                RunLumiEvents(1, 2, 40),
                RunLumiEvents(1, 3, 40),
            ),
        ),
    )
    result = EventAwareLumiSplitter().split(
        EventAwareLumiRequest(
            files=files,
            target_job_walltime=101.0,
            rates=_rates(1.0),
        )
    )
    assert len(result.jobs) == 1
    assert result.jobs[0].n_events == 120
    assert result.jobs[0].run_lumi_mask == (
        RunLumiRange(run=1, first_lumi=1, last_lumi=3),
    )
    assert result.jobs[0].input_lfns == ("/store/a.root",)
    # assert job estimates are correct
    assert result.jobs[0].estimates.walltime == 120.0
    assert result.jobs[0].estimates.scratch_disk == 360.0
    assert result.jobs[0].estimates.persisted_output == 120.0
    assert result.jobs[0].estimates.network == 100.0


def test_legacy_none_uses_file_average():
    """Three lumis, file.events=90 → avg 30; target 60 → two lumis then one."""
    files = (
        _file(
            "/store/a.root",
            events=90,
            run_lumis=(
                RunLumiEvents(1, 1, None),
                RunLumiEvents(1, 2, None),
                RunLumiEvents(1, 3, None),
            ),
        ),
    )
    result = EventAwareLumiSplitter().split(
        EventAwareLumiRequest(
            files=files,
            target_job_walltime=60.0,
            rates=_rates(1.0),
        )
    )
    assert [j.n_events for j in result.jobs] == [60, 30]
    assert result.jobs[0].run_lumi_mask == (
        RunLumiRange(run=1, first_lumi=1, last_lumi=2),
    )


def test_mixed_known_and_legacy_in_one_file_rejected():
    """Per file: all int or all None — mixed metadata is not supported."""
    files = (
        _file(
            "/store/a.root",
            events=100,
            run_lumis=(
                RunLumiEvents(1, 1, 10),
                RunLumiEvents(1, 2, None),
            ),
        ),
    )
    with pytest.raises(ValueError, match="mixes known and legacy"):
        EventAwareLumiSplitter().split(
            EventAwareLumiRequest(
                files=files,
                target_job_walltime=100.0,
                rates=_rates(1.0),
            )
        )


def test_shared_lumi_across_files_rejected():
    """Shared (run, lumi) is LumiAwareFile-only; EventAwareLumi must fail."""
    files = (
        _file(
            "/store/b.root",
            events=20,
            size=20,
            run_lumis=(RunLumiEvents(1, 1, 20),),
        ),
        _file(
            "/store/a.root",
            events=30,
            size=30,
            run_lumis=(RunLumiEvents(1, 1, 30),),
        ),
    )
    with pytest.raises(ValueError, match="LumiAwareFile"):
        EventAwareLumiSplitter().split(
            EventAwareLumiRequest(
                files=files,
                target_job_walltime=100.0,
                rates=_rates(1.0),
            )
        )


def test_oversized_single_lumi_marked_unsplittable():
    files = (
        _file(
            "/store/a.root",
            events=1000,
            run_lumis=(RunLumiEvents(1, 1, 1000),),
        ),
    )
    result = EventAwareLumiSplitter().split(
        EventAwareLumiRequest(
            files=files,
            target_job_walltime=100.0,
            rates=_rates(1.0),
            budgets=ResourceBudgets(max_job_walltime=500.0),
        )
    )
    assert len(result.jobs) == 1
    assert result.jobs[0].unsplittable is True
    assert result.jobs[0].n_events == 1000
    assert "max_job_walltime" in (result.jobs[0].unsplittable_reason or "")


def test_empty_files_returns_no_jobs():
    result = EventAwareLumiSplitter().split(
        EventAwareLumiRequest(
            files=(),
            target_job_walltime=100.0,
            rates=_rates(1.0),
        )
    )
    assert result.jobs == ()


def test_empty_run_lumis_rejected():
    with pytest.raises(ValueError, match="empty run_lumis"):
        EventAwareLumiSplitter().split(
            EventAwareLumiRequest(
                files=(_file("/store/a.root", events=1, run_lumis=()),),
                target_job_walltime=100.0,
                rates=_rates(1.0),
            )
        )


def test_deterministic_regardless_of_file_order():
    a = _file(
        "/store/a.root",
        events=40,
        run_lumis=(RunLumiEvents(1, 1, 40),),
    )
    b = _file(
        "/store/b.root",
        events=40,
        run_lumis=(RunLumiEvents(1, 2, 40),),
    )
    splitter = EventAwareLumiSplitter()
    req_ab = EventAwareLumiRequest(
        files=(a, b),
        target_job_walltime=50.0,
        rates=_rates(1.0),
    )
    req_ba = EventAwareLumiRequest(
        files=(b, a),
        target_job_walltime=50.0,
        rates=_rates(1.0),
    )
    assert splitter.split(req_ab) == splitter.split(req_ba)


def test_zero_event_lumis_pack_together():
    files = (
        _file(
            "/store/a.root",
            events=0,
            run_lumis=(
                RunLumiEvents(1, 1, 0),
                RunLumiEvents(1, 2, 0),
            ),
        ),
    )
    result = EventAwareLumiSplitter().split(
        EventAwareLumiRequest(
            files=files,
            target_job_walltime=100.0,
            rates=_rates(1.0),
        )
    )
    assert len(result.jobs) == 1
    assert result.jobs[0].n_events == 0
    assert result.jobs[0].run_lumi_mask == (
        RunLumiRange(run=1, first_lumi=1, last_lumi=2),
    )
    # also assert the job estimates are correct
    assert result.jobs[0].estimates.walltime == 0.0
    assert result.jobs[0].estimates.scratch_disk == 0.0
    assert result.jobs[0].estimates.persisted_output == 0.0
    # Network is sum of assigned file sizes (default size=100), not scaled
    # by n_events — the job still lists the input LFN.
    assert result.jobs[0].estimates.network == 100.0
    assert result.jobs[0].input_lfns == ("/store/a.root",)


def test_name():
    assert EventAwareLumiSplitter().name == "EventAwareLumi"


def test_resource_estimates_use_output_rates_and_file_size():
    """Disk estimates scale with n_events; network uses assigned file size."""
    files = (
        _file(
            "/store/a.root",
            events=10,
            size=50,
            run_lumis=(RunLumiEvents(1, 1, 10),),
        ),
    )
    result = EventAwareLumiSplitter().split(
        EventAwareLumiRequest(
            files=files,
            target_job_walltime=100.0,
            rates=_rates(1.0),
        )
    )
    assert len(result.jobs) == 1
    estimates = result.jobs[0].estimates
    assert result.jobs[0].n_events == 10
    assert estimates.walltime == 10.0
    assert estimates.scratch_disk == 30.0  # 10 × (2.0 + 1.0)
    assert estimates.persisted_output == 10.0  # 10 × 1.0
    assert estimates.network == 50.0
