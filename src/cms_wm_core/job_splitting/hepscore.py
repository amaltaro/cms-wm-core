"""HEPScore23 helpers for packing (baseline node, 1-core first cut).

See ``docs/hepscore23.md``. Not re-exported from the package ``__init__``.
"""

from __future__ import annotations

from cms_wm_core.job_splitting.types import ResourceRates


def uses_hepscore23(rates: ResourceRates) -> bool:
    """True when both HS23 work and baseline power are set (> 0)."""
    return (
        rates.hepscore23_s_per_event > 0.0
        and rates.baseline_hs23_per_core > 0.0
    )


def wall_seconds_per_event(
    rates: ResourceRates,
    *,
    require: bool = False,
) -> float:
    """Wall-clock seconds per event on the packing baseline (1 core, ε=1).

    Prefer HEPScore23 when both ``hepscore23_s_per_event`` and
    ``baseline_hs23_per_core`` are positive:

    ``wall_s = hepscore23_s_per_event / baseline_hs23_per_core``

    Otherwise fall back to legacy ``time_per_event``.
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
    if rates.time_per_event > 0.0:
        return rates.time_per_event
    if require:
        raise ValueError(
            "need hepscore23_s_per_event and baseline_hs23_per_core "
            "(both > 0), or time_per_event > 0"
        )
    return 0.0


def get_expected_hs23_s(n_events: int, rates: ResourceRates) -> float | None:
    """Expected job work in HS23·s, or None when not on the HEPScore23 path."""
    if not uses_hepscore23(rates):
        return None
    return float(n_events) * rates.hepscore23_s_per_event
