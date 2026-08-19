# MergeBySize

Merge packing by min/max output size band.

Part of the [job-splitting design](README.md).

---

Upstream:
[MergeBySize.py](https://github.com/dmwm/WMCore/blob/master/src/python/WMCore/JobSplitting/MergeBySize.py).

Merge packing: combine **small input files** into merge jobs whose expected
**output** size is driven by the sum of those inputs. Used when many tiny
files must be merged into fewer, larger files for efficient storage and
downstream processing.

Implemented in ``merge_by_size.py`` (v1). Leftover policy for v1 is
**always flush** (every seeded job is emitted after a full remainder scan).
Packing uses size-descending order and rescans remaining files to fill toward
``max``; ``min`` defines the desired band and is validated on the request.

### Upstream behavior (summary)

[MergeBySize](https://github.com/dmwm/WMCore/blob/master/src/python/WMCore/JobSplitting/MergeBySize.py):

1. Requires a single `merge_size` threshold (close when accumulated input
   sizes reach it).
2. Optional `all_files` (overflow): if true, leftover files that never reach
   `merge_size` still become a final merge job; if false, leftovers are left
   for a later cycle.
3. Buckets by **location** (`sortByLocation`), then walks files in each bucket,
   accumulating `size` until `accumSize >= merge_size`, then emits a job and
   resets.
4. A single file with `size >= merge_size` closes a job by itself (alone in
   that merge job).
5. Sets a trivial event mask (`max/skip` events) on merge jobs.

The upstream module docstring also mentions grouping by run and sorting by
lumi; the current implementation does **not** do that — only location + size
accumulation. We do not invent run/lumi merge constraints unless a real
caller needs them.

### What drives splitting (cms-wm-core)

Prefer a **min / max band** over a single threshold. That lets the packer
keep adding files after the soft minimum so outputs grow toward (but not
past) the maximum — fewer tiny merge products, still within limits.

| Input | Role |
| --- | --- |
| File list with **`size`** (and `lfn`) | Units to pack; size is the packing signal |
| `min_output_size_bytes` | Soft floor: prefer not to emit a job below this
  when more files might still fit |
| `max_output_size_bytes` | Ceiling when **combining** files: do not add
  another file if the sum would exceed this (`min <= max`, both `> 0`) |

Assumption (same as other algorithms): the caller passes a
**location-consistent** file list. No location bucketing inside the core
splitter.

**Single file larger than max:** see open note below. Provisional v1: emit it
**alone as a normal merge job** (not `unsplittable`), so the already-processed
file still gets a merge attempt.

**Order / fill:** sort by **`(-size, lfn)`** (largest first). Each job is
seeded with the next remaining file; the packer then scans **all** remaining
files and adds every candidate that still fits under ``max``. That costs
``O(n^2)`` but fills closer to the ceiling and mixes large seeds with smaller
files that fit in the slack. Close the job only after that full scan (or when
the seed alone is oversize).

### Packing rule (fill toward max)

```text
require min_output_size_bytes <= max_output_size_bytes

remaining = sorted(files, key=(-size, lfn))
while remaining:
    seed = remaining.pop(0)
    if seed.size > max_output_size_bytes:
        emit job([seed])   # alone; oversize — see open note
        continue
    current, accum = [seed], seed.size
    for each candidate still in remaining (in order):
        if accum + candidate.size <= max_output_size_bytes:
            move candidate into current; accum += candidate.size
    emit job(current)      # may be < min if nothing else fit
```

Unlike next-fit (close when the immediate next file does not fit), this
rescans the whole remainder so a large seed can still pick up later small
files that fit in the slack. Multi-file jobs always satisfy
``accum <= max_output_size_bytes``. A lone oversize file is the intentional
exception to the ceiling.

Estimated output size for characterization is `accum` (sum of input sizes)
at emit time — merge is treated as roughly size-preserving for packing.

### Explicitly out of scope (v1)

| Upstream / idea | Decision |
| --- | --- |
| Location bucketing | **Omit** (pre-scoped input) |
| Run / lumi grouping for merge order | **Omit** for v1 (not in upstream code
  path; see [Future work: contiguous run/lumi order](#future-work-contiguous-runlumi-order)) |
| WMBS / subscription / UUID job names | **Omit** |
| Event masks on merge jobs | **Omit** unless a consumer requires a
  sentinel mask |
| Parents / ACDC | **Omit** |
| Single-threshold `merge_size` only | **Replace** with min/max band (above) |

### Resource estimates and `n_events`

Reminder (same model as in [resource-model.md](resource-model.md)): **transient** output lives
only on worker scratch; **persisted** output is written to scratch **and**
staged to shared storage. Estimated scratch is always
`transient + persisted` while the job runs.

Merge jobs are I/O-heavy. Proposed v1:

- **`network`**: sum of assigned input file sizes (read volume)
- **`n_events`**: sum of file-level `events` when present (characterization)
- **`transient_output_size_per_event`**: forced to **0** — merge has no
  scratch-only product; the merge output is persisted (shared storage). Callers
  may still pass a non-zero transient rate; it is ignored.
- **`persisted_output` / scratch / walltime**: from optional rates ×
  `n_events` when provided (otherwise zeros). Scratch therefore equals
  persisted for merge jobs (`0 + persisted`), not zero disk.

Do not pretend processing `time_per_event` applies unless the caller passes
merge-calibrated rates.

### Leftover files below min (v1 decision)

With a min/max band, mid-stream closes (next file does not fit under max)
should normally leave `accum >= min` after greedy fill. The hard case is the
**tail** of the request (or a gap before an oversized file): `accum < min`
and nothing else fits.

**v1: always flush** undersized remainders as a merge job. That matches
complete, pre-scoped file lists. A future `flush_remainder` flag or
never-flush contract can wait until streaming/incomplete filesets need it.

### Type / API sketch

```text
MergeBySizeRequest:
  files: tuple[SplitFile, ...]       # lfn + size required; events optional
  min_output_size_bytes: int          # > 0
  max_output_size_bytes: int          # >= min_output_size_bytes
  rates: ResourceRates = ResourceRates()  # optional; see estimates note
  budgets: ResourceBudgets = ResourceBudgets()

MergeBySizeSplitter(JobSplitter[MergeBySizeRequest])
```

Module: `merge_by_size.py` (implemented).

### Implementation status

v1 implemented: min/max validation, ``(-size, lfn)`` order with full-remainder
fill toward ``max`` (``O(n^2)``), always-flush emits, oversize singleton as a
normal one-file job, `n_events` + `network` via shared `make_job` /
`estimates_for`.

### Open note: oversize single file vs `unsplittable`

In processing splitters, `unsplittable` often means “do not submit / fail this
unit” (e.g. skip HTCondor). For **merge**, that is a poor fit: the expensive
processing step has already produced the large file, and refusing to merge it
only strands data.

**Provisional v1:** a file with `size > max_output_size_bytes` still becomes a
**normal** one-file merge job (ceiling applies to combining files, not to
rejecting an already-large input).

**Future work / decide later:**

- Whether to flag oversize merges somehow without blocking submission
  (warning field, baggage, metrics) for ops visibility
- Whether `max` should ever force-fail merge (probably not)
- How merge job resource estimates should reflect an oversize singleton

### Future work: contiguous run/lumi order

v1 packs by **file size** (sorted ``(-size, lfn)``, full-remainder fill toward
max). A useful variant would still use that band, but prefer packing files
whose `(run, lumi)` metadata form an **ascending, contiguous** pattern (better
merge locality for consumers that care about run/lumi order).

**TODO:**

- Require non-empty `run_lumis` on each input file (unlike size-only v1)
- Define ordering (e.g. by min `(run, lumi)` per file) and what “contiguous”
  means across file boundaries (adjacent lumis, same run, gaps allowed or not)
- Keep the min/max size band as the primary close rule; use run/lumi order as
  the walk / preference order, not a second independent quota — unless
  product requirements demand hard run boundaries inside a merge job
- Document interaction with LumiAwareFile-style shared lumis (likely still
  out of scope for merge, or co-located first)

### Future work: oversize inputs — ops visibility

v1 still merges a singleton oversize file. Future work may add non-blocking
signaling (metrics / baggage) so operators can see merges that exceeded the
configured max without failing the job in HTCondor.
