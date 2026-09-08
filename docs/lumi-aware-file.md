# LumiAwareFile

FileBased packing that co-locates shared ``(run, lumi)`` components.

Part of the [job-splitting design](README.md).

---

Variant of FileBased that is **run+lumi aware**.

### Extra constraint

Each file must carry a non-empty ``run_lumis`` list of ``(run, lumi[, events])``
entries. Files that share any ``(run, lumi)`` — including **transitively**
through other files — form one atomic component and are always assigned to the
**same job**.

This algorithm is the **only** place that supports a run+lumi scattered across
multiple files. All other algorithms (including
[EventAwareLumi](event-aware-lumi.md)) and downstream steps require each
run+lumi to live in a single file.

### Packing

Same as FileBased otherwise:

- ``files_per_job`` packs whole **components** (never splits a component)
- A component larger than ``files_per_job`` still becomes one job
- Resource rates / targets / maxima apply to the files in the job
- Walltime uses HEPScore23 when both `hepscore23_s_per_event` and
  `baseline_hs23_per_core` are set, otherwise legacy `time_per_event`
  (shared ``file_common``; see [HEPScore23](hepscore23.md))
- Estimates use file-level ``events`` and ``size``; jobs set ``n_events`` to
  that event sum
- When packed with HEPScore23 rates, ``estimates.expected_hs23_s`` is
  ``n_events × hepscore23_s_per_event``; otherwise ``None``
- Input ``network`` is the sum of assigned file ``size`` (whole files)
- Deterministic: components ordered by minimum LFN; LFNs sorted within a job
