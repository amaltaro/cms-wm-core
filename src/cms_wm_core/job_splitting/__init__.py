"""Job splitting algorithms (pure packing; no data discovery).

Typical layout:

* ``types`` — dataclasses for files, budgets, jobs, results (data)
* ``base`` — ``JobSplitter`` ABC (behavior every algorithm must implement)
* ``file_based`` — FileBased algorithm

See ``docs/job-splitting.md`` for design invariants.
"""

from cms_wm_core.job_splitting.base import JobSplitter
from cms_wm_core.job_splitting.file_based import FileBasedRequest, FileBasedSplitter
from cms_wm_core.job_splitting.types import (
    ResourceBudgets,
    ResourceEstimates,
    ResourceRates,
    RunLumiEvents,
    SplitFile,
    SplitJob,
    SplitResult,
)

__all__ = [
    "FileBasedRequest",
    "FileBasedSplitter",
    "JobSplitter",
    "ResourceBudgets",
    "ResourceEstimates",
    "ResourceRates",
    "RunLumiEvents",
    "SplitFile",
    "SplitJob",
    "SplitResult",
]
