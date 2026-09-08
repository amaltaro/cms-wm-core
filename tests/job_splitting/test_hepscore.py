"""Tests for HEPScore23 packing helpers."""

import pytest

from cms_wm_core.job_splitting.hepscore import (
    get_expected_hs23_s,
    wall_seconds_per_event,
)
from cms_wm_core.job_splitting.types import ResourceRates


def test_wall_seconds_from_hepscore23():
    rates = ResourceRates(
        hepscore23_s_per_event=20.0,
        baseline_hs23_per_core=10.0,
    )
    assert wall_seconds_per_event(rates) == 2.0


def test_wall_seconds_zero_when_unset_and_not_required():
    assert wall_seconds_per_event(ResourceRates()) == 0.0


def test_wall_seconds_require_raises_when_unset():
    with pytest.raises(ValueError, match="both > 0"):
        wall_seconds_per_event(ResourceRates(), require=True)


def test_wall_seconds_rejects_partial_hepscore23():
    with pytest.raises(ValueError, match="both be > 0"):
        wall_seconds_per_event(ResourceRates(hepscore23_s_per_event=1.0))
    with pytest.raises(ValueError, match="both be > 0"):
        wall_seconds_per_event(ResourceRates(baseline_hs23_per_core=1.0))


def test_get_expected_hs23_s_none_when_unset():
    assert get_expected_hs23_s(10, ResourceRates()) is None


def test_get_expected_hs23_s_on_hepscore_path():
    rates = ResourceRates(
        hepscore23_s_per_event=2.5,
        baseline_hs23_per_core=10.0,
    )
    assert get_expected_hs23_s(4, rates) == 10.0
