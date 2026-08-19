"""Tests for LumiAwareFileSplitter."""

import pytest

from cms_wm_core.job_splitting import (
    LumiAwareFileRequest,
    LumiAwareFileSplitter,
    ResourceBudgets,
    ResourceRates,
    RunLumiEvents,
    SplitFile,
)


def _rl(*pairs: tuple[int, int]) -> tuple[RunLumiEvents, ...]:
    return tuple(RunLumiEvents(run=run, lumi=lumi, events=0) for run, lumi in pairs)


def test_splitter_name():
    assert LumiAwareFileSplitter().name == "LumiAwareFile"


def test_shared_run_lumi_keeps_files_in_same_job():
    """files_per_job=1 must not split files that share a (run, lumi)."""
    files = (
        SplitFile(
            lfn="/store/b.root",
            events=10,
            size=100,
            run_lumis=_rl((1, 1), (1, 2)),
        ),
        SplitFile(
            lfn="/store/a.root",
            events=10,
            size=100,
            run_lumis=_rl((1, 2), (1, 3)),
        ),
    )
    jobs = LumiAwareFileSplitter().split(
        LumiAwareFileRequest(files=files, files_per_job=1)
    ).jobs

    assert len(jobs) == 1
    assert jobs[0].input_lfns == ("/store/a.root", "/store/b.root")


def test_transitive_sharing_forms_one_component():
    files = (
        SplitFile(
            lfn="/store/a.root", events=1, size=10, run_lumis=_rl((1, 1))
        ),
        SplitFile(
            lfn="/store/b.root", events=1, size=10, run_lumis=_rl((1, 1), (1, 2))
        ),
        SplitFile(
            lfn="/store/c.root", events=1, size=10, run_lumis=_rl((1, 2))
        ),
    )
    jobs = LumiAwareFileSplitter().split(
        LumiAwareFileRequest(files=files, files_per_job=1)
    ).jobs
    assert len(jobs) == 1
    assert jobs[0].input_lfns == (
        "/store/a.root",
        "/store/b.root",
        "/store/c.root",
    )


def test_disjoint_lumis_can_split_across_jobs():
    files = (
        SplitFile(
            lfn="/store/a.root", events=1, size=10, run_lumis=_rl((1, 1))
        ),
        SplitFile(
            lfn="/store/b.root", events=1, size=10, run_lumis=_rl((1, 2))
        ),
        SplitFile(
            lfn="/store/c.root", events=1, size=10, run_lumis=_rl((2, 1))
        ),
    )
    jobs = LumiAwareFileSplitter().split(
        LumiAwareFileRequest(files=files, files_per_job=1)
    ).jobs
    assert len(jobs) == 3
    assert jobs[0].input_lfns == ("/store/a.root",)
    assert jobs[1].input_lfns == ("/store/b.root",)
    assert jobs[2].input_lfns == ("/store/c.root",)


def test_packs_components_up_to_files_per_job():
    files = (
        SplitFile(
            lfn="/store/a.root", events=1, size=10, run_lumis=_rl((1, 1))
        ),
        SplitFile(
            lfn="/store/b.root", events=1, size=10, run_lumis=_rl((2, 1))
        ),
        SplitFile(
            lfn="/store/c.root", events=1, size=10, run_lumis=_rl((3, 1))
        ),
    )
    jobs = LumiAwareFileSplitter().split(
        LumiAwareFileRequest(files=files, files_per_job=2)
    ).jobs
    assert len(jobs) == 2
    assert jobs[0].input_lfns == ("/store/a.root", "/store/b.root")
    assert jobs[1].input_lfns == ("/store/c.root",)


def test_does_not_break_component_to_satisfy_files_per_job():
    files = (
        SplitFile(
            lfn="/store/a.root", events=1, size=10, run_lumis=_rl((1, 1))
        ),
        SplitFile(
            lfn="/store/b.root",
            events=1,
            size=10,
            run_lumis=_rl((2, 1), (2, 2)),
        ),
        SplitFile(
            lfn="/store/c.root", events=1, size=10, run_lumis=_rl((2, 2))
        ),
    )
    # After packing a alone (1 file), b+c is a 2-file component; with
    # files_per_job=2 it still fits in a new job as one unit.
    jobs = LumiAwareFileSplitter().split(
        LumiAwareFileRequest(files=files, files_per_job=2)
    ).jobs
    assert len(jobs) == 2
    assert jobs[0].input_lfns == ("/store/a.root",)
    assert jobs[1].input_lfns == ("/store/b.root", "/store/c.root")


def test_empty_run_lumis_rejected():
    with pytest.raises(ValueError, match="empty run_lumis"):
        LumiAwareFileSplitter().split(
            LumiAwareFileRequest(
                files=(
                    SplitFile(lfn="/store/a.root", events=1, size=10),
                ),
                files_per_job=1,
            )
        )


def test_component_over_max_walltime_is_unsplittable():
    files = (
        SplitFile(
            lfn="/store/a.root",
            events=40,
            size=10,
            run_lumis=_rl((1, 1)),
        ),
        SplitFile(
            lfn="/store/b.root",
            events=40,
            size=10,
            run_lumis=_rl((1, 1)),
        ),
    )
    jobs = LumiAwareFileSplitter().split(
        LumiAwareFileRequest(
            files=files,
            files_per_job=10,
            rates=ResourceRates(time_per_event=1.0),
            budgets=ResourceBudgets(max_job_walltime=50.0),
        )
    ).jobs
    assert len(jobs) == 1
    assert jobs[0].unsplittable is True
    assert jobs[0].input_lfns == ("/store/a.root", "/store/b.root")
    assert jobs[0].estimates.walltime == 80.0


def test_component_with_resource_budgets():
    files = (
        SplitFile(
            lfn="/store/a.root",
            events=40,
            size=10,
            run_lumis=_rl((1, 1)),
        ),
        SplitFile(
            lfn="/store/b.root",
            events=40,
            size=10,
            run_lumis=_rl((1, 2)),
        ),
    )
    jobs = LumiAwareFileSplitter().split(
        LumiAwareFileRequest(
            files=files,
            files_per_job=10,
            rates=ResourceRates(time_per_event=1.0),
            budgets=ResourceBudgets(max_job_walltime=50.0),
        )
    ).jobs
    # files are assigned to different jobs because of the resource budgets
    assert len(jobs) == 2
    assert jobs[0].unsplittable is False
    assert jobs[1].unsplittable is False
    assert jobs[0].input_lfns == ("/store/a.root",)
    assert jobs[1].input_lfns == ("/store/b.root",)


def test_deterministic_for_same_input():
    files = (
        SplitFile(
            lfn="/store/b.root", events=2, size=20, run_lumis=_rl((1, 1))
        ),
        SplitFile(
            lfn="/store/a.root", events=1, size=10, run_lumis=_rl((1, 1))
        ),
    )
    request = LumiAwareFileRequest(files=files, files_per_job=5)
    splitter = LumiAwareFileSplitter()
    assert splitter.split(request) == splitter.split(request)
