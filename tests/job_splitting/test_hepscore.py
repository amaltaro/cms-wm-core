"""Tests for HEPScore23 packing helpers."""

import pytest

from cms_wm_core.job_splitting.hepscore import (
    get_expected_hs23_s,
    uses_hepscore23,
    wall_seconds_per_event,
)
from cms_wm_core.job_splitting.types import ResourceRates


def test_uses_hepscore23_requires_both_positive():
    assert uses_hepscore23(ResourceRates()) is False
    assert uses_hepscore23(ResourceRates(hepscore23_s_per_event=1.0)) is False
    assert uses_hepscore23(ResourceRates(baseline_hs23_per_core=1.0)) is False
    assert (
        uses_hepscore23(
            ResourceRates(
                hepscore23_s_per_event=1.0,
                baseline_hs23_per_core=2.0,
            )
        )
        is True
    )


def test_wall_seconds_prefers_hepscore23():
    rates = ResourceRates(
        time_per_event=99.0,
        hepscore23_s_per_event=20.0,
        baseline_hs23_per_core=10.0,
    )
    assert wall_seconds_per_event(rates) == 2.0


def test_wall_seconds_falls_back_to_time_per_event():
    assert wall_seconds_per_event(ResourceRates(time_per_event=3.5)) == 3.5


def test_wall_seconds_zero_when_unset_and_not_required():
    assert wall_seconds_per_event(ResourceRates()) == 0.0


def test_wall_seconds_require_raises_when_unset():
    with pytest.raises(ValueError, match="time_per_event"):
        wall_seconds_per_event(ResourceRates(), require=True)


def test_wall_seconds_rejects_partial_hepscore23():
    with pytest.raises(ValueError, match="both be > 0"):
        wall_seconds_per_event(ResourceRates(hepscore23_s_per_event=1.0))


def test_get_expected_hs23_s_none_on_legacy_path():
    assert get_expected_hs23_s(10, ResourceRates(time_per_event=1.0)) is None


def test_get_expected_hs23_s_on_hepscore_path():
    rates = ResourceRates(
        hepscore23_s_per_event=2.5,
        baseline_hs23_per_core=10.0,
    )
    assert get_expected_hs23_s(4, rates) == 10.0
