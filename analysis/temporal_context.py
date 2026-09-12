"""Describe whether two satellite dates are seasonally comparable."""
from __future__ import annotations

from datetime import date


def comparison_context(before_date: str, after_date: str) -> dict[str, int | bool | str]:
    """Return date-gap and same-season context for a before/after comparison."""
    before = date.fromisoformat(before_date)
    after = date.fromisoformat(after_date)
    if after <= before:
        raise ValueError("The after date must be later than the before date.")
    month_distance = abs(after.month - before.month)
    month_distance = min(month_distance, 12 - month_distance)
    same_season = month_distance <= 1
    return {
        "day_gap": (after - before).days,
        "month_distance": month_distance,
        "same_season": same_season,
        "status": "same_season" if same_season else "seasonal_mismatch",
        "interpretation": (
            "Dates are seasonally comparable; this reduces seasonal vegetation confounding."
            if same_season
            else "Dates are from different seasons; vegetation seasonality may confound observed change."
        ),
    }
