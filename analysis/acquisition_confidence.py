"""Confidence label based only on acquisition quality and calibration presence.

This intentionally differs from Member B's richer decision-trail score, which
expects canopy-model agreement. The Open-Canopy model is not enabled in the
current Amazon workflow, so the live pipeline must not pretend that agreement
exists.
"""
from __future__ import annotations


def score(usable_before_pct: float, usable_after_pct: float, calibration_available: bool) -> dict[str, object]:
    pixel_component = min(usable_before_pct, usable_after_pct) / 100
    value = 0.8 * pixel_component + 0.2 * float(calibration_available)
    return {
        "score": round(value, 2),
        "label": "high" if value >= 0.8 else "medium" if value >= 0.6 else "low",
        "basis": "acquisition_quality_and_calibration_only",
    }
