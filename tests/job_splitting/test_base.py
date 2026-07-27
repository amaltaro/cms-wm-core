"""Tests for the job-splitting ABC.

``JobSplitter[FileBasedRequest]`` guides static type checkers. At runtime,
Python only enforces that abstract methods are implemented — not the request
type parameter. Wrong request objects are a type-checker / review concern
unless a concrete ``split`` adds its own validation.
"""

import pytest

from cms_wm_core.job_splitting import FileBasedRequest, JobSplitter, SplitResult


def test_job_splitter_cannot_be_instantiated():
    """The ABC itself is not a usable algorithm."""
    with pytest.raises(TypeError):
        JobSplitter()


def test_subclass_missing_split_cannot_be_instantiated():
    """Both abstract members are required; name alone is not enough."""

    class IncompleteSplitter(JobSplitter[FileBasedRequest]):
        @property
        def name(self) -> str:
            return "Incomplete"

    with pytest.raises(TypeError):
        IncompleteSplitter()


def test_subclass_missing_name_cannot_be_instantiated():
    """Both abstract members are required; split alone is not enough."""

    class IncompleteSplitter(JobSplitter[FileBasedRequest]):
        def split(self, request: FileBasedRequest) -> SplitResult:
            return SplitResult(jobs=())

    with pytest.raises(TypeError):
        IncompleteSplitter()

