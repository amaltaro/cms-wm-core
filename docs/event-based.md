# EventBased

No-input Monte Carlo: disjoint event ranges and unique lumis.

Part of the [job-splitting design](README.md).

---

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
