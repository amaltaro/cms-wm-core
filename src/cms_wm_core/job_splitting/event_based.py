"""Event-based job splitting for no-input Monte Carlo workflows.

Simplified from WMCore ``EventBased``:
https://github.com/dmwm/WMCore/blob/master/src/python/WMCore/JobSplitting/EventBased.py

Assigns disjoint half-open event ranges
``[first_event, first_event + n_events)`` and a unique integer luminosity
section per job. ``events_per_job`` is derived as
``floor(target_job_walltime / time_per_event)``.

Upstream ``MCFakeFile`` placeholders are not emitted; event/lumi fields on
``SplitJob`` replace that convention.

Intentionally omitted: real input-file event splitting, ACDC, parents,
location bucketing, deterministic pileup, memory packing.
"""

from __future__ import annotations

from dataclasses import dataclass

from cms_wm_core.job_splitting.base import JobSplitter
from cms_wm_core.job_splitting.file_common import (
    estimates_for_events,
    exceeds_maximum,
)
from cms_wm_core.job_splitting.types import (
    ResourceBudgets,
    ResourceRates,
    SplitJob,
    SplitResult,
)


@dataclass(frozen=True)
class EventBasedRequest:
    """Inputs for :class:`EventBasedSplitter` (no-input MC slice)."""

    total_events: int
    target_job_walltime: float
    rates: ResourceRates
    first_event: int = 1
    first_lumi: int = 1
    budgets: ResourceBudgets = ResourceBudgets()


def events_per_job(target_job_walltime: float, time_per_event: float) -> int:
    """Positive integer job size from walltime target and time per event."""
    if time_per_event <= 0.0:
        raise ValueError(
            f"time_per_event must be > 0, got {time_per_event}"
        )
    if target_job_walltime <= 0.0:
        raise ValueError(
            f"target_job_walltime must be > 0, got {target_job_walltime}"
        )
    n_events = int(target_job_walltime // time_per_event)
    if n_events < 1:
        raise ValueError(
            "events_per_job must be >= 1; got "
            f"floor({target_job_walltime} / {time_per_event}) = {n_events}"
        )
    return n_events


class EventBasedSplitter(JobSplitter[EventBasedRequest]):
    """Split a MC event request into disjoint event ranges and unique lumis."""

    @property
    def name(self) -> str:
        return "EventBased"

    def split(self, request: EventBasedRequest) -> SplitResult:
        if request.total_events < 0:
            raise ValueError(
                f"total_events must be >= 0, got {request.total_events}"
            )
        if request.first_event < 1:
            raise ValueError(
                f"first_event must be >= 1, got {request.first_event}"
            )
        if request.first_lumi < 1:
            raise ValueError(
                f"first_lumi must be >= 1, got {request.first_lumi}"
            )
        if request.total_events == 0:
            return SplitResult(jobs=())

        chunk = events_per_job(
            request.target_job_walltime,
            request.rates.time_per_event,
        )

        jobs: list[SplitJob] = []
        remaining = request.total_events
        current_event = request.first_event
        current_lumi = request.first_lumi

        while remaining > 0:
            n_events = min(chunk, remaining)
            estimates = estimates_for_events(n_events, request.rates)
            reason = exceeds_maximum(estimates, request.budgets)
            jobs.append(
                SplitJob(
                    input_lfns=(),
                    estimates=estimates,
                    first_event=current_event,
                    n_events=n_events,
                    lumi=current_lumi,
                    unsplittable=reason is not None,
                    unsplittable_reason=reason,
                )
            )
            remaining -= n_events
            current_event += n_events
            current_lumi += 1

        return SplitResult(jobs=tuple(jobs))
