# HEPScore23 and job sizing

Design notes for **HEPScore23·seconds per event** packing while still
targeting a wall-clock job duration (CMS often aims for ~12 h). Opaque
wall-clock ``time_per_event`` was removed; timing is HS23-only.

Part of the [job-splitting design](README.md). Helpers live in
``job_splitting.hepscore``. All v1 splitters use them for walltime estimates
and (where applicable) packing; see
[future-work](future-work.md#hepscore23-normalized-packing) for deferred
multi-core / site / match-time work.

---

## Why normalize

Wall-clock seconds depend on the worker. The same workflow on a faster CPU
finishes sooner. HEPScore23 (HS23) is the WLCG CPU benchmark scale (successor
to HS06). Expressing event cost as **HS23·seconds** makes packed work portable;
wall time on a given machine follows from that machine’s power.

Packing still happens **before** the execution resource is known. The splitter
therefore sizes against a **baseline** HS23 per core (campaign-, VO-, or
caller-supplied average)—not the eventual WN. Matchmaking may rescale later.

## Vocabulary

| Term | Meaning |
| --- | --- |
| **HS23 node score** | Throughput of a full machine from the official HEPScore23 run (workloads fill the node) |
| **HS23 per core** | Accounting / corepower factor: ``node_score / logical_cores`` ([WLCG accounting](https://w3.hepix.org/benchmarking/accounting_migration.html)) |
| **HS23·seconds (HS23·s)** | Normalized **work** = power × time (same idea as historical HS06·s) |
| **HS23·s per event** | Work required to process one event |
| **Baseline HS23/core** | Reference power used at pack time (pre-match) |
| **Wall s per event** | Wall-clock seconds per event **on a stated machine** |

### Node score vs core count (common pitfall)

HS23 as a **benchmark** is a **node** measurement. WLCG then publishes a
**per-core** factor for pledges and job accounting.

**HS23·s per event is work for one event.** Do **not** divide it by job core
count when going from 1-core to N-core (that double-counts). Multi-core
belongs in **available power**:

```text
available_power = N_cores × hs23_per_core × ε
```

where ``ε ≤ 1`` is parallel efficiency. Example: 10 HS23·s/event stays **10**
on two cores with ``ε = 1``; walltime halves because power doubles, not
because the rate became 5.

## What is HEPScore23·seconds per event?

``hepscore23_s_per_event`` is the normalized CPU **work** to process one
event of the workflow. It is independent of how many cores the job requests.

### Calibration vs pack time (two different HS23/core values)

The power of the machine that **measured** the event is required to *form*
``hepscore23_s_per_event``. It is **not** the same role as the baseline used
when packing to ~12 h.

| Stage | HS23/core involved | Role |
| --- | --- | --- |
| **Calibration** | ``hs23_per_core`` of the sample / test machine | Convert measured wall s/event → portable **work** |
| **Packing** | ``baseline_hs23_per_core`` (reference for ~12 h) | Convert that work → wall time on the baseline |

Calibration (run one or more sample events on a known machine):

```text
hepscore23_s_per_event =
  measured_wall_s_per_event × N_cores_used × hs23_per_core_calib × ε_observed
```

For a careful single-core calibration (``N_cores_used = 1``, ``ε = 1``):

```text
hepscore23_s_per_event =
  measured_wall_s_per_event × hs23_per_core_calib
```

Once ``hepscore23_s_per_event`` is stored, **``hs23_per_core_calib`` is
already baked into that number.** Packing only needs the work figure plus
``baseline_hs23_per_core`` (which may equal the calibration machine, or may
be a campaign-wide reference—often they match by choice, but they are
logically distinct).

Example: measured 2 s/event on a 12 HS23/core box → work = 24 HS23·s/event.
Packing to 12 h on a **15** HS23/core baseline uses 24 and 15; it does not
need “12” again unless you are still holding raw wall seconds instead of work.

**What the splitter must see**

- **Preferred:** caller passes precomputed ``hepscore23_s_per_event`` +
  ``baseline_hs23_per_core`` + ``target_job_walltime``. Calibration power is
  a workflow-setup concern (ReqMgr / campaign DB / docs), not a live
  ``split()`` field.
- **Alternative:** caller passes ``measured_wall_s_per_event`` +
  ``hs23_per_core_calib`` (+ cores/ε); the library (or a thin helper)
  multiplies them into work, then packs with ``baseline_hs23_per_core``.
  Useful if CMS keeps raw timing + machine metadata separate.

Either way, **calibration power is part of the workflow definition path**;
only the alternative makes it an explicit splitter input. Omitting it
entirely is wrong if you only have wall seconds—you cannot get portable
work without knowing how fast the timing machine was.

Store provenance (which machine / HS23/core was used for calibration) with
the workflow even when the splitter only consumes the derived work rate.

### One-core vs N-core workflows

| Case | How to treat ``hepscore23_s_per_event`` |
| --- | --- |
| Single-core job | Calibrate as above; packing uses ``N_cores = 1`` |
| Multi-core job | Keep the **same** per-event work if the *event* cost is unchanged; put parallelism in ``N_cores × ε`` when converting to wall time |
| Multi-core changes physics/app cost per event | Re-measure work per event on the multi-core configuration; still do **not** “divide by N” as a shortcut |

First cms-wm-core cut: assume 1-core packing (``N_cores = 1``, ``ε = 1``)
unless the request explicitly passes otherwise.

## From work to wall-clock seconds per event

On any machine (or the baseline):

```text
wall_s_per_event =
  hepscore23_s_per_event / (N_cores × hs23_per_core × ε)
```

Today’s packing uses this quantity on an **explicit** baseline:

```text
wall_s_per_event_baseline =
  hepscore23_s_per_event / (N_cores × baseline_hs23_per_core × ε)
```

(Historical note: an opaque wall-clock ``time_per_event`` used to stand in
for this on an implicit machine; that field has been removed.)

## Events per job and target wallclock time

CMS still wants jobs that run about ``target_job_walltime`` (e.g. 12 h) **on
the baseline**. That does not change:

```text
events_per_job =
  floor(target_job_walltime / wall_s_per_event)
  = floor(
      target_job_walltime × N_cores × baseline_hs23_per_core × ε
      / hepscore23_s_per_event
    )
```

Equivalently, estimated walltime on the baseline for a packed job:

```text
estimated_walltime_baseline =
  n_events × hepscore23_s_per_event
  / (N_cores × baseline_hs23_per_core × ε)
```

### Example (1 core, ε = 1)

| Input | Value |
| --- | --- |
| ``hepscore23_s_per_event`` | 10 |
| ``baseline_hs23_per_core`` | 15 |
| ``target_job_walltime`` | 12 h = 43200 s |

```text
wall_s_per_event = 10 / 15 ≈ 0.667 s
events_per_job   = floor(43200 / 0.667) ≈ 64800
job_work         = 64800 × 10 = 648000 HS23·s
```

### Request inputs (first cut)

| Input | Role |
| --- | --- |
| ``hepscore23_s_per_event`` | Work per event (from calibration; see above) |
| ``baseline_hs23_per_core`` | Baseline core power for ~12 h walltime |
| ``target_job_walltime`` | Desired wall time on that baseline |
| ``N_cores``, ``ε`` | Optional later; default 1, 1 |

Optional instead of precomputed work: ``measured_wall_s_per_event`` +
``hs23_per_core_calib`` (library derives work). Caller-owned; the splitter
does not discover site HS23.

## Accounting for completed jobs

After execution, WLCG / APEL-style accounting uses wall time, processors, and
the site’s per-core ServiceLevel (HS23/core):

```text
consumed_hs23_s ≈
  walltime_s × Processors × service_level_hs23_per_core
  × (cpu_efficiency adjustments as applicable)
```

([WLCG HS23 accounting migration](https://w3.hepix.org/benchmarking/accounting_migration.html)).

For cms-wm-core / upper layers:

1. At pack time, record **expected work** on
   ``ResourceEstimates.expected_hs23_s``
   (``n_events × hepscore23_s_per_event``, baseline frame)
2. At completion, the WMS (or site accounting) records **consumed** HS23·s
   from actual walltime × cores × site HS23/core
3. Compare expected vs consumed for monitoring; do not require the splitter
   to know the final host

PanDA follows the same pattern: size from benchmark·s per event, account
consumed work as benchmark·s using site corepower
([Job Sizing](https://panda-wms.readthedocs.io/en/latest/advanced/sizing.html#job-sizing);
corepower moving to HS23/core after WLCG adoption).

## Relation to PanDA and DiracX

- **PanDA:** task ``cpuTime`` is historically HS06sec/event; walltime on a
  resource uses cores × corepower. Richer than our first step (can pack to a
  *known* queue’s wall limit). We start with baseline-only packing so
  ``target_job_walltime`` stays meaningful pre-match.
- **DiracX:** prefer HS23 (and later GPU scores) as the CMS-facing scale.
  Map whatever matchmaking ``cpu-work`` field appears onto HS23·s. DB12 is
  not this library’s target unit.
- ATLAS also runs HS23 via HammerCloud/PanDA to validate declared vs runtime
  corepower ([arXiv:2502.04853](https://arxiv.org/abs/2502.04853)).

## Implementation status

| Piece | Status |
| --- | --- |
| ``ResourceRates.hepscore23_s_per_event`` /
  ``baseline_hs23_per_core`` | Done (``time_per_event`` removed) |
| ``wall_seconds_per_event`` / ``get_expected_hs23_s`` helpers | Done |
| ``ResourceEstimates.expected_hs23_s`` | Done |
| All v1 splitters (HS23-only packing / estimates) | Done |
| Multi-core ``ε``, site HS23, match-time rescaling | Deferred |

First cut keeps 1-core, ``ε = 1``, baseline-only packing.
