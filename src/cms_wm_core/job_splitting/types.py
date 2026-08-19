"""Shared data types for job splitting.

This module holds **data only** (dataclasses). It does not pack files into
jobs. Algorithms import these types so inputs and outputs have explicit,
named fields instead of bare dicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RunLumiEvents:
    """One run / luminosity-section / event-count triple on a file.

    ``events`` may be ``None`` for legacy metadata (no per-lumi count).
    Event-aware algorithms then substitute a file-level average.

    A single file may carry on the order of **tens of thousands** of these
    entries. Prefer compact storage and avoid copying this table casually.
    """

    run: int
    lumi: int
    events: int | None = None


@dataclass(frozen=True)
class RunLumiRange:
    """Inclusive contiguous lumi range within one run (job mask entry)."""

    run: int
    first_lumi: int
    last_lumi: int

    def __post_init__(self) -> None:
        if self.first_lumi > self.last_lumi:
            raise ValueError(
                f"first_lumi ({self.first_lumi}) > last_lumi ({self.last_lumi})"
            )


@dataclass(frozen=True)
class SplitFile:
    """One input file already resolved by the caller (no discovery here).

    Unused by no-input EventBased (MC), which takes event/lumi offsets on the
    request rather than files.
    """

    lfn: str
    events: int
    size: int
    # Unused in v1; reserved for a future input-file EventBased splitter.
    first_event: int = 0
    # Run/lumi map; empty if the algorithm does not need it (e.g. FileBased).
    # Ordered for determinism (caller or splitter should sort stably).
    run_lumis: tuple[RunLumiEvents, ...] = ()


@dataclass(frozen=True)
class ResourceRates:
    """How resource cost scales with events (caller-provided or derived)."""

    time_per_event: float = 0.0
    input_size_per_event: float = 0.0
    transient_output_size_per_event: float = 0.0
    persisted_output_size_per_event: float = 0.0


@dataclass(frozen=True)
class ResourceBudgets:
    """Soft targets and hard maxima for closing / rejecting jobs.

    Invariant when set: each target should be <= the matching maximum.
    Units are TBD in the typed API (seconds; bytes vs MB).
    """

    target_job_walltime: float | None = None
    max_job_walltime: float | None = None
    target_job_disk: float | None = None
    max_job_disk: float | None = None


@dataclass(frozen=True)
class ResourceEstimates:
    """Estimated cost of one job (splitter output; no memory).

    ``scratch_disk`` is peak local disk while the job runs (transient plus
    persisted outputs). ``persisted_output`` is the subset that must be staged
    out after processing; it is already included in ``scratch_disk``.
    """

    walltime: float = 0.0
    scratch_disk: float = 0.0
    persisted_output: float = 0.0
    network: float = 0.0


@dataclass(frozen=True)
class SplitJob:
    """One job produced by a splitter.

    File-oriented splitters fill ``input_lfns`` and ``n_events`` (sum of
    assigned file-level event counts). EventBased (MC) uses ``first_event`` /
    ``n_events`` as a half-open range
    ``[first_event, first_event + n_events)`` and a unique ``lumi``.
    EventAwareLumi fills ``input_lfns``, ``run_lumi_mask``, and ``n_events``
    as the assigned (or estimated) processing event total.
    """

    # Stable order of LFNs (determinism); empty for no-input EventBased.
    input_lfns: tuple[str, ...] = ()
    estimates: ResourceEstimates = field(default_factory=ResourceEstimates)
    # Half-open event range start (EventBased); None when unused.
    first_event: int | None = None
    # Assigned / estimated event total for characterization and estimates.
    # FileBased / LumiAwareFile: sum of file ``events``.
    # EventBased: generated range length.
    # EventAwareLumi: sum of packed lumi weights.
    n_events: int | None = None
    # Unique luminosity section id for MC EventBased jobs.
    lumi: int | None = None
    # Compact run/lumi mask for processing splitters (EventAwareLumi).
    run_lumi_mask: tuple[RunLumiRange, ...] = ()
    # True when this unit cannot fit under maxima (unsplittable).
    unsplittable: bool = False
    unsplittable_reason: str | None = None


@dataclass(frozen=True)
class SplitResult:
    """Full splitter output: an ordered sequence of jobs.

    This in-memory shape is fine for early algorithms and tests. Large
    workflows can yield tens of thousands of jobs on the **workload
    management** side; a later revision may stream or chunk results so WM
    process memory stays bounded (see design doc).
    """

    jobs: tuple[SplitJob, ...]
