"""Convert pipeline evidence into a conservative dashboard-ready decision."""
from __future__ import annotations

from typing import Any


def build_decision_summary(
    before: dict[str, Any], after: dict[str, Any], ndvi_change: dict[str, Any],
    confidence: dict[str, Any], hansen_validation: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return an explainable recommendation without claiming deforestation.

    A strong NDVI decline initiates a review. It is deliberately not elevated to
    an automatic alert because crop cycles, fires, water, and seasonality can
    produce a similar spectral signal.
    """
    quality_passed = before["quality"]["status"] == "ok" and after["quality"]["status"] == "ok"
    delta = float(ndvi_change["mean_delta"])
    review_area = float(ndvi_change["loss_pixel_pct"])
    evidence = [
        f"Both scenes passed the 60% usable-pixel gate ({before['usable_pixel_pct']}% and {after['usable_pixel_pct']}%).",
        f"Mean NDVI changed by {delta:+.4f}; {review_area:.2f}% of observed pixels met the vegetation-decline screening rule.",
    ]
    limitations = [
        "NDVI decline is a vegetation-change signal, not proof of deforestation.",
        "The comparison dates are in different seasons; seasonal vegetation differences may contribute to the signal.",
        "Open-Canopy canopy-height inference is pending checkpoint validation.",
    ]
    if hansen_validation:
        overlap = float(hansen_validation["ndvi_review_overlap_pct"])
        evidence.append(f"{overlap:.2f}% of NDVI review pixels overlap 2025 Hansen annual tree-cover-loss pixels.")
        limitations.append("Hansen is an annual 30 m reference product, not ground truth for this specific event.")

    if quality_passed and delta <= -0.20:
        status = "review_required"
        headline = "Substantial vegetation decline detected — validate before reporting deforestation."
        recommendation = "Inspect the red review-queue pixels in the Earth Engine map and corroborate with high-resolution imagery."
    elif not quality_passed:
        status = "insufficient_data"
        headline = "Scene quality is below the required threshold."
        recommendation = "Use the logged retry candidates or choose a clearer date window before interpreting change."
    else:
        status = "no_strong_signal"
        headline = "No substantial NDVI decline crossed the review threshold."
        recommendation = "Continue monitoring; do not create a deforestation incident from this comparison alone."

    return {
        "status": status,
        "headline": headline,
        "confidence_label": confidence["label"],
        "recommendation": recommendation,
        "evidence": evidence,
        "limitations": limitations,
    }
