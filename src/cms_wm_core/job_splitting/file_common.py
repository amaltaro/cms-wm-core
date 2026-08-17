"""Shared helpers for job splitters.

Used by file-oriented and event-based algorithms. Not part of the public
package API (not re-exported from ``__init__``).
"""

from __future__ import annotations

from cms_wm_core.job_splitting.types import (
    ResourceBudgets,
    ResourceEstimates,
    ResourceRates,
    SplitFile,
    SplitJob,
)


def estimates_for_events(
    n_events: int,
    rates: ResourceRates,
    *,
    network: float = 0.0,
) -> ResourceEstimates:
    """Resource estimates for a known event count (no input files required)."""
    transient = n_events * rates.transient_output_size_per_event
    persisted = n_events * rates.persisted_output_size_per_event
    return ResourceEstimates(
        walltime=n_events * rates.time_per_event,
        scratch_disk=transient + persisted,
        persisted_output=persisted,
        network=network,
    )


def estimates_for(
    files: list[SplitFile],
    rates: ResourceRates,
) -> ResourceEstimates:
    total_events = sum(f.events for f in files)
    return estimates_for_events(
        total_events,
        rates,
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
    n_events = sum(f.events for f in ordered)
    return SplitJob(
        input_lfns=tuple(f.lfn for f in ordered),
        estimates=estimates_for(ordered, rates),
        n_events=n_events,
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
