"""File-based splitting that keeps shared run+lumi tuples in one job.

Baseline packing matches :mod:`file_based` (``files_per_job``, resource
rates/budgets), with one extra constraint:

**Files that share any ``(run, lumi)`` must land in the same job.**

That is the only supported case where a single run+lumi may appear in more
than one file. Elsewhere in the system, a run+lumi is assumed to live in a
single file. Shared keys form connected components (transitively): if A
shares a lumi with B and B with C, then A, B, and C are one atomic unit.

Each input file must provide a non-empty ``run_lumis`` list. Per-lumi event
counts on ``RunLumiEvents`` are accepted for metadata but resource estimates
still use the file-level ``events`` / ``size`` fields (same as FileBased).

Intentionally omitted: location bucketing, lumi masks, parents,
``jobs_per_group``, memory packing.
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

RunLumiKey = tuple[int, int]


@dataclass(frozen=True)
class FileLumiAwareRequest:
    """Inputs for :class:`FileLumiAwareSplitter`."""

    files: tuple[SplitFile, ...]
    files_per_job: int
    rates: ResourceRates = ResourceRates()
    budgets: ResourceBudgets = ResourceBudgets()


def _run_lumi_keys(file_: SplitFile) -> frozenset[RunLumiKey]:
    return frozenset((entry.run, entry.lumi) for entry in file_.run_lumis)


def _connected_components(
    files: tuple[SplitFile, ...],
) -> list[list[SplitFile]]:
    """Group files that share any (run, lumi), including transitive links."""
    if not files:
        return []

    by_lfn = {f.lfn: f for f in files}
    lfns = sorted(by_lfn)
    index = {lfn: i for i, lfn in enumerate(lfns)}
    parent = list(range(len(lfns)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    key_to_lfns: dict[RunLumiKey, list[str]] = {}
    for file_ in files:
        for key in _run_lumi_keys(file_):
            key_to_lfns.setdefault(key, []).append(file_.lfn)

    for owners in key_to_lfns.values():
        if len(owners) < 2:
            continue
        first = index[owners[0]]
        for other in owners[1:]:
            union(first, index[other])

    groups: dict[int, list[SplitFile]] = {}
    for lfn in lfns:
        root = find(index[lfn])
        groups.setdefault(root, []).append(by_lfn[lfn])

    components = [groups[root] for root in sorted(groups)]
    components.sort(key=lambda comp: min(f.lfn for f in comp))
    return components


class FileLumiAwareSplitter(JobSplitter[FileLumiAwareRequest]):
    """FileBased packing that never splits a shared (run, lumi) across jobs."""

    @property
    def name(self) -> str:
        return "FileLumiAware"

    def split(self, request: FileLumiAwareRequest) -> SplitResult:
        if request.files_per_job < 1:
            raise ValueError(
                f"files_per_job must be >= 1, got {request.files_per_job}"
            )
        for file_ in request.files:
            validate_file_basics(file_)
            if not file_.run_lumis:
                raise ValueError(
                    f"file {file_.lfn!r} has empty run_lumis; "
                    "FileLumiAware requires at least one (run, lumi)"
                )

        components = _connected_components(request.files)
        jobs: list[SplitJob] = []
        current: list[SplitFile] = []

        for component in components:
            alone = estimates_for(component, request.rates)
            alone_reason = exceeds_maximum(alone, request.budgets)
            if alone_reason is not None:
                if current:
                    jobs.append(make_job(current, request.rates))
                    current = []
                jobs.append(
                    make_job(
                        component,
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
                elif (
                    len(current) + len(component) > request.files_per_job
                ):
                    # Do not break a component; close and start a new job.
                    should_close = True
                else:
                    combined = estimates_for(
                        current + component, request.rates
                    )
                    if exceeds_maximum(combined, request.budgets) is not None:
                        should_close = True
                if should_close:
                    jobs.append(make_job(current, request.rates))
                    current = []

            current.extend(component)

        if current:
            jobs.append(make_job(current, request.rates))

        return SplitResult(jobs=tuple(jobs))
