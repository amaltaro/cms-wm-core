# EventAwareLumi

Final processing: pack ``(run, lumi)`` work by event/walltime target.

Part of the [job-splitting design](README.md).

---

## Upstream: EventAwareLumiBased vs EventAwareLumiByWork

These are the WMCore algorithms for input file processing with lumi and event awareness: work is assigned as `(run, lumi)` units, while **events** mainly size jobs. Upstream sources:

- [EventAwareLumiBased.py](https://github.com/dmwm/WMCore/blob/master/src/python/WMCore/JobSplitting/EventAwareLumiBased.py)
  — heavily used in central production
- [EventAwareLumiByWork.py](https://github.com/dmwm/WMCore/blob/master/src/python/WMCore/JobSplitting/EventAwareLumiByWork.py)
  — improvements that were never really used in central production

Also summarized in the
[WMCore JobCreator wiki](https://github.com/dmwm/WMCore/wiki/JobCreator)
and
[JobSplitting Algorithms wiki](https://github.com/dmwm/WMCore/wiki/JobSplitting-Argorithms).

### Shared ideas

| Idea | Role |
| --- | --- |
| Atomic work unit | Whole luminosity sections (`(run, lumi)`); never split a lumi |
| Primary packing knob | `events_per_job` (often derived from TimePerEvent × desired wall time) |
| Resource estimates | `n_events × timePerEvent` / `sizePerEvent`; optional memory on jobs |
| Oversized single lumi | If one lumi’s estimated time exceeds `job_time_limit` (~48h), emit a
  create-failed / unsplittable job |
| Boundary flags | `halt_job_on_file_boundaries`, `splitOnRun` — **open
  question** for cms-wm-core (see below /
  [Future work](future-work.md) |
| Out-of-band concerns | Location buckets, ACDC / Couch whitelists, parents, deterministic
  pileup baggage, WMBS run–lumi DAO loads |

### EventAwareLumiBased (production workhorse)

**File-centric.** Iterate files (per location), then runs, then lumis inside
each file.

1. For each file, compute
   `avgEvtsPerLumi = round(file.events / file.lumiCount)`.
2. Convert the event target into a **lumi quota**:
   `lumisPerJob = max(floor(events_per_job / avgEvtsPerLumi), 1)`.
3. Walk contiguous good lumis; close a job when `lumisInJob == lumisPerJob`
   (or on run / file boundaries when those flags are set).
4. Job masks store **contiguous lumi ranges** per run
   (`[firstLumi, lastLumi]`); gaps or whitelist skips break the range.
5. When jobs may span files, remaining event room is recomputed and the
   lumi quota is updated at file boundaries.
6. Split lumis across files need an explicit **LumiChecker** /
   `applyLumiCorrection` path so the same `(run, lumi)` is not double-counted
   incorrectly.

**Strengths:** battle-tested; predictable “N lumis per job” behavior when
metadata only has file-level event totals.

**Weaknesses:** packing is driven by an **average**, so real job event
counts can drift when lumis are uneven; file-first iteration plus correction
logic is complex; continuous-range bookkeeping is easy to get wrong.

### EventAwareLumiByWork (unused improvements)

**Work-centric.** Treat `(run, lumi)` as the primary iterator; files are
looked up from a `filesByLumi` map.

1. Build `lumisByFile` and `eventsByLumi` (upstream still estimates per-lumi
   events as `round(file.events / lumisInFile)` when true per-lumi counts
   are unavailable).
2. For each unused `(run, lumi)`, decide whether it fits the **current** job
   by a **closest-to-target** rule: close the job before adding the lumi if
   `|eventsInJob + eventsInLumi − target| >= |eventsInJob − target|`
   (and both sides are non-empty / positive as coded).
3. Multi-file lumis are automatic: every file containing that lumi is added
   to the job; no separate LumiChecker.
4. Masks are built via `LumiList` compact ranges.
5. Same oversized-lumi failure path and optional run/file boundary stops.

**Strengths:** cleaner work model; natural handling of lumis split across
files; packing tracks the event target more tightly when per-lumi sizes vary.

**Weaknesses:** never validated at central-production scale; upstream still
often uses averaged per-lumi events; same location-bucketing caveat (identical
`(run, lumi)` at two sites can yield two jobs).

### Side-by-side

| Aspect | EventAwareLumiBased | EventAwareLumiByWork |
| --- | --- | --- |
| Iteration | File → run → lumi | Lumi (work) → files containing it |
| Sizing when events uneven | Fixed lumi quota from file average | Closest-to-`events_per_job` |
| Cross-file lumi | Explicit correction | `filesByLumi` map |
| Central production | Yes | Effectively no |
| Best fit for metadata | File totals only | True per-lumi event counts |

## EventAwareLumi (cms-wm-core design — draft)

Working name for the final-processing splitter in this library. Goal: keep
the production semantics of **EventAwareLumiBased**, adopt the work-centric
packing improvements of **EventAwareLumiByWork**, and fit the shared
resource / pre-scoped-input model used by FileBased and EventBased.

Implemented in ``event_aware_lumi.py`` (v1). This section remains the design
baseline; open questions (run/file boundaries, allow-list) are unchanged.

### Problem statement

Always **real input files**. Each file carries a non-empty `run_lumis` list of
`(run, lumi, events)` where `events` may be `int` or `None`:

- **Legacy:** all per-lumi `events` are `None` → size using an **average
  events per lumi** (`round(file.events / n_lumis)`) for packing and
  `n_events`
- **Modern (~2018+):** all per-lumi `events` are ints → pack using **those**
  counts and a closest-to-target rule (no averaging)

Mixed known/legacy counts **within one file** are rejected. A request may
still combine fully-legacy and fully-known files.

**v1 scope of work per file:** process **all** `(run, lumi)` entries present on
each input file. There is no run/lumi allow-list yet; subsetting a file is
[future work](#future-work-runlumi-allow-list).

Jobs must list input LFNs plus a **run/lumi mask** of whole lumis assigned to
that job. Execution consumes LFNs + mask; it does **not** need a separate
event total. Still, each job should record **`n_events`**: the total events
assigned to that job (exact sum of per-lumi counts when known, otherwise the
same average-based estimate used for packing). That figure characterizes the
job and is the natural input to resource estimates (`n_events × rates`).

Resource estimates therefore follow from the recorded event total, not from
re-deriving it later from masks unless a caller chooses to.

### What drives splitting

Align with EventBased for the soft packing goal:

```text
events_per_job = floor(target_job_walltime / time_per_event)
```

Require `time_per_event > 0`, `target_job_walltime > 0`, and
`events_per_job >= 1`. Optional hard `max_job_walltime` / `max_job_disk`
follow the shared budget model (unsplittable when a single lumi cannot fit).

Events are a **sizing** signal; the **assigned work** is always a set of
`(run, lumi)` pairs (and the files that contain them).

### Packing modes

Use one work-centric loop (ByWork style). Resolve each lumi’s event weight
before the close/keep decision:

| Per-lumi `events` | Weight used for packing |
| --- | --- |
| all `int` in the file | Those integers (no averaging) |
| all `None` in the file | File-level average:
  `round(file.events / n_lumis_in_file)` for every lumi |

Then apply the **closest-to-`events_per_job`** close rule (ByWork). When every
lumi in a file uses the same average weight, this is approximately the old
“convert target → `lumisPerJob`” behavior, without a separate code path.

**Policy per file:** event metadata must be uniform — either every lumi has an
`int` count or every lumi is `None`. Mixing both in one file is rejected
(not expected in production). Different files in one request may differ
(some fully known, some fully legacy).

**Empty / zero-event files:** define explicitly in implementation (skip vs
pack all remaining lumis); mirror upstream’s “zero events → treat as
unlimited / take remaining lumis” only where tests justify it.

### Cross-file `(run, lumi)`

**Invariant:** outside the special LumiAwareFile workflow, each
`(run, lumi)` lives in **exactly one** file. EventAwareLumi work units are
therefore `(run, lumi)` **on a single file**. If the same key appears in more
than one input file, EventAwareLumi raises; the caller must use
**LumiAwareFile** for that workflow (the only algorithm that co-locates
shared lumis under file-count packing).

### Job output shape (gap vs current types)

`SplitJob` today is oriented at FileBased / EventBased (LFNs and MC event
ranges). EventAwareLumi also needs a compact **mask**, for example:

- `run_lumi_mask: tuple[RunLumiRange, ...]` with contiguous
  `(run, first_lumi, last_lumi)` ranges, or
- an explicit list of `(run, lumi)` (worse for tens of thousands of lumis)

Prefer compact ranges. Do **not** copy full per-lumi event tables onto each
job.

**Assigned / estimated event total:** set `SplitJob.n_events` to the sum of
lumi weights actually packed into the job (true counts and/or averages).
Reuse the existing field: for EventBased it is the generated event range
length; for EventAwareLumi it is the processing event total (not a mask for
the worker). Callers use it to characterize jobs and to relate
`ResourceEstimates` back to work size without reconstructing the mask.

Mark oversized single-lumi jobs with `unsplittable=True` and a clear reason
(replacing upstream create-failed / ACDC upload).

### Explicitly out of scope (v1)

| Upstream / idea | Decision |
| --- | --- |
| Location bucketing | **Omit** (pre-scoped input) |
| ACDC / Couch clients and whitelist fetch | **Omit** (no service clients in
  the core library) |
| Run/lumi allow-list (process a subset of a
  file) | **Omit for v1** — pack every lumi on the input files; see
  [Future work: run/lumi allow-list](#future-work-runlumi-allow-list) |
| WMBS DAO run–lumi load | **Omit**; `run_lumis` must already be on
  `SplitFile` |
| `include_parents` | **Omit** for now |
| Deterministic pileup `skipPileupEvents` baggage | **Omit** for now |
| Memory on jobs | **Omit** |
| `job_limit` hard stop mid-split | Defer unless a caller needs it |
| Pure LumiBased (`lumis_per_job` only) | Separate algorithm if still needed |

### Open question: run / file boundary flags

Upstream exposes two packing stops beyond the event target:

| Flag | Effect when true |
| --- | --- |
| `splitOnRun` | Close the job before a lumi from a **new run** |
| `halt_job_on_file_boundaries` | Close the job before a lumi from a **new file** |

They still show up in production knobs, but it is unclear whether they remain
the right model for DiracX-era splitting (pre-scoped inputs, work-centric
packing, event/walltime targets).

**Decide before locking the v1 API:**

1. **Still relevant?** Do any remaining workflows *require* “one run per job”
   or “one file per job” as hard packing rules, or is event/walltime targeting
   enough?
2. **Fixed default behavior?** If boundaries matter, pick one fixed policy
   for v1 (e.g. never mix runs; allow multi-file jobs) and document it —
   without request fields.
3. **Configurable hooks?** Only add `split_on_run` /
   `halt_on_file_boundaries` (or equivalents) on the request if real callers
   need both modes. Prefer not to carry unused WMCore flags “just in case.”

Until decided: do **not** treat these as required request fields. Record the
chosen default (or deferred configurability) in the module docstring when
implementing.

### Type / API sketch

```text
RunLumiEvents.events: int | None   # extend current int-only field

EventAwareLumiRequest:
  files: tuple[SplitFile, ...]     # each with non-empty run_lumis
  rates: ResourceRates             # time_per_event required
  budgets: ResourceBudgets         # target_job_walltime required
  # boundary flags: TBD — see open question above
  # run/lumi allow-list: Future work (v1 = full files)

EventAwareLumi(JobSplitter[EventAwareLumiRequest])
```

Module: `event_aware_lumi.py`.

**v1 packing defaults (pending open question):** no run/file boundary stops;
jobs may span runs and files. Only the event-target close rule applies.

### Determinism and WM memory

- Stable sort of files (LFN) and of work units before packing
- Same inputs → same job sequence, masks, and estimates
- Avoid duplicating full `run_lumis` tables on every job; prefer masks
- Large workflows still subject to the streaming / chunked `SplitResult`
  direction in “Scale and process memory”

### Implementation order (when we start coding)

1. Extend `RunLumiEvents` / docs for optional per-lumi `events`
2. Add compact mask representation on `SplitJob` (or a nested type);
   set `n_events` to the assigned/estimated event total on every job
3. Implement work-centric packer + average fallback + unsplittable path
4. Unit tests: all-`None` (average), all-`int` (closest), reject mixed
   metadata, reject shared multi-file lumi, oversized single lumi,
   determinism, and that `n_events` matches the packed lumi weights
   (plus run/file boundary cases once that open question is settled)

### Future work: run / file boundary policy

Resolve the open question above (are `splitOnRun` /
`halt_job_on_file_boundaries` still needed?). Outcomes to record once decided:

- **Drop** — pack only by event/walltime target; document that jobs may span
  runs and/or files
- **Fixed default** — one hard-coded policy in the algorithm (no request
  knobs); document the invariant
- **Configurable** — add explicit request flags only if callers need both
  modes; keep names/semantics clear and tested

Do not implement configurable hooks until that decision is made.

### Future work: run/lumi allow-list

v1 treats each file’s `run_lumis` as the full work set: every lumi on the
file is eligible for packing.

**TODO:** Allow the caller to restrict processing to a subset of
`(run, lumi)` pairs (an allow-list / mask passed as **data**, not fetched from
ACDC/Couch). Use cases include recovery, partial blocks, and skims over only
selected lumis. Expected shape:

- Request carries an optional set (or compact list) of allowed `(run, lumi)`
- Only matching lumis from the input files are packed; others are skipped
- Jobs still emit LFNs + masks for the **selected** work only
- Keep discovery/persistence of that list outside the core algorithm
