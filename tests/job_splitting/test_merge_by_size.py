"""Unit tests for MergeBySizeSplitter."""

import pytest

from cms_wm_core.job_splitting.merge_by_size import (
    MergeBySizeRequest,
    MergeBySizeSplitter,
)
from cms_wm_core.job_splitting.types import ResourceRates, SplitFile


def _file(lfn: str, *, size: int, events: int = 0) -> SplitFile:
    return SplitFile(lfn=lfn, events=events, size=size)


def test_name():
    assert MergeBySizeSplitter().name == "MergeBySize"


def test_empty_files_returns_no_jobs():
    result = MergeBySizeSplitter().split(
        MergeBySizeRequest(
            files=(),
            min_output_size_bytes=10,
            max_output_size_bytes=100,
        )
    )
    assert result.jobs == ()


def test_rejects_invalid_min_max():
    with pytest.raises(ValueError, match="min_output_size_bytes must be > 0"):
        MergeBySizeSplitter().split(
            MergeBySizeRequest(
                files=(),
                min_output_size_bytes=0,
                max_output_size_bytes=10,
            )
        )
    with pytest.raises(ValueError, match="max_output_size_bytes must be > 0"):
        MergeBySizeSplitter().split(
            MergeBySizeRequest(
                files=(),
                min_output_size_bytes=10,
                max_output_size_bytes=0,
            )
        )
    with pytest.raises(ValueError, match="max_output_size_bytes must be >="):
        MergeBySizeSplitter().split(
            MergeBySizeRequest(
                files=(),
                min_output_size_bytes=50,
                max_output_size_bytes=10,
            )
        )


def test_fills_toward_max_skipping_files_that_do_not_fit():
    """After seeding, scan all remaining files and add any that fit under max."""
    # Descending: 70, 40, 30, 25 — seed 70, skip 40, add 30 (=100); then 40+25
    files = (
        _file("/store/a.root", size=70, events=7),
        _file("/store/b.root", size=40, events=4),
        _file("/store/c.root", size=30, events=3),
        _file("/store/d.root", size=25, events=2),
    )
    result = MergeBySizeSplitter().split(
        MergeBySizeRequest(
            files=files,
            min_output_size_bytes=50,
            max_output_size_bytes=100,
        )
    )
    assert len(result.jobs) == 2
    assert result.jobs[0].input_lfns == ("/store/a.root", "/store/c.root")
    assert result.jobs[0].estimates.network == 100.0
    assert result.jobs[0].n_events == 10
    assert result.jobs[1].input_lfns == ("/store/b.root", "/store/d.root")
    assert result.jobs[1].estimates.network == 65.0
    assert all(not j.unsplittable for j in result.jobs)


def test_mixes_large_seed_with_smaller_files_in_slack():
    """Descending seed leaves slack that later small files can fill."""
    files = (
        _file("/store/z_large.root", size=90),
        _file("/store/a_small.root", size=10),
        _file("/store/b_small.root", size=10),
    )
    result = MergeBySizeSplitter().split(
        MergeBySizeRequest(
            files=files,
            min_output_size_bytes=30,
            max_output_size_bytes=100,
        )
    )
    # Seed 90 + first 10 = 100; second 10 does not fit → remainder alone.
    assert [j.input_lfns for j in result.jobs] == [
        ("/store/a_small.root", "/store/z_large.root"),
        ("/store/b_small.root",),
    ]
    assert result.jobs[0].estimates.network == 100.0
    assert result.jobs[1].estimates.network == 10.0


def test_single_file_over_max_is_alone_not_unsplittable():
    files = (
        _file("/store/big.root", size=500, events=10),
        _file("/store/small.root", size=20, events=2),
    )
    result = MergeBySizeSplitter().split(
        MergeBySizeRequest(
            files=files,
            min_output_size_bytes=50,
            max_output_size_bytes=100,
        )
    )
    assert len(result.jobs) == 2
    assert result.jobs[0].input_lfns == ("/store/big.root",)
    assert result.jobs[0].estimates.network == 500.0
    assert result.jobs[0].unsplittable is False
    assert result.jobs[1].input_lfns == ("/store/small.root",)
    assert result.jobs[1].unsplittable is False


def test_always_flush_undersized_tail():
    files = (
        _file("/store/a.root", size=10),
        _file("/store/b.root", size=10),
    )
    result = MergeBySizeSplitter().split(
        MergeBySizeRequest(
            files=files,
            min_output_size_bytes=50,
            max_output_size_bytes=100,
        )
    )
    assert len(result.jobs) == 1
    assert result.jobs[0].input_lfns == ("/store/a.root", "/store/b.root")
    assert result.jobs[0].estimates.network == 20.0


def test_flush_current_before_oversize_file():
    files = (
        _file("/store/a.root", size=20),
        _file("/store/b.root", size=200),
    )
    result = MergeBySizeSplitter().split(
        MergeBySizeRequest(
            files=files,
            min_output_size_bytes=50,
            max_output_size_bytes=100,
        )
    )
    assert [j.input_lfns for j in result.jobs] == [
        ("/store/b.root",),
        ("/store/a.root",),
    ]


def test_deterministic_regardless_of_file_order():
    files_ab = (
        _file("/store/a.root", size=40),
        _file("/store/b.root", size=40),
        _file("/store/c.root", size=40),
    )
    files_ba = (
        _file("/store/c.root", size=40),
        _file("/store/b.root", size=40),
        _file("/store/a.root", size=40),
    )
    splitter = MergeBySizeSplitter()
    req = dict(min_output_size_bytes=50, max_output_size_bytes=100)
    assert splitter.split(
        MergeBySizeRequest(files=files_ab, **req)
    ) == splitter.split(MergeBySizeRequest(files=files_ba, **req))


def test_estimates_use_optional_rates():
    """Merge estimates ignore transient rates (output is fully persisted)."""
    files = (_file("/store/a.root", size=10, events=5),)
    result = MergeBySizeSplitter().split(
        MergeBySizeRequest(
            files=files,
            min_output_size_bytes=1,
            max_output_size_bytes=100,
            rates=ResourceRates(
                time_per_event=2.0,
                # Non-zero on purpose: MergeBySize must force transient to 0.
                transient_output_size_per_event=3.0,
                persisted_output_size_per_event=1.0,
            ),
        )
    )
    job = result.jobs[0]
    assert job.n_events == 5
    assert job.estimates.walltime == 10.0
    assert job.estimates.persisted_output == 5.0
    assert job.estimates.scratch_disk == 5.0  # persisted only
    assert job.estimates.network == 10.0
