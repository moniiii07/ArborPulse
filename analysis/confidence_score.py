"""
confidence_score.py

Computes SylvaSense's multi-factor confidence score for a single detection run.

WHY THESE WEIGHTS (write-up for judges / README):
  - data_quality      (0.35) — highest weight. Bad input pixels are the least
                        recoverable failure mode: if the imagery itself is bad,
                        nothing downstream can be trusted, no matter how good
                        the model or calibration is.
  - model_agreement   (0.30) — cross-validates the primary detector (Open-Canopy)
                        against the independent NDVI signal. This is what makes
                        the score "multi-factor" rather than a single detector's
                        self-reported confidence.
  - temporal_gap      (0.20) — a large gap between Date A and Date B introduces
                        confounds (seasonal growth, unrelated disturbance) that
                        have nothing to do with the change we're trying to detect.
  - calibration_fit   (0.15) — lowest weight. This reflects how well the
                        per-region NDVI baseline calibration converged. Important,
                        but least directly tied to whether THIS pair of images
                        is trustworthy.

  Weights sum to 1.0. Keep them here, in one place, so the number that gates a
  real alert is never buried inside a function nobody reads.
"""

from dataclasses import dataclass, field
from typing import Optional

DEFAULT_WEIGHTS = {
    "data_quality": 0.35,
    "model_agreement": 0.30,
    "temporal_gap": 0.20,
    "calibration_fit": 0.15,
}

# Below this score, SylvaSense withholds the alert and flags for human review.
# [BOUNDARY #2 in the architecture doc]
DEFAULT_CONFIDENCE_THRESHOLD = 0.60

# Temporal gap tuning: full confidence up to IDEAL_GAP_DAYS, linear decay to 0
# confidence at MAX_GAP_DAYS.
IDEAL_GAP_DAYS = 30
MAX_GAP_DAYS = 180


@dataclass
class ConfidenceFactor:
    name: str
    raw_value: float          # the original input value, for the trail
    normalized: float         # 0-1
    weight: float
    contribution: float       # normalized * weight
    reasoning: str            # human-readable, goes straight into the decision trail


@dataclass
class ConfidenceResult:
    score: float
    threshold: float
    passed: bool
    factors: list = field(default_factory=list)

    def summary_line(self) -> str:
        verdict = "PASSED — alert cleared" if self.passed else "BELOW THRESHOLD — human review required"
        return f"Confidence {self.score:.2f} / threshold {self.threshold:.2f} → {verdict}"


def _normalize_temporal_gap(gap_days: float) -> float:
    """Full confidence up to IDEAL_GAP_DAYS, linear decay to 0 at MAX_GAP_DAYS."""
    if gap_days <= IDEAL_GAP_DAYS:
        return 1.0
    if gap_days >= MAX_GAP_DAYS:
        return 0.0
    return 1.0 - (gap_days - IDEAL_GAP_DAYS) / (MAX_GAP_DAYS - IDEAL_GAP_DAYS)


def compute_confidence(
    usable_pixel_pct: float,      # 0-100, from cloud_mask.py / quality_check.py
    ndvi_model_agreement: float,  # 0-1, agreement between Open-Canopy loss mask and NDVI loss mask
    temporal_gap_days: float,     # days between Date A and Date B
    calibration_fit_score: float, # 0-1, goodness of per-region NDVI baseline fit
    weights: Optional[dict] = None,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> ConfidenceResult:
    """
    Combine the four independent signals into one weighted confidence score.
    Every factor is kept individually visible in the result — this is what lets
    the decision trail show *why* a score landed where it did, not just the
    number itself.
    """
    w = weights or DEFAULT_WEIGHTS
    assert abs(sum(w.values()) - 1.0) < 1e-6, "Confidence weights must sum to 1.0"

    dq_norm = max(0.0, min(1.0, usable_pixel_pct / 100.0))
    dq = ConfidenceFactor(
        name="data_quality",
        raw_value=usable_pixel_pct,
        normalized=dq_norm,
        weight=w["data_quality"],
        contribution=dq_norm * w["data_quality"],
        reasoning=f"{usable_pixel_pct:.1f}% of pixels usable after cloud/shadow masking.",
    )

    agr_norm = max(0.0, min(1.0, ndvi_model_agreement))
    agr = ConfidenceFactor(
        name="model_agreement",
        raw_value=ndvi_model_agreement,
        normalized=agr_norm,
        weight=w["model_agreement"],
        contribution=agr_norm * w["model_agreement"],
        reasoning=f"Open-Canopy and NDVI cross-check agreed on {agr_norm*100:.0f}% of the flagged change area.",
    )

    temp_norm = _normalize_temporal_gap(temporal_gap_days)
    temp = ConfidenceFactor(
        name="temporal_gap",
        raw_value=temporal_gap_days,
        normalized=temp_norm,
        weight=w["temporal_gap"],
        contribution=temp_norm * w["temporal_gap"],
        reasoning=(
            f"{temporal_gap_days:.0f} days between Date A and Date B "
            f"(ideal ≤{IDEAL_GAP_DAYS}d, confidence reaches 0 at {MAX_GAP_DAYS}d)."
        ),
    )

    cal_norm = max(0.0, min(1.0, calibration_fit_score))
    cal = ConfidenceFactor(
        name="calibration_fit",
        raw_value=calibration_fit_score,
        normalized=cal_norm,
        weight=w["calibration_fit"],
        contribution=cal_norm * w["calibration_fit"],
        reasoning=f"Per-region NDVI baseline calibration fit score: {cal_norm:.2f}.",
    )

    factors = [dq, agr, temp, cal]
    total = sum(f.contribution for f in factors)

    return ConfidenceResult(
        score=round(total, 4),
        threshold=threshold,
        passed=total >= threshold,
        factors=factors,
    )


if __name__ == "__main__":
    # Quick manual sanity check
    result = compute_confidence(
        usable_pixel_pct=92.0,
        ndvi_model_agreement=0.81,
        temporal_gap_days=21,
        calibration_fit_score=0.74,
    )
    print(result.summary_line())
    for f in result.factors:
        print(f"  {f.name:16s} raw={f.raw_value!r:>8} norm={f.normalized:.2f} contrib={f.contribution:.3f}  {f.reasoning}")
