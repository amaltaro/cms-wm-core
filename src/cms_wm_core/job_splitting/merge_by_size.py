"""Merge job packing by input file size (min/max output band).

Adapted from WMCore ``MergeBySize``:
https://github.com/dmwm/WMCore/blob/master/src/python/WMCore/JobSplitting/MergeBySize.py

Packs whole files into merge jobs so the sum of input sizes stays within
``[min_output_size_bytes, max_output_size_bytes]`` when combining files.

Files are ordered by **size descending, then LFN**. Each job starts with the
next remaining file; the packer then scans **all** remaining files and adds
any that still fit under ``max`` (even after ``min`` is reached). That is
``O(n^2)`` in the number of files but tends to fill closer to ``max``.

A single file larger than ``max`` becomes a normal one-file merge job (not
unsplittable). Merge has no scratch-only (transient) product — output is
persisted to shared storage — so estimates force
``transient_output_size_per_event=0``; scratch still includes persisted
bytes. v1 leftover policy: every started job is emitted after the full scan
(complete pre-scoped requests). Location bucketing, run/lumi merge order,
and event masks are omitted; see ``docs/merge-by-size.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from cms_wm_core.job_splitting.base import JobSplitter
from cms_wm_core.job_splitting.file_common import make_job, validate_file_basics
from cms_wm_core.job_splitting.types import (
    ResourceBudgets,
    ResourceRates,
    SplitFile,
    SplitResult,
)


@dataclass(frozen=True)
class MergeBySizeRequest:
    """Inputs for :class:`MergeBySizeSplitter`."""

    files: tuple[SplitFile, ...]
    min_output_size_bytes: int
    max_output_size_bytes: int
    rates: ResourceRates = ResourceRates()
    budgets: ResourceBudgets = ResourceBudgets()


class MergeBySizeSplitter(JobSplitter[MergeBySizeRequest]):
    """Pack files into merge jobs, filling each job toward ``max``."""

    @property
    def name(self) -> str:
        """Stable algorithm id."""
        return "MergeBySize"

    def split(self, request: MergeBySizeRequest) -> SplitResult:
        """Pack files into merge jobs (size-desc fill; always emit)."""
        if request.min_output_size_bytes <= 0:
            raise ValueError(
                "min_output_size_bytes must be > 0, got "
                f"{request.min_output_size_bytes}"
            )
        if request.max_output_size_bytes <= 0:
            raise ValueError(
                "max_output_size_bytes must be > 0, got "
                f"{request.max_output_size_bytes}"
            )
        if request.max_output_size_bytes < request.min_output_size_bytes:
            raise ValueError(
                "max_output_size_bytes must be >= min_output_size_bytes, got "
                f"min={request.min_output_size_bytes}, "
                f"max={request.max_output_size_bytes}"
            )
        for file_ in request.files:
            validate_file_basics(file_)

        if not request.files:
            return SplitResult(jobs=())

        # Merge writes the product to shared storage; no transient scratch.
        rates = replace(request.rates, transient_output_size_per_event=0.0)

        # Sort files by size descending, then LFN ascending.
        remaining = sorted(request.files, key=lambda f: (-f.size, f.lfn))
        jobs = []
        max_size = request.max_output_size_bytes

        while remaining:
            seed = remaining.pop(0)
            if seed.size > max_size:
                jobs.append(make_job([seed], rates))
                continue

            current = [seed]
            accum = seed.size
            index = 0
            while index < len(remaining):
                candidate = remaining[index]
                if accum + candidate.size <= max_size:
                    current.append(candidate)
                    accum += candidate.size
                    del remaining[index]
                    continue
                index += 1

            jobs.append(make_job(current, rates))

        return SplitResult(jobs=tuple(jobs))
