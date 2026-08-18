# Future work

Roadmap and cross-cutting TODOs.

Part of the [job-splitting design](README.md).

---

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
