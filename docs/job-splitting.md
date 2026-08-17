# Job splitting design

Design notes for extracting CMS workload-management job splitting into
`cms-wm-core`, with a path toward reuse in DiracX.

Upstream reference:
[WMCore JobSplitting](https://github.com/dmwm/WMCore/tree/master/src/python/WMCore/JobSplitting).

Code will live under `src/cms_wm_core/job_splitting/`.

## Scope

In scope: **agent-style job splitting** — given an already resolved set of
files and split parameters, produce jobs (input files + masks + estimates).

Out of scope for the core algorithms:

- Data discovery (DBS, Rucio, CRIC)
- WorkQueue-style start policies (dataset/block → work elements)
- Persistence (WMBS commit, Couch/ACDC clients)
- T0 Express/Repack DAO-driven splitters (later, as adapters)
- Memory sizing / memory-based packing (see below)

## CMS / Rucio data hierarchy

| Rucio concept | Typical CMS meaning | Role |
| --- | --- | --- |
| Container | Full dataset | Discovery / placement scope |
| Dataset | Block (subset of the container) | Usual placement and distribution unit |
| File / replica | Single file | Unit consumed by job(s) |

Data placement is normally performed at **container** or **dataset (block)**
level, but file-level placement will be added in the future system.

### File metadata: run / lumi / events

Below the file, CMS data is further described by luminosity sections. For
job splitting, each file may carry a list of triples:

| Field | Meaning |
| --- | --- |
| Run number | CMS run |
| Luminosity section number | Lumi within that run |
| Event count | Events in that run/lumi for this file (`int`, or `None` for legacy) |

Not every algorithm needs this map (e.g. pure FileBased may only use file
totals). Lumi- and event-aware algorithms do.

**Legacy vs modern event counts:** older CMS file metadata often omits a
per-lumi event count (`None`). Newer files (roughly post-2018) typically
carry an integer per `(run, lumi)`. Event-aware packing must support both
(see EventAwareLumi below).

**Scale warning:** a single file can have on the order of **tens of
thousands** of lumis. The run/lumi table is therefore a demanding structure
and a major contributor to **workload-management** process memory. Design
implications:

- Keep the representation compact (e.g. small immutable records / tuples)
- Do not duplicate the full map per job when a mask / index range suffices
- Load or pass run/lumi data only when the chosen algorithm requires it
- Prefer streaming or views over deep copies when adapting from WMBS/DBS

In code, this is modeled as `RunLumiEvents` on `SplitFile.run_lumis`
(`types.py`).

## Scale and process memory

Two different “memory” topics appear in this design; do not confuse them:

| Topic | Where it runs | Meaning | In splitter scope? |
| --- | --- | --- | --- |
| Grid-job application memory | **Worker node** executing one job | RSS as the payload processes its assigned data | **No** (not a packing budget) |
| Workload-management memory | **WM service** turning workflows into jobs | RAM while ingesting high-level requests and emitting many jobs | **Yes** (stability constraint) |

The scale risk called out here is **not** about worker nodes. It is about the
workload management component (agent, orchestrator, DiracX service, …) that
accepts workflow-level requests and breaks them into processing units (grid
jobs). Large workflows can generate **tens of thousands of jobs** in one
logical split; if that component holds full run/lumi maps and the entire job
list in memory, it can become unstable.

A robust memory strategy is therefore required **on the WM side**: peak
memory should stay bounded (or grow only weakly), not scale linearly with
workflow size or total jobs produced.

Direction of travel (API may evolve; early code may still materialize results
for clarity):

1. **Bounded inputs** — pre-scoped units; avoid loading unused run/lumi maps
2. **Compact structures** — prefer tuples/arrays over heavy objects; share
   file metadata by reference where safe
3. **Streaming / chunked output** — emit jobs via iterator or fixed-size
   batches so WM peak memory does not track total job count
4. **Drain as you go** — persist or enqueue each chunk (WMBS, DiracX, …)
   instead of accumulating the full result in the splitter process

Determinism still applies under streaming: for the same input, the sequence
of emitted jobs must be identical.

Current `SplitResult` is an in-memory snapshot suitable for unit tests and
small runs; treat it as provisional for large production workflows.

## Core invariant: pre-scoped input

**Job splitting assumes its input file list is already a locality- and
placement-consistent unit.** Cross-dataset / cross-block packing and data
discovery are **caller** responsibilities.

### Why not encode Rucio dataset preference inside the algorithm?

An alternative is to require a Rucio dataset name on every file and have the
splitter prefer (or force) packing within the same dataset, with a hook to
enable/disable that behavior.

That approach is rejected for the core library because it:

- Mixes **placement policy** with **packing math**
- Couples the API to CMS/Rucio naming forever
- Makes behavior depend on how mixed the caller's file list is
- Complicates testing and reuse outside CMS (e.g. DiracX)

### Preferred pattern

1. Upper layer (orchestrator, WorkQueue-like policy, or adapter) selects a
   coherent unit — typically one Rucio dataset / block, already placed.
2. That layer invokes the splitter **once per unit** with that file list.
3. The splitter only applies packing rules (by files, events, lumis, …).

If a caller ever needs “pack within groups, never across” over a mixed list,
prefer **multiple invocations** (one per group) over an in-algorithm
enable/disable hook. An opaque optional `group_key` on files remains a
possible future extension; it is not required for the first extract.

Location metadata on files (whether replicas are local or remote) may still
inform **estimates** (e.g. network) within a pre-scoped unit. That is file
metadata, not Rucio hierarchy policy.

## Determinism

**Job splitting must be deterministic:** the same inputs always produce the
same jobs (same grouping, file order within jobs, masks, and estimates).

Practical rules:

- Do not rely on `set` iteration order or unordered dict key order for packing
- Apply a stable sort before packing (e.g. by LFN, then by run/lumi if needed)
- Tie-breakers must be explicit and documented per algorithm
- Characterization tests should freeze expected job boundaries for fixtures

Determinism is required for reproducible debugging, safe retries, and fair
comparison across refactors.

## Separation of concerns

| Concern | Owner |
| --- | --- |
| Discover containers/datasets/files | Caller / data-management adapters |
| Choose placement and work granularity | Caller / scheduling layer |
| Load run–lumi maps, parentage, ACDC whitelists | Caller (pass **data**, not clients) |
| Pack files into jobs using packing rules and resource budgets | **Job splitting algorithms** |
| Persist jobs, apply generators, map sites | Caller / WMAgent-style adapters |
| WM process memory under large workflows | WM component + splitter API (streaming/chunking) |
| Worker-node application RSS | Outside splitting (payload / runtime) |

### Worker application memory is out of scope for packing

Worker-node **application memory** (RSS of the grid job) is **not** part of
the job-splitting budget. Ideally, an application’s footprint does not grow
with the amount of data assigned to one job; packing more events/files should
not be gated on RSS.

That is separate from **workload-management process memory**, which *is* a
stability concern when workflows expand into very large run/lumi maps and job
counts (see Scale and process memory above).

Upstream WMCore attaches `memoryRequirement` / `estimatedMemory` to jobs for
matchmaking. In this library, that stays with the caller or submitter adapter
if needed — not as a splitter rate, target, or close condition.

## When to close job A and open job B

Splitters need more than the file list: they need **budgets** that decide when
the current job is full and the next job should start. Those budgets come from
the caller (workload / site / pilot policy), not from discovery services.

### Packing targets (primary close conditions)

Algorithm-specific targets remain the usual close triggers, for example:

- `files_per_job` (FileBased)
- `events_per_job` (EventBased, EventAware*)
- `lumis_per_job` (LumiBased)
- optional boundary rules (halt on file/run boundaries, fileset closed, …)

### Resource model (rates, targets, and maxima)

CMS jobs must fit the **execution envelope** of the worker (historically
GlideinWMS pilot jobs). For wall time and disk, the splitter uses three
layers of information:

1. **Rates** — how cost scales with work (see size decomposition below)
2. **Targets** — preferred job size; close when the estimate reaches the
   target (soft packing goal)
3. **Maxima** — hard ceiling; never emit a job estimated above the max;
   flag work that cannot fit even alone

| Concern | Estimate (sketch) | Target (soft) | Maximum (hard) |
| --- | --- | --- | --- |
| Wall-clock time | `n_events × time_per_event` | `target_job_walltime` | `max_job_walltime` |
| Scratch disk | see disk components below | `target_job_disk` | `max_job_disk` |

Invariant: `target_* ≤ max_*` when both are set.

Upstream WMCore uses a single `sizePerEvent` and a time cap (`job_time_limit`).
This design replaces that with explicit **targets vs maxima** and a richer
size model.

### Size per event — decomposed metrics

A single `size_per_event` is too coarse. Prefer three rates:

| Rate | Meaning | Typical use |
| --- | --- | --- |
| `input_size_per_event` | Average input bytes per event | Network estimate (remote read); may inform local staging needs |
| `transient_output_size_per_event` | Intermediate output on worker scratch | Part of scratch-disk estimate |
| `persisted_output_size_per_event` | Output that must be **staged out** after processing | Stage-out volume; also counted in scratch while the job runs |

**Scratch disk estimate** (normative intent):

```text
estimated_scratch ≈ n_events × (transient_output_size_per_event + persisted_output_size_per_event)
estimated_persisted ≈ n_events × persisted_output_size_per_event
```

During the job, both transient and persisted products occupy the worker
scratch area. After processing, a post-process step stages persisted data to
shared storage; when the job container finishes, all scratch used by that job
is released.

Whether a local copy of input also counts against scratch is **TBD** per
runtime model; if it does, document it as an additive term, not by collapsing
metrics back into one `size_per_event`.

**`input_size_per_event` source — TBD:**

- **Derived**: `file.size / file.events` (per file or averaged over the unit),
  or
- **Caller-provided**: campaign / workflow performance parameter

The implementation should pick one default and allow override; characterization
tests must state which mode a fixture uses.

### Network estimate

When a job may read input **remotely**, expose a network metric derived from
input size, e.g.:

```text
estimated_network ≈ n_events × input_size_per_event
```

or, equivalently, the sum of assigned input file sizes when reading whole
files. Locality (all replicas local vs remote) is caller/file metadata; the
splitter only computes the estimate when remote read is indicated or assumed.

Network is an **output estimate** for planning and monitoring. Whether it
also acts as a packing close condition is optional and algorithm-specific;
wall time and scratch remain the primary resource close drivers.

### Who supplies what (common resource inputs)

| Input | Meaning | Owner |
| --- | --- | --- |
| `time_per_event` | Average processing time per event | Caller (task / campaign performance) |
| `input_size_per_event` | Average input bytes per event | Caller and/or derived from file size/events |
| `transient_output_size_per_event` | Intermediate scratch bytes per event | Caller |
| `persisted_output_size_per_event` | Stage-out bytes per event (also on scratch while running) | Caller |
| `persisted_output_size_per_event` | Stage-out bytes per event | Caller |
| `target_job_walltime` | Preferred estimated wall time per job | Caller (ops / campaign policy) |
| `max_job_walltime` | Hard wall-time ceiling (e.g. pilot max) | Caller (pilot / site policy) |
| `target_job_disk` | Preferred estimated scratch per job | Caller |
| `max_job_disk` | Hard local-disk (scratch) ceiling | Caller (site / slot policy) |
| `n_events` (per candidate job) | From assigned files / masks | Derived inside the algorithm |

### Decision rules (normative intent)

While accumulating work into the current job:

1. Recompute estimates (time, scratch, stage-out volume, network as applicable)
   from assigned events and the rates above.
2. **Prefer closing** the job when a configured **target** is reached
   (`target_job_walltime` and/or `target_job_disk`), subject to algorithm
   packing rules (files/events/lumis, boundary flags).
3. **Never** create a job whose wall-time or scratch estimate exceeds a
   configured **maximum**.
4. If a single indivisible unit (e.g. one file, or one lumi that cannot be
   split further) exceeds `max_job_walltime` or `max_job_disk`, **flag** it
   (unsplittable / failed-on-creation) rather than emitting an oversize job.

Count-based packing knobs (`files_per_job`, `events_per_job`, …) remain
valid; resource targets/maxima either complement them or, for event-aware
algorithms, become the primary close condition. Interaction rules will be
fixed per algorithm when implemented.

Exact units (seconds; bytes vs MB/GB) will be fixed in the typed API.

Resource rates, targets, and maxima are **inputs** (or derived from file
metadata for input size). Calibration of processing and output rates stays
outside the splitter.

## Code sketch (interface)

Under `src/cms_wm_core/job_splitting/`:

| Module | Role |
| --- | --- |
| `types.py` | Dataclasses only: files, run/lumi triples, rates, budgets, jobs, results |
| `base.py` | `JobSplitter` ABC — subclasses must implement `name` and `split` |
| `file_based.py` | FileBased v1 + `FileBasedRequest` |
| `file_lumi_aware.py` | FileBased + keep shared `(run, lumi)` in one job |
| `event_based.py` | MC EventBased + `EventBasedRequest` |
| `file_common.py` | Shared estimate / validation helpers |
| `event_aware_lumi.py` | Final processing EventAwareLumi + `EventAwareLumiRequest` |
| `merge_by_size.py` | Merge packing by min/max output size + `MergeBySizeRequest` |
| further algorithms | Own `*Request` dataclass + `JobSplitter[ThatRequest]` |

`typing.Protocol` / duck typing is intentionally avoided so each field has an
explicit dataclass type.

## Input / output contract (sketch)

**Each algorithm may require a different subset of inputs.** Shared types in
`types.py` are a vocabulary; each algorithm adds a request dataclass.
Callers must not assume FileBased and EventAwareLumiBased consume the same
request.

### Input — file (common fields; algorithms vary)

Typical fields (not all required for every algorithm):

- `lfn`, `events`, `size`, `first_event`
- `locations` / locality hints (optional; network vs local read)
- `run_lumis`: list of `(run, lumi, events)` — can be very large; omit when
  unused
- optional `parents` (LFNs already attached)

No required Rucio container/dataset fields on the core input.

### Input — request (common fields; algorithms vary)

- Algorithm identity (e.g. file-based, event-based)
- Packing targets relevant to that algorithm (`files_per_job`,
  `events_per_job`, `lumis_per_job`, …)
- Boundary flags, lumi mask, `fileset_closed`, … as needed by that algorithm
- **Performance rates**: `time_per_event`, `input_size_per_event` (or derive),
  `transient_output_size_per_event`, `persisted_output_size_per_event`
- **Resource targets** (soft close): `target_job_walltime`, `target_job_disk`
- **Resource maxima** (hard ceiling / unsplittable flag):
  `max_job_walltime`, `max_job_disk`
- Precomputed whitelists/masks as data only (no URLs or DB handles)

### Output

- Ordered jobs (deterministic for the given inputs); stored as an immutable
  tuple on ``SplitResult.jobs``
- Each job: ordered input LFNs, mask (when applicable), **resource estimates**:
  - wall time
  - scratch disk (transient + persisted; ± TBD input staging)
  - persisted / stage-out volume (subset of scratch)
  - network (from input file sizes when remote read applies)
- optional creation-failure / unsplittable marker and reason
- small baggage dict if needed

No memory estimate from the splitter.

## FileBased (v1 scope)

Upstream:
[WMCore FileBased](https://github.com/dmwm/WMCore/blob/master/src/python/WMCore/JobSplitting/FileBased.py).

FileBased packs whole files into jobs. It is the first algorithm to extract.

### What drives splitting

- **`files_per_job`** — soft/primary packing target: close the current job and
  start a new one when this many files have been assigned
- **Per-file `events`** — required on each input file so resource estimates
  can be computed (`n_events × rates`)
- Optional **resource targets/maxima** and size/time rates — same shared
  budget model as the rest of this design (estimates always; hard closes /
  unsplittable flags as we wire them in)

### Explicitly out of scope for FileBased

| Upstream / idea | Decision |
| --- | --- |
| Location bucketing (`sortByLocation`) | **Omit.** Caller must pass a file list that is already location-consistent. Site/locality belongs closer to **job execution** than to job definition in WM. |
| Run / lumi masks and run boundaries | **Omit.** If run/lumi constraints matter, use a lumi-aware algorithm — not FileBased. |
| `jobs_per_group` | **Omit.** Packaging/scalability concern for persistence, not packing math. |
| `include_parents` / parent LFN resolution | **Omit for now.** Document as deferred in the module docstring (needed historically when processing files with parents). |
| Memory requirement on jobs | **Omit** (not a packing input; see above). |

### Input / output (FileBased-specific)

**Input files:** required `lfn`, `events`, and `size` (size feeds the network
estimate). `run_lumis` and `locations` are ignored if present.

**Input request:** `files_per_job`, file tuple, `ResourceRates`, optional
`ResourceBudgets`.

**Output:** ordered ``SplitResult.jobs`` (LFN-sorted packing). Each job sets
``n_events`` to the sum of assigned file-level ``events`` (same total used for
resource estimates). Deterministic for the same input.

## FileLumiAware

Variant of FileBased that is **run+lumi aware**.

### Extra constraint

Each file must carry a non-empty ``run_lumis`` list of ``(run, lumi[, events])``
entries. Files that share any ``(run, lumi)`` — including **transitively**
through other files — form one atomic component and are always assigned to the
**same job**.

This algorithm is the **only** place that supports a run+lumi scattered across
multiple files. All other algorithms (including EventAwareLumi) and downstream
steps require each run+lumi to live in a single file.

### Packing

Same as FileBased otherwise:

- ``files_per_job`` packs whole **components** (never splits a component)
- A component larger than ``files_per_job`` still becomes one job
- Resource rates / targets / maxima apply to the files in the job
- Estimates use file-level ``events`` and ``size``; jobs set ``n_events`` to
  that event sum
- Deterministic: components ordered by minimum LFN; LFNs sorted within a job

## EventBased (v1 scope)

Upstream:
[WMCore EventBased](https://github.com/dmwm/WMCore/blob/master/src/python/WMCore/JobSplitting/EventBased.py).

### CMS usage (rule of thumb)

EventBased is the usual splitter for workflows **without real input data**
(Monte Carlo generation). The user asks for a total number of events to
produce; the WMS assigns **disjoint event ranges** and **unique luminosity
sections** to jobs.

Upstream used a `MCFakeFile` placeholder (not a real file) so work could be
carried with start/end events and lumis. v1 does **not** invent fake LFNs;
jobs expose event/lumi fields directly on `SplitJob`.

### Distributing across WMS instances

Callers (or a higher-level allocator) choose a slice of the global MC
namespace by passing:

- `first_event` — start of this slice’s event range
- `first_lumi` — first luminosity section id for this slice
- `total_events` — how many events this slice must generate

Each job gets one **unique** integer lumi, incremented from `first_lumi`.
Event ranges are half-open: `[first_event, first_event + n_events)`.

Defaults: `first_event = 1`, `first_lumi = 1`.

### Packing size

`events_per_job` is **not** a free input. It is computed as a positive
integer:

```text
events_per_job = floor(target_job_walltime / time_per_event)
```

Require `time_per_event > 0`, `target_job_walltime > 0`, and
`events_per_job >= 1`.

### What WMCore EventBased also does (out of scope for v1)

| Upstream feature | Decision |
| --- | --- |
| Real input files split by events inside each file | **Omit** for v1;
  revisit if MC lumis grow too large (see Future work) |
| Emitting `MCFakeFile` LFNs | **Omit** (use job event/lumi fields) |
| ACDC recovery path | **Omit** |
| `include_parents`, location bucketing | **Omit** |
| Deterministic pileup baggage | **Omit** |
| Memory requirement on jobs | **Omit** |

### v1 inputs

| Input | Role |
| --- | --- |
| `total_events` | Events to generate in this request/slice |
| `target_job_walltime` | Soft packing goal; drives `events_per_job` |
| `ResourceRates.time_per_event` | Required; used with walltime to size jobs |
| Output size rates | Scratch / stage-out estimates |
| `first_event` | Event-range start (default `1`) |
| `first_lumi` | First job lumi id (default `1`) |
| `ResourceBudgets` maxima | Optional hard caps / unsplittable |

No `SplitFile` list. Network estimate is **0**.

### v1 output

Each job carries:

- empty `input_lfns`
- `first_event` + `n_events` (half-open range)
- `lumi` (unique integer for that job)
- `ResourceEstimates` for `n_events`

Deterministic: increasing events and lumis with no gaps/overlaps in the slice.

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
  question** for cms-wm-core (see below / Future work) |
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
Future work.

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

**Invariant:** outside the special FileLumiAware workflow, each
`(run, lumi)` lives in **exactly one** file. EventAwareLumi work units are
therefore `(run, lumi)` **on a single file**. If the same key appears in more
than one input file, EventAwareLumi raises; the caller must use
**FileLumiAware** for that workflow (the only algorithm that co-locates
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
  file) | **Omit for v1** — pack every lumi on the input files; see Future work |
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
chosen default (or deferred configurability) under Future work / in the
module docstring when implementing.

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

## MergeBySize (cms-wm-core design — draft)

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
  path; see Future work for a contiguous run/lumi variant) |
| WMBS / subscription / UUID job names | **Omit** |
| Event masks on merge jobs | **Omit** unless a consumer requires a
  sentinel mask |
| Parents / ACDC | **Omit** |
| Single-threshold `merge_size` only | **Replace** with min/max band (above) |

### Resource estimates and `n_events`

Reminder (same model as elsewhere in this doc): **transient** output lives
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

## Planned extract order

1. **FileBased** — v1 scope above
2. **FileLumiAware** — FileBased + co-locate shared `(run, lumi)`
3. **EventBased** — MC / no-input disjoint event ranges (v1 above)
4. **EventAwareLumi** — final processing; design draft above
5. **MergeBySize** — merge packing by min/max output size (design draft above)
6. **LumiBased** (optional) — fixed `lumis_per_job` if still needed apart from
   EventAwareLumi

Defer: other merge/sibling/Harvest splitters, WorkQueue start policies,
T0-specific algorithms, FileBased parentage and `jobs_per_group`, EventBased
real-file and ACDC paths, EventAwareLumi parents / pileup baggage / ACDC
clients / run-lumi allow-list.

## Provenance

When porting, record upstream path and intent of changes in the module
docstring or PR (see `AGENTS.md`). Prefer behavior-preserving extraction,
then refactor behind the contracts above.

## Future work / TODO

### Run / file boundary policy for EventAwareLumi

Resolve the open question under EventAwareLumi (are `splitOnRun` /
`halt_job_on_file_boundaries` still needed?). Outcomes to record here once
decided:

- **Drop** — pack only by event/walltime target; document that jobs may span
  runs and/or files
- **Fixed default** — one hard-coded policy in the algorithm (no request
  knobs); document the invariant
- **Configurable** — add explicit request flags only if callers need both
  modes; keep names/semantics clear and tested

Do not implement configurable hooks until that decision is made.

### MergeBySize with contiguous run/lumi order

v1 MergeBySize packs by **file size** (sorted ``(-size, lfn)``, full-remainder
fill toward max). A useful variant would still use that band, but prefer
packing files whose `(run, lumi)` metadata form an **ascending, contiguous**
pattern (better merge locality for consumers that care about run/lumi order).

**TODO:**

- Require non-empty `run_lumis` on each input file (unlike size-only v1)
- Define ordering (e.g. by min `(run, lumi)` per file) and what “contiguous”
  means across file boundaries (adjacent lumis, same run, gaps allowed or not)
- Keep the min/max size band as the primary close rule; use run/lumi order as
  the walk / preference order, not a second independent quota — unless
  product requirements demand hard run boundaries inside a merge job
- Document interaction with FileLumiAware-style shared lumis (likely still
  out of scope for merge, or co-located first)

### Oversize merge inputs (above max) — ops visibility

See MergeBySize open note: v1 still merges a singleton oversize file. Future
work may add non-blocking signaling (metrics / baggage) so operators can see
merges that exceeded the configured max without failing the job in HTCondor.

### Run/lumi allow-list (subset of a file)

v1 EventAwareLumi treats each file’s `run_lumis` as the full work set: every
lumi on the file is eligible for packing.

**TODO:** Allow the caller to restrict processing to a subset of
`(run, lumi)` pairs (an allow-list / mask passed as **data**, not fetched from
ACDC/Couch). Use cases include recovery, partial blocks, and skims over only
selected lumis. Expected shape:

- Request carries an optional set (or compact list) of allowed `(run, lumi)`
- Only matching lumis from the input files are packed; others are skipped
- Jobs still emit LFNs + masks for the **selected** work only
- Keep discovery/persistence of that list outside the core algorithm

### EventBased on large MC lumis / input datasets

v1 EventBased is **no-input MC**: one unique lumi per job and a disjoint
event range. That breaks down if a single MC luminosity section grows so
large that one job cannot process all of its events in a reasonable
walltime (or within infrastructure maxima).

**TODO:** Reconsider extending EventBased (or a sibling algorithm) to work
**with an input dataset** — splitting work inside an oversized lumi across
multiple jobs (event ranges within that lumi), so packing stays within
target/max walltime.

**Open design questions** (especially if a later **merge** step must
reassemble products):

- Does the application/framework support event range or event offset?
- Must event ranges assigned within one lumi be **contiguous** (and how are
  gaps / failures represented)?
- Must jobs that share a parent lumi emit masks or baggage that a merger can
  consume without reordering surprises?
- Do merge constraints require **contiguous lumis** as well as contiguous
  events, or is per-lumi event-range merging enough?
- How do unsplittable / partial failures interact with merge completeness?

Record chosen invariants in the EventBased (or successor) module docstring
when this is implemented. Until then, v1 keeps one lumi per job and assumes
that lumi fits a single job’s resource budget.

### Pileup in resource estimates (especially network)

CMS jobs often read **pileup** datasets in addition to primary input (or, for
MC EventBased, in addition to generating events with no primary input files).
Pileup can dominate remote I/O.

Today `ResourceEstimates.network` is:

- FileBased / FileLumiAware: sum of primary input file sizes
- EventBased: `0` (no primary input)

**TODO:** Factor pileup into job resource estimates so matchmaking /
provisioning see realistic network (and related) demand. At minimum:

- Model pileup contribution to **`network`** (bytes expected to be read,
  typically remotely)
- Decide whether pileup also affects scratch, walltime, or other estimates
- Keep pileup discovery/config outside the core splitter; pass resolved
  rates or byte estimates on the request (same separation-of-concerns rule
  as other performance inputs)
- Ensure EventBased MC jobs can report non-zero network when pileup is used

Without this, the WMS under-characterizes network activity and the underlying
resource provisioning / matchmaking stack lacks information needed for sound
resource-vs-job matching.

### HEPScore-normalized work and Dirac / DiracX alignment

Wall-clock estimates today use a raw `time_per_event` rate. That rate depends
on the **worker capability**. Benchmarks such as **HEPScore23** (CPU) and
**HEPScore4GPU** provide a common scale across heterogeneous sites.

DIRAC (and the DiracX direction) uses HEPScore mainly as a **normalization
metric for CPU power**, feeding matching, accounting, and workload sizing in
the Transformation Framework. In outline (to be validated against current
DIRAC / DiracX docs and code):

- **Normalized work** — express effort as HEPScore×seconds (or
  HEPScore·s per event / per MB), not uncalibrated wall seconds alone.
  HEPScore23 is the WLCG successor path away from legacy HS06 / DB12.
- **Pilot / site calibration** — WN power comes from site-advertised values
  (env, CE/GLUE2) or a quick local benchmark scaled to HEPScore equivalents.
- **Matching** — compare a job’s required **normalized** time to queue /
  pilot limits so work fits before expiration.

**TODO:** Align these splitters with that model once confirmed correct for
DiracX, for example:

- Quote packing rates as **normalized cost per event**
  (HEPScore·s/event), plus a **reference HEPScore** (and later GPU score)
- Size jobs with a formula in the spirit of:

  ```text
  events_per_job ≈
    (target_walltime × reference_HEPScore × N_cores × ε)
    / (normalized_cost_per_event)
  ```

  where `ε ≤ 1` is multi-core scaling efficiency (I/O / memory bandwidth
  often prevent linear speedup)
- Apply a **safety margin** on max walltime (DIRAC practice often cites
  ~15–20%) for I/O stalls and host load vs peak advertised score
- Keep site score discovery outside the core algorithm; pass normalized
  rates / reference score / `ε` on the request so estimates stay portable

Until then, walltime targets and maxima assume an implicit machine class and
will mis-size jobs on faster or slower workers—and will not match DIRAC’s
normalized matching units.
