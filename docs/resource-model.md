# Resource model

Rates, targets, maxima, and when to close one job and open the next.

Part of the [job-splitting design](README.md).

---

## When to close job A and open job B

Splitters need more than the file list: they need **budgets** that decide when
the current job is full and the next job should start. Those budgets come from
the caller (workload / site / pilot policy), not from discovery services.

### Packing targets (primary close conditions)

Algorithm-specific targets remain the usual close triggers, for example:

- `files_per_job` (FileBased, LumiAwareFile)
- `events_per_job` (EventBased, EventAwareLumi)
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

``ResourceEstimates.network`` is **input-read volume only** (primary input
bytes expected to be read). It does **not** include stage-out / output
network; that can reuse ``persisted_output`` later (see
[future-work.md](future-work.md)).

How input network is derived depends on the packing unit:

| Algorithms | Input network |
| --- | --- |
| FileBased, LumiAwareFile, MergeBySize | Sum of assigned input file ``size`` (whole files) |
| EventAwareLumi | ``n_events × input_size_per_event`` (fractional file work) |
| EventBased | ``0`` until real input and/or pileup are modeled |

Local vs remote replica choice is left to later matchmaking (late-binding);
the splitter reports a volume, not a site-specific transfer.

Network is an **estimate for planning and monitoring**. Whether it also acts
as a packing close condition is optional and algorithm-specific; wall time
and scratch remain the primary resource close drivers.

### Who supplies what (common resource inputs)

| Input | Meaning | Owner |
| --- | --- | --- |
| `time_per_event` | Average processing time per event | Caller (task / campaign performance) |
| `input_size_per_event` | Average input bytes per event | Caller and/or derived from file size/events |
| `transient_output_size_per_event` | Intermediate scratch bytes per event | Caller |
| `persisted_output_size_per_event` | Stage-out bytes per event (also on scratch while running) | Caller |
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
