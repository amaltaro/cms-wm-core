"""Tests for the job-splitting ABC and shared types.

``JobSplitter[FileBasedRequest]`` guides static type checkers. At runtime,
Python only enforces that abstract methods are implemented — not the request
type parameter. Wrong request objects are a type-checker / review concern
unless a concrete ``split`` adds its own validation.
"""

import pytest

from cms_wm_core.job_splitting import JobSplitter, SplitFile, SplitResult
from cms_wm_core.job_splitting._example import FileBasedRequest, IdentityFileSplitter


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
            return SplitResult(job_groups=())

    with pytest.raises(TypeError):
        IncompleteSplitter()


def test_identity_splitter_is_deterministic():
    files = (
        SplitFile(lfn="/store/b.root", events=20),
        SplitFile(lfn="/store/a.root", events=10),
    )
    request = FileBasedRequest(files=files, files_per_job=1)
    splitter = IdentityFileSplitter()

    first = splitter.split(request)
    second = splitter.split(request)

    assert first == second
    assert splitter.name == "IdentityFile"
    assert isinstance(first, SplitResult)
    # Sorted by LFN: a before b.
    assert first.job_groups[0][0].input_lfns == ("/store/a.root",)
    assert first.job_groups[0][1].input_lfns == ("/store/b.root",)
