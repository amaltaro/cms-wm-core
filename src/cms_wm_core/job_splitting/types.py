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

    A single file may carry on the order of **tens of thousands** of these
    entries. Prefer compact storage and avoid copying this table casually.
    """

    run: int
    lumi: int
    events: int


@dataclass(frozen=True)
class SplitFile:
    """One input file already resolved by the caller (no discovery here)."""

    lfn: str
    events: int
    size: int = 0
    first_event: int = 0
    # Optional locality hints; empty means "unspecified".
    locations: frozenset[str] = field(default_factory=frozenset)
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
    """Estimated cost of one job (splitter output; no memory)."""

    walltime: float = 0.0
    scratch_disk: float = 0.0
    persisted_output: float = 0.0
    network: float = 0.0


@dataclass(frozen=True)
class SplitJob:
    """One job produced by a splitter."""

    # Stable order of LFNs (determinism).
    input_lfns: tuple[str, ...]
    estimates: ResourceEstimates = field(default_factory=ResourceEstimates)
    # True when this unit cannot fit under maxima (unsplittable).
    unsplittable: bool = False
    unsplittable_reason: str | None = None


@dataclass(frozen=True)
class SplitResult:
    """Full splitter output: ordered job groups, each an ordered list of jobs.

    This in-memory shape is fine for early algorithms and tests. Large
    workflows can yield tens of thousands of jobs on the **workload
    management** side; a later revision may stream or chunk results so WM
    process memory stays bounded (see design doc).
    """

    job_groups: tuple[tuple[SplitJob, ...], ...]
