"""
orchestrator.py

The actual automation layer — this is what makes SylvaSense/ArborPulse
"autonomous" rather than "a script someone runs with a flag telling it what
to do." The orchestrator decides, at runtime, whether image quality is good
enough to proceed or whether to retry with a different date window
[BOUNDARY #1], and separately whether its own confidence is high enough to
release an alert or defer to a human [BOUNDARY #2]. No human picks the
outcome in advance — that's the whole point.

Built with dependency injection: fetch_fn / detect_fn / gap_fn / biomass_fn
are swappable. Right now they default to mock_adapters. Once Member A's real
modules exist, swap ONE line in `main()` — nothing in the orchestrator logic
itself needs to change, because it only depends on function signatures
(the JSON contract), not implementations.
"""

import uuid
from typing import Callable, Optional

from analysis.confidence_score import compute_confidence, ConfidenceResult
from reasoning_log.decision_trail import DecisionTrail
from automation.mock_adapters import (
    mock_fetch_and_quality_check,
    mock_detection_and_crosscheck,
    mock_temporal_gap_days,
    mock_biomass_carbon,
)

# Autonomous retry policy — the system's own boundary, not a human's choice per run.
MAX_RETRIES = 2
MIN_USABLE_PIXEL_PCT = 70.0


class PipelineOrchestrator:
    def __init__(
        self,
        fetch_fn: Callable[[str, int], dict] = mock_fetch_and_quality_check,
        detect_fn: Callable[[str], dict] = mock_detection_and_crosscheck,
        gap_fn: Callable[[], float] = mock_temporal_gap_days,
        biomass_fn: Callable[[float], dict] = mock_biomass_carbon,
        max_retries: int = MAX_RETRIES,
        min_usable_pixel_pct: float = MIN_USABLE_PIXEL_PCT,
    ):
        self.fetch_fn = fetch_fn
        self.detect_fn = detect_fn
        self.gap_fn = gap_fn
        self.biomass_fn = biomass_fn
        self.max_retries = max_retries
        self.min_usable_pixel_pct = min_usable_pixel_pct

    def run(self, region_name: str) -> tuple[DecisionTrail, ConfidenceResult]:
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        trail = DecisionTrail(run_id=run_id, region_name=region_name)
        trail.add_step("fetch_imagery", "ok", "Fetching Sentinel-2 L2A imagery for Date A and Date B.")

        # --- BOUNDARY #1: autonomous retry, decided by the system, not a flag ---
        attempt = 0
        qc = self.fetch_fn(region_name, attempt)
        first_attempt_pct = qc["usable_pixel_pct"]

        while qc["usable_pixel_pct"] < self.min_usable_pixel_pct and attempt < self.max_retries:
            attempt += 1
            trail.add_step(
                "quality_check", "retry",
                f"Usable-pixel % ({qc['usable_pixel_pct']:.1f}%) below {self.min_usable_pixel_pct:.0f}% "
                f"threshold — auto re-querying a different date window (attempt {attempt}/{self.max_retries}).",
                details={"usable_pct_this_attempt": qc["usable_pixel_pct"]},
                is_boundary=True,
            )
            qc = self.fetch_fn(region_name, attempt)

        if qc["usable_pixel_pct"] >= self.min_usable_pixel_pct:
            trail.add_step(
                "quality_check", "ok",
                f"Usable-pixel % {qc['usable_pixel_pct']:.1f}% ≥ {self.min_usable_pixel_pct:.0f}% threshold — proceeding.",
                details={"attempts_used": attempt + 1, "first_attempt_pct": first_attempt_pct},
            )
        else:
            trail.add_step(
                "quality_check", "warning",
                f"Usable-pixel % still {qc['usable_pixel_pct']:.1f}% after {attempt} retries — "
                f"proceeding anyway with degraded input; this will likely suppress the confidence score.",
                details={"attempts_used": attempt + 1},
            )

        trail.add_step("reproject_align", "ok", "Both dates reprojected/aligned to common CRS and grid.")

        det = self.detect_fn(region_name)
        trail.add_step(
            "run_opencanopy_model", "ok",
            f"Canopy height loss detected: {det['canopy_height_loss_m']:.1f}m.",
            details={"canopy_height_loss_m": det["canopy_height_loss_m"]},
        )
        trail.add_step("ndvi_crosscheck", "ok", f"NDVI cross-check agreement: {det['ndvi_model_agreement']*100:.0f}%.")
        trail.add_step("per_region_calibration", "ok", f"Calibration fit: {det['calibration_fit_score']:.2f}.")

        biomass = self.biomass_fn(det["canopy_height_loss_m"])
        trail.add_step(
            "biomass_carbon_estimate", "ok",
            f"Estimated carbon loss: {biomass['carbon_loss_kg_per_ha']:.1f} kg/ha.",
            details=biomass,
        )

        gap_days = self.gap_fn()
        result = compute_confidence(
            usable_pixel_pct=qc["usable_pixel_pct"],
            ndvi_model_agreement=det["ndvi_model_agreement"],
            temporal_gap_days=gap_days,
            calibration_fit_score=det["calibration_fit_score"],
        )
        factor_details = {
            f.name: f"raw={f.raw_value}, norm={f.normalized:.2f}, contrib={f.contribution:.3f} — {f.reasoning}"
            for f in result.factors
        }

        # --- BOUNDARY #2: autonomous confidence gate ---
        if result.passed:
            trail.add_step(
                "confidence_gate", "ok",
                f"Confidence {result.score:.2f} ≥ threshold {result.threshold:.2f} — alert cleared for release.",
                details=factor_details, is_boundary=True,
            )
            trail.add_step("generate_output", "ok", "GeoJSON + decision trail generated. Alert released to dashboard.")
        else:
            trail.add_step(
                "confidence_gate", "blocked",
                f"Confidence {result.score:.2f} BELOW threshold {result.threshold:.2f} — alert withheld, flagged for human review.",
                details=factor_details, is_boundary=True,
            )
            trail.add_step("generate_output", "warning", "GeoJSON + decision trail generated. Flagged for human review, no alert fired.")

        return trail, result


if __name__ == "__main__":
    orchestrator = PipelineOrchestrator()
    trail, result = orchestrator.run(region_name="Test Forest Polygon A")
    print(trail.to_markdown())
    json_path, md_path = trail.save()
    print(f"\nSaved: {json_path}\nSaved: {md_path}")