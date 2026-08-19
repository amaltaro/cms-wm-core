# FileBased

Whole-file packing by ``files_per_job``.

Part of the [job-splitting design](README.md).

---

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

**Input files:** required `lfn`, `events`, and `size` (size feeds the input
network estimate). `run_lumis` is ignored if present.

**Input request:** `files_per_job`, file tuple, `ResourceRates`, optional
`ResourceBudgets`.

**Output:** ordered ``SplitResult.jobs`` (LFN-sorted packing). Each job sets
``n_events`` to the sum of assigned file-level ``events`` (same total used for
resource estimates). Input ``network`` is the sum of assigned file ``size``
values. Deterministic for the same input.
