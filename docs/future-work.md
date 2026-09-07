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

### HEPScore-normalized work (DiracX / PanDA alignment)

Wall-clock estimates today use a raw `time_per_event` (seconds per event on
an implicit machine class). That mis-sizes jobs across heterogeneous sites.
The intended redesign is to treat packing cost in **HEPScore23** units
(and later GPU scores such as HEPScore4GPU), not legacy DB12 / HS06 as the
target scale.

**Packing happens before the execution resource is known.** Job splitting
produces jobs without knowing which WN (or even which site’s average power)
will run them. Matchmaking / brokerage comes later. Therefore the splitter
cannot use the *actual* host HEPScore23; it must size against a
**baseline / reference** score (campaign-wide, VO-wide, or a site-average
supplied by the caller). Downstream layers may still apply site averages or
distributions when matching; that is outside the core packer.

**Simplest cms-wm-core direction (preferred first step):**

- Replace (or reinterpret) ``time_per_event`` as **HEPScore23·seconds per
  event** on a documented baseline node
- Keep ``target_job_walltime`` as the packing input: it means “desired wall
  time **if** the job ran on the baseline node”
- Then:

  ```text
  events_per_job =
    floor(target_job_walltime × baseline_HEPScore23 / hepscore23_s_per_event)
  ```

  Equivalently, walltime on the baseline is
  ``n_events × hepscore23_s_per_event / baseline_HEPScore23``. Job resource
  estimates stay in that baseline frame unless the caller later rescales.
- Do **not** require per-site power, multi-core ``ε``, or safety margins in
  the first cut; those can layer on later if needed
- Keep baseline score and rates as **request inputs** (caller-owned); the
  algorithm does not discover site HEPScore23

**Do not confuse node score, per-core power, and per-event work.** Official
HEPScore23 measures **node throughput** (workloads fill the machine); WLCG
accounting then publishes a **per-core** factor
(``score_per_node / logical_cores``). **HS23·s per event** is normalized
*work* for one event: it must **not** be divided by job core count when
moving from 1-core to N-core (that would double-count). Multi-core belongs in
available power (``N_cores × HS23_per_core × ε``), which shortens walltime for
the same per-event work. Example: 10 HS23·s/event stays 10 on two cores with
``ε = 1``; walltime halves because power doubles, not because the rate became
5.

**PanDA (ATLAS) as a related baseline.** PanDA JEDI already sizes from
normalized work ([Job Sizing](https://panda-wms.readthedocs.io/en/latest/advanced/sizing.html#job-sizing)):

- Task ``cpuTime`` is **HS06sec per event** historically; site **corepower**
  is moving to **HS23 per core** after WLCG’s HEPScore23 adoption
- PanDA can also pack *to a known resource’s* walltime limit using that
  resource’s corepower — a richer path than our first step, which only uses
  a baseline node so ``target_job_walltime`` stays meaningful pre-match
- Consumed work is accounted as benchmark·s
  (``hs23sec ≈ walltime × corepower × cores × …``)
- ATLAS also runs HEPScore23 via HammerCloud/PanDA to validate declared vs
  runtime corepower ([arXiv:2502.04853](https://arxiv.org/abs/2502.04853))

**Dirac / DiracX.** Prefer **HEPScore23** (and GPU successors) as the CMS /
DiracX-facing scale. Map whatever ``cpu-work`` matchmaking field DiracX
exposes onto HEPScore23·s; do not treat DB12 as the library’s target unit.

**TODO:** Design and (later) implement the minimal baseline-node model above;
defer site averages, ``ε``, and match-time rescaling until there is a clear
caller need. Until then, walltime targets assume an implicit machine class.
