"""File-based job splitting.

Ported and simplified from WMCore ``FileBased``:
https://github.com/dmwm/WMCore/blob/master/src/python/WMCore/JobSplitting/FileBased.py

Packs whole files into jobs using ``files_per_job``. The caller must supply a
location-consistent file list; this algorithm does not bucket by site.

Intentionally omitted (see ``docs/job-splitting.md``):

* location sorting / multi-site job groups
* run / lumi masks and run boundaries (use a lumi-aware splitter instead)
* ``jobs_per_group`` (persistence packaging, not packing math)
* ``include_parents`` / parent LFN resolution (deferred)
* memory requirements on jobs
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
    """Inputs for :class:`FileBasedSplitter`."""

    files: tuple[SplitFile, ...]
    files_per_job: int
    rates: ResourceRates = ResourceRates()
    budgets: ResourceBudgets = ResourceBudgets()


def _estimates_for(
    files: list[SplitFile],
    rates: ResourceRates,
) -> ResourceEstimates:
    total_events = sum(f.events for f in files)
    return ResourceEstimates(
        walltime=total_events * rates.time_per_event,
        scratch_disk=total_events * rates.transient_output_size_per_event,
        persisted_output=total_events * rates.persisted_output_size_per_event,
        network=float(sum(f.size for f in files)),
    )


def _exceeds_maximum(
    estimates: ResourceEstimates,
    budgets: ResourceBudgets,
) -> str | None:
    """Return a reason string if estimates break a hard maximum."""
    if (
        budgets.max_job_walltime is not None
        and estimates.walltime > budgets.max_job_walltime
    ):
        return (
            f"estimated walltime {estimates.walltime} exceeds "
            f"max_job_walltime {budgets.max_job_walltime}"
        )
    if (
        budgets.max_job_disk is not None
        and estimates.scratch_disk > budgets.max_job_disk
    ):
        return (
            f"estimated scratch disk {estimates.scratch_disk} exceeds "
            f"max_job_disk {budgets.max_job_disk}"
        )
    return None


def _meets_soft_target(
    estimates: ResourceEstimates,
    budgets: ResourceBudgets,
) -> bool:
    """True when the current job should close before taking more files."""
    if (
        budgets.target_job_walltime is not None
        and estimates.walltime >= budgets.target_job_walltime
    ):
        return True
    if (
        budgets.target_job_disk is not None
        and estimates.scratch_disk >= budgets.target_job_disk
    ):
        return True
    return False


def _make_job(
    files: list[SplitFile],
    rates: ResourceRates,
    *,
    unsplittable: bool = False,
    reason: str | None = None,
) -> SplitJob:
    return SplitJob(
        input_lfns=tuple(f.lfn for f in files),
        estimates=_estimates_for(files, rates),
        unsplittable=unsplittable,
        unsplittable_reason=reason,
    )


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
            if file_.events < 0:
                raise ValueError(
                    f"file {file_.lfn!r} has negative events: {file_.events}"
                )
            if file_.size < 0:
                raise ValueError(
                    f"file {file_.lfn!r} has negative size: {file_.size}"
                )

        ordered = sorted(request.files, key=lambda f: f.lfn)
        jobs: list[SplitJob] = []
        current: list[SplitFile] = []

        for file_ in ordered:
            alone = _estimates_for([file_], request.rates)
            alone_reason = _exceeds_maximum(alone, request.budgets)
            if alone_reason is not None:
                if current:
                    jobs.append(_make_job(current, request.rates))
                    current = []
                jobs.append(
                    _make_job(
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
                elif _meets_soft_target(
                    _estimates_for(current, request.rates),
                    request.budgets,
                ):
                    should_close = True
                else:
                    combined = _estimates_for(current + [file_], request.rates)
                    if _exceeds_maximum(combined, request.budgets) is not None:
                        should_close = True
                if should_close:
                    jobs.append(_make_job(current, request.rates))
                    current = []

            current.append(file_)

        if current:
            jobs.append(_make_job(current, request.rates))

        return SplitResult(jobs=tuple(jobs))
