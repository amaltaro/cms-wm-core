"""HEPScore23 helpers for packing (baseline node, 1-core first cut).

See ``docs/hepscore23.md``. Not re-exported from the package ``__init__``.
"""

from __future__ import annotations

from cms_wm_core.job_splitting.types import ResourceRates


def wall_seconds_per_event(
    rates: ResourceRates,
    *,
    require: bool = False,
) -> float:
    """Wall-clock seconds per event on the packing baseline (1 core, ε=1).

    ``wall_s = hepscore23_s_per_event / baseline_hs23_per_core`` when both
    rates are positive. Both unset (0) yields ``0.0`` unless ``require`` is
    true. A partial pair raises ``ValueError``.
    """
    hs = rates.hepscore23_s_per_event
    base = rates.baseline_hs23_per_core
    if hs > 0.0 and base > 0.0:
        return hs / base
    if hs > 0.0 or base > 0.0:
        raise ValueError(
            "hepscore23_s_per_event and baseline_hs23_per_core must both be "
            f"> 0 when using HEPScore23 packing; got {hs} and {base}"
        )
    if require:
        raise ValueError(
            "need hepscore23_s_per_event and baseline_hs23_per_core (both > 0)"
        )
    return 0.0


def get_expected_hs23_s(n_events: int, rates: ResourceRates) -> float | None:
    """Expected job work in HS23·s, or None when HS23 rates are unset."""
    if rates.hepscore23_s_per_event <= 0.0 or rates.baseline_hs23_per_core <= 0.0:
        return None
    return float(n_events) * rates.hepscore23_s_per_event
