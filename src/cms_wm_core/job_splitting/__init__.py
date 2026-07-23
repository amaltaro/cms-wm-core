"""Job splitting algorithms.

Typical layout:

* ``types`` — dataclasses for files, budgets, jobs, results (data)
* ``base`` — ``JobSplitter`` ABC (behavior every algorithm must implement)
* ``file_based`` etc. — concrete algorithms (added later)

See ``docs/job-splitting.md`` for design invariants.
"""

from cms_wm_core.job_splitting.base import JobSplitter
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
    "JobSplitter",
    "ResourceBudgets",
    "ResourceEstimates",
    "ResourceRates",
    "RunLumiEvents",
    "SplitFile",
    "SplitJob",
    "SplitResult",
]
