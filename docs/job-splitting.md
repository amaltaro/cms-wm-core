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
| Event count | Events in that run/lumi for this file |

Not every algorithm needs this map (e.g. pure FileBased may only use file
totals). Lumi- and event-aware algorithms do.

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
| `transient_output_size_per_event` | Output written to worker **scratch** | Scratch disk estimate and disk target/max packing |
| `persisted_output_size_per_event` | Output that must be **staged out** to long-term storage | Stage-out volume estimate (not necessarily a close condition) |

**Scratch disk estimate** (normative intent):

```text
estimated_scratch ≈ n_events × transient_output_size_per_event
```

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
| `transient_output_size_per_event` | Scratch output bytes per event | Caller |
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
| per-algorithm modules | Own `*Request` dataclass + `JobSplitter[ThatRequest]` |

`typing.Protocol` / duck typing is intentionally avoided so each field has an
explicit dataclass type. See `_example.py` for a tiny illustrative subclass.

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

- Job groups (stable order; deterministic for the given inputs)
- Each job: ordered input LFNs, mask, **resource estimates**:
  - wall time
  - scratch disk (from transient output, ± TBD input staging)
  - persisted / stage-out volume
  - network (from input size when remote read applies)
- optional creation-failure / unsplittable marker and reason
- small baggage dict if needed

No memory estimate from the splitter.

## Planned extract order

1. **FileBased** — clearest packing; characterization tests first
2. **EventBased** — establishes mask semantics
3. **LumiBased**, then **EventAwareLumiBased** — production processing path

Defer: merge/sibling/Harvest splitters, WorkQueue start policies, T0-specific
algorithms.

## Provenance

When porting, record upstream path and intent of changes in the module
docstring or PR (see `AGENTS.md`). Prefer behavior-preserving extraction,
then refactor behind the contracts above.
