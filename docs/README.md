# Job splitting

Design notes for extracting CMS workload-management job splitting into
`cms-wm-core`, with a path toward reuse in DiracX.

Upstream reference:
[WMCore JobSplitting](https://github.com/dmwm/WMCore/tree/master/src/python/WMCore/JobSplitting).

Code lives under `src/cms_wm_core/job_splitting/`.
Algorithm-specific detail is in the pages linked under
[Algorithms](#algorithms).

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
(see [EventAwareLumi](event-aware-lumi.md)).

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


## Algorithms

| Algorithm | Core idea | Detail |
| --- | --- | --- |
| FileBased | Pack whole files by `files_per_job` | [file-based.md](file-based.md) |
| FileLumiAware | FileBased + co-locate shared `(run, lumi)` | [file-lumi-aware.md](file-lumi-aware.md) |
| EventBased | No-input MC; disjoint events / unique lumis | [event-based.md](event-based.md) |
| EventAwareLumi | Pack `(run, lumi)` work by event/walltime target | [event-aware-lumi.md](event-aware-lumi.md) |
| MergeBySize | Merge by min/max output size band | [merge-by-size.md](merge-by-size.md) |

## Code sketch (interface)

Under `src/cms_wm_core/job_splitting/`:

| Module | Role |
| --- | --- |
| `types.py` | Dataclasses only: files, run/lumi triples, rates, budgets, jobs, results |
| `base.py` | `JobSplitter` ABC — subclasses must implement `name` and `split` |
| `file_based.py` | [FileBased](file-based.md) + `FileBasedRequest` |
| `file_lumi_aware.py` | [FileLumiAware](file-lumi-aware.md) |
| `event_based.py` | [EventBased](event-based.md) + `EventBasedRequest` |
| `file_common.py` | Shared estimate / validation helpers |
| `event_aware_lumi.py` | [EventAwareLumi](event-aware-lumi.md) |
| `merge_by_size.py` | [MergeBySize](merge-by-size.md) |
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


## Planned extract order

1. **FileBased** — [detail](file-based.md)
2. **FileLumiAware** — [detail](file-lumi-aware.md)
3. **EventBased** — [detail](event-based.md)
4. **EventAwareLumi** — [detail](event-aware-lumi.md)
5. **MergeBySize** — [detail](merge-by-size.md)
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

Resolve the open question under [EventAwareLumi](event-aware-lumi.md) (are `splitOnRun` /
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

v1 [MergeBySize](merge-by-size.md) packs by **file size** (sorted ``(-size, lfn)``, full-remainder
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

See [MergeBySize](merge-by-size.md) open note: v1 still merges a singleton oversize file. Future
work may add non-blocking signaling (metrics / baggage) so operators can see
merges that exceeded the configured max without failing the job in HTCondor.

### Run/lumi allow-list (subset of a file)

v1 [EventAwareLumi](event-aware-lumi.md) treats each file’s `run_lumis` as the full work set: every
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

v1 [EventBased](event-based.md) is **no-input MC**: one unique lumi per job and a disjoint
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
