"""Small summary statistics that skip missing values."""

from __future__ import annotations

from collections.abc import Iterable, Sequence


def mean(values: Iterable[float | None]) -> float | None:
    """Mean of the non-None values rounded to 4 places; None when nothing is left."""
    kept = [v for v in values if v is not None]
    return round(sum(kept) / len(kept), 4) if kept else None


def rate(flags: Iterable[bool | None]) -> float | None:
    """Share of True among the non-None flags."""
    return mean(1.0 if flag else 0.0 for flag in flags if flag is not None)


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Linear-interpolation percentile (fraction in 0..1) rounded to 1 place."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 1)
