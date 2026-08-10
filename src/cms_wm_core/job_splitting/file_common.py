"""Shared helpers for file-oriented job splitters.

Used by ``file_based`` and ``file_lumi_aware``. Not part of the public package
API (not re-exported from ``__init__``); import from algorithm modules instead.
"""

from __future__ import annotations

from cms_wm_core.job_splitting.types import (
    ResourceBudgets,
    ResourceEstimates,
    ResourceRates,
    SplitFile,
    SplitJob,
)


def estimates_for(
    files: list[SplitFile],
    rates: ResourceRates,
) -> ResourceEstimates:
    total_events = sum(f.events for f in files)
    transient = total_events * rates.transient_output_size_per_event
    persisted = total_events * rates.persisted_output_size_per_event
    return ResourceEstimates(
        walltime=total_events * rates.time_per_event,
        # Both live on the worker scratch area for part of the job lifetime.
        scratch_disk=transient + persisted,
        persisted_output=persisted,
        network=float(sum(f.size for f in files)),
    )


def exceeds_maximum(
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


def meets_soft_target(
    estimates: ResourceEstimates,
    budgets: ResourceBudgets,
) -> bool:
    """True when the current job should close before taking more work."""
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


def make_job(
    files: list[SplitFile],
    rates: ResourceRates,
    *,
    unsplittable: bool = False,
    reason: str | None = None,
) -> SplitJob:
    ordered = sorted(files, key=lambda f: f.lfn)
    return SplitJob(
        input_lfns=tuple(f.lfn for f in ordered),
        estimates=estimates_for(ordered, rates),
        unsplittable=unsplittable,
        unsplittable_reason=reason,
    )


def validate_file_basics(file_: SplitFile) -> None:
    if file_.events < 0:
        raise ValueError(
            f"file {file_.lfn!r} has negative events: {file_.events}"
        )
    if file_.size < 0:
        raise ValueError(
            f"file {file_.lfn!r} has negative size: {file_.size}"
        )
