"""Abstract base for job splitting algorithms.

``JobSplitter`` is the **behavior** contract: every algorithm must implement
``split`` and ``name``. Request/response **shapes** live in ``types`` (and later in
per-algorithm request dataclasses).

This uses ``abc.ABC`` (explicit subclassing), not duck typing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from cms_wm_core.job_splitting.types import SplitResult

RequestT = TypeVar("RequestT")


class JobSplitter(ABC, Generic[RequestT]):
    """Minimum API every job-splitting algorithm must provide.

    Subclasses bind ``RequestT`` to their own request dataclass, e.g.
    ``class FileBasedSplitter(JobSplitter[FileBasedRequest])``.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable algorithm id (e.g. ``\"FileBased\"``)."""

    @abstractmethod
    def split(self, request: RequestT) -> SplitResult:
        """Pack the request into a deterministic ``SplitResult``."""
