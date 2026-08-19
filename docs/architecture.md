# Job splitting architecture

Data structures, invariants, module layout, and the caller/splitter contract.

Part of the [job-splitting design](README.md).

---

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

Local vs remote replica choice is **late-binding**: matchmaking / execution,
not job splitting. Splitters do not take per-file location hints.

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

## Code sketch (interface)

Under `src/cms_wm_core/job_splitting/`:

| Module | Role |
| --- | --- |
| `types.py` | Dataclasses only: files, run/lumi triples, rates, budgets, jobs, results |
| `base.py` | `JobSplitter` ABC — subclasses must implement `name` and `split` |
| `file_common.py` | Shared estimate / validation helpers |
| `file_based.py` | [FileBased](file-based.md) + `FileBasedRequest` |
| `lumi_aware_file.py` | [LumiAwareFile](lumi-aware-file.md) + `LumiAwareFileRequest` |
| `event_based.py` | [EventBased](event-based.md) + `EventBasedRequest` |
| `event_aware_lumi.py` | [EventAwareLumi](event-aware-lumi.md) + `EventAwareLumiRequest` |
| `merge_by_size.py` | [MergeBySize](merge-by-size.md) + `MergeBySizeRequest` |
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

- `lfn`, `events`, `size`
- `first_event` (unused in v1; reserved for a future input-file EventBased)
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
  - network (sum of assigned input file sizes; not local-vs-remote)
- optional creation-failure / unsplittable marker and reason
- small baggage dict if needed

No memory estimate from the splitter.

## Diagrams (planned)

Mermaid diagrams for caller → splitter → jobs flow, type relationships, and
the packing loop will be added here.
