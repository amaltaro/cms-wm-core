"""File-based job splitting.

Ported and simplified from WMCore ``FileBased``:
https://github.com/dmwm/WMCore/blob/master/src/python/WMCore/JobSplitting/FileBased.py

Packs whole files into jobs using ``files_per_job``. The caller must supply a
location-consistent file list; this algorithm does not bucket by site.

Intentionally omitted (see ``docs/file-based.md``):

* location sorting / multi-site job groups
* run / lumi masks and run boundaries (use ``file_lumi_aware`` instead)
* ``jobs_per_group`` (persistence packaging, not packing math)
* ``include_parents`` / parent LFN resolution (deferred)
* memory requirements on jobs
"""

from __future__ import annotations

from dataclasses import dataclass

from cms_wm_core.job_splitting.base import JobSplitter
from cms_wm_core.job_splitting.file_common import (
    estimates_for,
    exceeds_maximum,
    make_job,
    meets_soft_target,
    validate_file_basics,
)
from cms_wm_core.job_splitting.types import (
    ResourceBudgets,
    ResourceRates,
    SplitFile,
    SplitJob,
    SplitResult,
)


@dataclass(frozen=True)
class FileBasedRequest:
    """Inputs for :class:`FileBasedSplitter`."""

    files: tuple[SplitFile, ...]
    files_per_job: int
    rates: ResourceRates = ResourceRates()
    budgets: ResourceBudgets = ResourceBudgets()


class FileBasedSplitter(JobSplitter[FileBasedRequest]):
    """Split by whole files using ``files_per_job`` (WMCore FileBased v1)."""

    @property
    def name(self) -> str:
        return "FileBased"

    def split(self, request: FileBasedRequest) -> SplitResult:
        if request.files_per_job < 1:
            raise ValueError(
                f"files_per_job must be >= 1, got {request.files_per_job}"
            )
        for file_ in request.files:
            validate_file_basics(file_)

        ordered = sorted(request.files, key=lambda f: f.lfn)
        jobs: list[SplitJob] = []
        current: list[SplitFile] = []

        for file_ in ordered:
            alone = estimates_for([file_], request.rates)
            alone_reason = exceeds_maximum(alone, request.budgets)
            if alone_reason is not None:
                if current:
                    jobs.append(make_job(current, request.rates))
                    current = []
                jobs.append(
                    make_job(
                        [file_],
                        request.rates,
                        unsplittable=True,
                        reason=alone_reason,
                    )
                )
                continue

            if current:
                should_close = False
                if len(current) >= request.files_per_job:
                    should_close = True
                elif meets_soft_target(
                    estimates_for(current, request.rates),
                    request.budgets,
                ):
                    should_close = True
                else:
                    combined = estimates_for(current + [file_], request.rates)
                    if exceeds_maximum(combined, request.budgets) is not None:
                        should_close = True
                if should_close:
                    jobs.append(make_job(current, request.rates))
                    current = []

            current.append(file_)

        if current:
            jobs.append(make_job(current, request.rates))

        return SplitResult(jobs=tuple(jobs))
