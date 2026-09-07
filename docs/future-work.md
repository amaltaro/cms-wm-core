# Future work

Roadmap and cross-cutting TODOs.

Part of the [job-splitting design](README.md).

---

## Planned extract order

1. **FileBased** — [detail](file-based.md)
2. **LumiAwareFile** — [detail](lumi-aware-file.md)
3. **EventBased** — [detail](event-based.md)
4. **EventAwareLumi** — [detail](event-aware-lumi.md)
5. **MergeBySize** — [detail](merge-by-size.md)
6. **LumiBased** (optional) — fixed `lumis_per_job` if still needed apart from
   EventAwareLumi

Defer: other merge/sibling/Harvest splitters, WorkQueue start policies,
T0-specific algorithms, FileBased parentage and `jobs_per_group`, EventBased
real-file and ACDC paths, EventAwareLumi parents / pileup baggage / ACDC
clients / run-lumi allow-list.

## Algorithm-specific open items

These topics are documented on the algorithm pages (not duplicated here):

| Topic | Page |
| --- | --- |
| Run / file boundary policy | [event-aware-lumi.md](event-aware-lumi.md#future-work-run--file-boundary-policy) |
| Run/lumi allow-list | [event-aware-lumi.md](event-aware-lumi.md#future-work-runlumi-allow-list) |
| Contiguous run/lumi merge variant | [merge-by-size.md](merge-by-size.md#future-work-contiguous-runlumi-order) |
| Oversize merge ops visibility | [merge-by-size.md](merge-by-size.md#future-work-oversize-inputs-ops-visibility) |
| Large MC lumis / input datasets | [event-based.md](event-based.md#future-work-large-mc-lumis--input-datasets) |

## Cross-cutting TODOs

### Pileup in resource estimates (especially network)

CMS jobs often read **pileup** datasets in addition to primary input (or, for
MC EventBased, in addition to generating events with no primary input files).
Pileup can dominate remote I/O.

Today `ResourceEstimates.network` is **input-read volume only**:

- FileBased / LumiAwareFile / MergeBySize: sum of primary input file sizes
- EventAwareLumi: `n_events × input_size_per_event`
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

### Output / stage-out network

``ResourceEstimates.network`` does not yet include bytes written to shared
storage. ``persisted_output`` already estimates that stage-out volume; a later
revision may expose output network explicitly (or document that callers add
``persisted_output`` to input ``network`` for total transfer planning).

### OpenTelemetry observability

Job splitters are pure packing today: callers see only the returned
``SplitResult``. That is fine for unit tests, but in production the upper
layer (orchestrator, DiracX service, …) and monitoring stacks cannot see
what happened inside ``split`` without re-deriving it from inputs/outputs.

**TODO:** Add optional [OpenTelemetry](https://opentelemetry.io/)
instrumentation so splitters are not a black box. Direction:

- Emit a span (and/or metrics) per ``split`` call with stable attributes such
  as algorithm ``name``, input scale (file count, total events, lumi count),
  output scale (job count, unsplittable count), and wall time of the pack
- Prefer **aggregates and counters** over dumping full LFN lists or run/lumi
  maps into span attributes (those can be huge and hurt WM process memory /
  exporter cost)
- Keep packing math free of vendor SDKs: use the OTel API with a no-op
  provider when unset, or an optional extra / thin instrumentation wrapper so
  core install stays dependency-light
- Align attribute naming and context propagation with whatever DiracX (or the
  caller) already uses for traces, so a request can be followed from workflow
  intake through splitting into job enqueue

Until then, observability stops at the library boundary; callers must log or
trace around ``split`` themselves.

### HEPScore23-normalized packing

Wall-clock ``time_per_event`` assumes an implicit machine class. The intended
redesign uses **HEPScore23·s per event** plus a **baseline HS23/core**, while
keeping ``target_job_walltime`` (e.g. ~12 h on that baseline).

Full design (definitions, 1-core vs N-core, walltime bridge, packing formulas,
completed-job accounting, PanDA/DiracX notes):
[hepscore23.md](hepscore23.md).

**Status:** shared helpers + [EventBased](event-based.md) packing are in
tree. Migrate the other algorithms one at a time; defer site averages,
``ε``, and match-time rescaling until there is a clear caller need.
