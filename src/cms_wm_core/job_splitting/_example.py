"""Example of a concrete splitter request (not a real algorithm yet).

Shows how an algorithm-specific request sits beside the shared types, while
``JobSplitter.split`` stays the common entry point.
"""

from __future__ import annotations

from dataclasses import dataclass

from cms_wm_core.job_splitting.base import JobSplitter
from cms_wm_core.job_splitting.types import (
    ResourceBudgets,
    ResourceEstimates,
    ResourceRates,
    SplitFile,
    SplitJob,
    SplitResult,
)


@dataclass(frozen=True)
class FileBasedRequest:
    """Inputs for a future FileBased splitter (illustrative only)."""

    files: tuple[SplitFile, ...]
    files_per_job: int
    rates: ResourceRates = ResourceRates()
    budgets: ResourceBudgets = ResourceBudgets()


class IdentityFileSplitter(JobSplitter[FileBasedRequest]):
    """Toy splitter: one job per file, in LFN-sorted order.

    Exists only to demonstrate subclassing ``JobSplitter`` with a concrete
    request type. Replace with real FileBased packing later.
    """

    @property
    def name(self) -> str:
        return "IdentityFile"

    def split(self, request: FileBasedRequest) -> SplitResult:
        ordered = tuple(sorted(request.files, key=lambda f: f.lfn))
        jobs = tuple(
            SplitJob(
                input_lfns=(f.lfn,),
                estimates=ResourceEstimates(
                    walltime=f.events * request.rates.time_per_event,
                ),
            )
            for f in ordered
        )
        return SplitResult(job_groups=(jobs,))
