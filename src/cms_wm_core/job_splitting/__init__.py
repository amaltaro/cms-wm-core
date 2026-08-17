"""Job splitting algorithms (pure packing; no data discovery).

Typical layout:

* ``types`` — dataclasses for files, budgets, jobs, results (data)
* ``base`` — ``JobSplitter`` ABC (behavior every algorithm must implement)
* ``file_common`` — common functionality for file-based algorithms
* ``file_based`` / ``file_lumi_aware`` / ``event_based`` /
  ``event_aware_lumi`` / ``merge_by_size`` — concrete algorithms

See ``docs/job-splitting.md`` for design invariants.
"""

from cms_wm_core.job_splitting.base import JobSplitter
from cms_wm_core.job_splitting.event_aware_lumi import (
    EventAwareLumiRequest,
    EventAwareLumiSplitter,
)
from cms_wm_core.job_splitting.event_based import EventBasedRequest, EventBasedSplitter
from cms_wm_core.job_splitting.file_based import FileBasedRequest, FileBasedSplitter
from cms_wm_core.job_splitting.file_lumi_aware import (
    FileLumiAwareRequest,
    FileLumiAwareSplitter,
)
from cms_wm_core.job_splitting.merge_by_size import (
    MergeBySizeRequest,
    MergeBySizeSplitter,
)
from cms_wm_core.job_splitting.types import (
    ResourceBudgets,
    ResourceEstimates,
    ResourceRates,
    RunLumiEvents,
    RunLumiRange,
    SplitFile,
    SplitJob,
    SplitResult,
)

__all__ = [
    "EventAwareLumiRequest",
    "EventAwareLumiSplitter",
    "EventBasedRequest",
    "EventBasedSplitter",
    "FileBasedRequest",
    "FileBasedSplitter",
    "FileLumiAwareRequest",
    "FileLumiAwareSplitter",
    "JobSplitter",
    "MergeBySizeRequest",
    "MergeBySizeSplitter",
    "ResourceBudgets",
    "ResourceEstimates",
    "ResourceRates",
    "RunLumiEvents",
    "RunLumiRange",
    "SplitFile",
    "SplitJob",
    "SplitResult",
]
