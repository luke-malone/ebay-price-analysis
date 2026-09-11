"""Small, dependency-free robust statistics helpers."""

from __future__ import annotations

from statistics import median
from typing import Sequence

MODIFIED_Z_SCALE = 0.6745


def median_absolute_deviation(values: Sequence[float], centre: float | None = None) -> float:
    """Calculate unscaled MAD: median(abs(x - median(x)))."""
    if not values:
        raise ValueError("MAD is undefined for an empty sequence")
    centre = median(values) if centre is None else centre
    return float(median([abs(value - centre) for value in values]))


def modified_z_score(value: float, centre: float, mad: float) -> float | None:
    """Return the modified z-score, or None when MAD is zero."""
    if mad == 0:
        return None
    return MODIFIED_Z_SCALE * (value - centre) / mad
