# Job splitting

Design notes for extracting CMS workload-management job splitting into
`cms-wm-core`, with a path toward reuse in DiracX.

Upstream reference:
[WMCore JobSplitting](https://github.com/dmwm/WMCore/tree/master/src/python/WMCore/JobSplitting).

Code lives under `src/cms_wm_core/job_splitting/`.

## Documentation map

| Document | Contents |
| --- | --- |
| [architecture.md](architecture.md) | CMS data model, invariants, types, module layout, I/O contract |
| [resource-model.md](resource-model.md) | Rates, targets, maxima, packing close rules |
| [future-work.md](future-work.md) | Extract roadmap and cross-cutting TODOs |
| Algorithm pages (below) | Per-splitter behavior, scope, and open questions |

## Scope

In scope: **agent-style job splitting** — given an already resolved set of
files and split parameters, produce jobs (input files + masks + estimates).

Out of scope for the core algorithms:

- Data discovery (DBS, Rucio, CRIC)
- WorkQueue-style start policies (dataset/block → work elements)
- Persistence (WMBS commit, Couch/ACDC clients)
- T0 Express/Repack DAO-driven splitters (later, as adapters)
- Memory sizing / memory-based packing (see [architecture](architecture.md#worker-application-memory-is-out-of-scope-for-packing))

## Core invariants

Summarized here; rationale and detail in [architecture.md](architecture.md).

1. **Pre-scoped input** — the file list is already locality- and
   placement-consistent; cross-block packing and discovery are caller duties.
2. **Determinism** — same inputs always produce the same jobs (stable sort,
   explicit tie-breakers, characterization tests).
3. **Packing only** — splitters apply packing rules and resource budgets;
   they do not encode Rucio placement policy or fetch run/lumi from services.
4. **Worker RSS is out of scope** — grid-job application memory is not a
   packing budget; WM process memory under large workflows is (streaming /
   chunked output direction).
5. **Explicit types** — each algorithm has its own request dataclass;
   shared vocabulary lives in `types.py`.

## Algorithms

| Algorithm | Core idea | Detail |
| --- | --- | --- |
| FileBased | Pack whole files by `files_per_job` | [file-based.md](file-based.md) |
| FileLumiAware | FileBased + co-locate shared `(run, lumi)` | [file-lumi-aware.md](file-lumi-aware.md) |
| EventBased | No-input MC; disjoint events / unique lumis | [event-based.md](event-based.md) |
| EventAwareLumi | Pack `(run, lumi)` work by event/walltime target | [event-aware-lumi.md](event-aware-lumi.md) |
| MergeBySize | Merge by min/max output size band | [merge-by-size.md](merge-by-size.md) |

## Provenance

When porting, record upstream path and intent of changes in the module
docstring or PR (see `AGENTS.md`). Prefer behavior-preserving extraction,
then refactor behind the contracts in [architecture.md](architecture.md).
