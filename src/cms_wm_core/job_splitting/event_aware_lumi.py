"""Event-aware lumi packing for final processing with real input files.

Work unit is ``(run, lumi)`` on **one** file; events size jobs. Adapted from
WMCore ``EventAwareLumiBased`` (production) and ``EventAwareLumiByWork``
(work-centric packing):

* https://github.com/dmwm/WMCore/blob/master/src/python/WMCore/JobSplitting/EventAwareLumiBased.py
* https://github.com/dmwm/WMCore/blob/master/src/python/WMCore/JobSplitting/EventAwareLumiByWork.py

``events_per_job = floor(target_job_walltime / time_per_event)``. Within each
file, per-lumi ``events`` must be uniformly ``int`` (used directly) or
uniformly ``None`` (each lumi weighted ``round(file.events / n_lumis)``).
Mixed known/legacy event count metadata in one file is rejected. Jobs
accumulate one or more lumis. Packing closes before the next lumi when adding
it would not get closer to the event target (ByWork closest-to-target rule).

Each ``(run, lumi)`` must appear in exactly one input file. Workflows that
share the same run/lumi across files must use :class:`FileLumiAwareSplitter`
instead — that is the only algorithm that supports that case.

v1: process every lumi on each input file (no allow-list); no run/file
boundary flags (open question in ``docs/event-aware-lumi.md``); jobs may span
runs and files. Omitted: location bucketing, ACDC, parents, pileup baggage.
"""

from __future__ import annotations

from dataclasses import dataclass

from cms_wm_core.job_splitting.base import JobSplitter
from cms_wm_core.job_splitting.event_based import events_per_job
from cms_wm_core.job_splitting.file_common import (
    estimates_for_events,
    exceeds_maximum,
    validate_file_basics,
)
from cms_wm_core.job_splitting.types import (
    ResourceBudgets,
    ResourceRates,
    RunLumiRange,
    SplitFile,
    SplitJob,
    SplitResult,
)

RunLumiKey = tuple[int, int]


@dataclass(frozen=True)
class EventAwareLumiRequest:
    """Inputs for :class:`EventAwareLumiSplitter`."""

    files: tuple[SplitFile, ...]
    target_job_walltime: float
    rates: ResourceRates
    budgets: ResourceBudgets = ResourceBudgets()


@dataclass(frozen=True)
class _WorkUnit:
    """One atomic ``(run, lumi)`` on a single file, with event weight."""

    run: int
    lumi: int
    events: int
    file: SplitFile


def _average_events_per_lumi(file_: SplitFile) -> int:
    n_lumis = len(file_.run_lumis)
    if n_lumis == 0:
        return 0
    return int(round(file_.events / n_lumis))


def _lumi_weight(entry_events: int | None, file_avg: int) -> int:
    if entry_events is None:
        return file_avg
    return entry_events


def _validate_run_lumi_events(file_: SplitFile) -> None:
    """Require non-empty uniform ``run_lumis`` event metadata.

    Every lumi in the file must carry an ``int`` event count, or every lumi
    must be ``None`` (legacy average). Mixing both in one file is rejected.
    """
    if not file_.run_lumis:
        raise ValueError(
            f"file {file_.lfn!r} has empty run_lumis; "
            "EventAwareLumi requires at least one (run, lumi)"
        )
    known = [e.events is not None for e in file_.run_lumis]
    if any(known) and not all(known):
        raise ValueError(
            f"file {file_.lfn!r} mixes known and legacy (None) per-lumi "
            "event counts; use all int or all None"
        )
    for entry in file_.run_lumis:
        if entry.events is not None and entry.events < 0:
            raise ValueError(
                f"file {file_.lfn!r} has negative events for "
                f"run={entry.run} lumi={entry.lumi}: {entry.events}"
            )


def _build_work_units(files: tuple[SplitFile, ...]) -> list[_WorkUnit]:
    """Build ordered ``(run, lumi)`` work units with resolved event weights.

    Sorts files by LFN and lumis within each file so packing order is
    deterministic. Also rejects a ``(run, lumi)`` that appears in more than
    one file (FileLumiAware-only case).

    Note: that cross-file uniqueness scan is a safety check. If callers
    always guarantee one file per ``(run, lumi)`` and this becomes a
    performance hotspot, the check could be removed or made optional.
    """
    ordered_files = sorted(files, key=lambda f: f.lfn)
    lfn_by_run_lumi: dict[RunLumiKey, str] = {}
    units: list[_WorkUnit] = []

    for file_ in ordered_files:
        avg = _average_events_per_lumi(file_)
        # Stable within file when caller order varies.
        entries = sorted(file_.run_lumis, key=lambda e: (e.run, e.lumi))
        for entry in entries:
            key = (entry.run, entry.lumi)
            if key in lfn_by_run_lumi:
                raise ValueError(
                    f"run/lumi {key} appears in both "
                    f"{lfn_by_run_lumi[key]!r} and {file_.lfn!r}; "
                    "EventAwareLumi requires each (run, lumi) in a single "
                    "file (use FileLumiAware for shared lumis)"
                )
            lfn_by_run_lumi[key] = file_.lfn
            units.append(
                _WorkUnit(
                    run=entry.run,
                    lumi=entry.lumi,
                    events=_lumi_weight(entry.events, avg),
                    file=file_,
                )
            )
    return units


def _compact_mask(lumis: list[RunLumiKey]) -> tuple[RunLumiRange, ...]:
    """Merge contiguous lumis within a run into inclusive ranges."""
    if not lumis:
        return ()
    ordered = sorted(lumis)
    ranges: list[RunLumiRange] = []
    run, first, last = ordered[0][0], ordered[0][1], ordered[0][1]
    for next_run, next_lumi in ordered[1:]:
        if next_run == run and next_lumi == last + 1:
            last = next_lumi
            continue
        ranges.append(RunLumiRange(run=run, first_lumi=first, last_lumi=last))
        run, first, last = next_run, next_lumi, next_lumi
    ranges.append(RunLumiRange(run=run, first_lumi=first, last_lumi=last))
    return tuple(ranges)


def _should_close_before_add(
    events_in_job: int,
    events_in_lumi: int,
    target: int,
) -> bool:
    """ByWork closest-to-target rule.

    Zero-event lumis are valid work and must still be assigned to a job.
    When either side is zero, do not close: always add the lumi to the
    current job (otherwise the ``>=`` tie would split off empty lumis).
    """
    if events_in_job <= 0 or events_in_lumi <= 0:
        return False
    with_lumi = abs(events_in_job + events_in_lumi - target)
    without = abs(events_in_job - target)
    return with_lumi >= without


@dataclass
class _PackState:
    """Mutable accumulator while packing work units into jobs."""

    rates: ResourceRates
    budgets: ResourceBudgets
    jobs: list[SplitJob]
    current_lumis: list[RunLumiKey]
    current_files: dict[str, SplitFile]
    events_in_job: int


class EventAwareLumiSplitter(JobSplitter[EventAwareLumiRequest]):
    """Pack ``(run, lumi)`` work units by event target and walltime rates."""

    @property
    def name(self) -> str:
        """Stable algorithm id."""
        return "EventAwareLumi"

    def _emit_current(
        self,
        state: _PackState,
        *,
        unsplittable: bool = False,
        reason: str | None = None,
    ) -> None:
        """Flush the current accumulator into ``state.jobs`` and reset it."""
        if not state.current_lumis and not state.current_files:
            return
        file_list = sorted(state.current_files.values(), key=lambda f: f.lfn)
        network = float(sum(f.size for f in file_list))
        estimates = estimates_for_events(
            state.events_in_job,
            state.rates,
            network=network,
        )
        if not unsplittable:
            reason = exceeds_maximum(estimates, state.budgets)
            unsplittable = reason is not None
        state.jobs.append(
            SplitJob(
                input_lfns=tuple(f.lfn for f in file_list),
                estimates=estimates,
                n_events=state.events_in_job,
                run_lumi_mask=_compact_mask(state.current_lumis),
                unsplittable=unsplittable,
                unsplittable_reason=reason,
            )
        )
        state.current_lumis = []
        state.current_files = {}
        state.events_in_job = 0

    def _start_with(self, state: _PackState, unit: _WorkUnit) -> None:
        """Begin a new job with ``unit``; emit immediately if unsplittable."""
        state.current_lumis.append((unit.run, unit.lumi))
        state.current_files[unit.file.lfn] = unit.file
        state.events_in_job = unit.events
        alone = estimates_for_events(
            unit.events,
            state.rates,
            network=float(unit.file.size),
        )
        alone_reason = exceeds_maximum(alone, state.budgets)
        if alone_reason is not None:
            self._emit_current(state, unsplittable=True, reason=alone_reason)

    def split(self, request: EventAwareLumiRequest) -> SplitResult:
        """Pack input files into jobs by closest-to-target event sizing."""
        if not request.files:
            return SplitResult(jobs=())

        for file_ in request.files:
            validate_file_basics(file_)
            _validate_run_lumi_events(file_)

        target = events_per_job(
            request.target_job_walltime,
            request.rates.time_per_event,
        )
        work_units = _build_work_units(request.files)
        state = _PackState(
            rates=request.rates,
            budgets=request.budgets,
            jobs=[],
            current_lumis=[],
            current_files={},
            events_in_job=0,
        )

        for unit in work_units:
            if not state.current_lumis:
                self._start_with(state, unit)
                continue
            if _should_close_before_add(state.events_in_job, unit.events, target):
                self._emit_current(state)
                self._start_with(state, unit)
                continue
            state.current_lumis.append((unit.run, unit.lumi))
            state.current_files[unit.file.lfn] = unit.file
            state.events_in_job += unit.events

        self._emit_current(state)
        return SplitResult(jobs=tuple(state.jobs))
