"""
demo_run.py

Runs the Member B pipeline slice (confidence scoring + decision trail) end to
end using MOCKED outputs from Member A's data_acquisition/ and detection/
modules. This lets Member B's logic be built, tested, and demoed before those
modules exist, and swapped for real data later with zero changes to the logic
below — only the mock_* function calls at the top of main() need replacing.

Run: python demo_run.py [--scenario pass|retry|blocked]

run_pipeline() is also the entry point the Streamlit dashboard (dashboard/app.py)
calls, so the CLI demo and the UI always execute the identical code path.
"""

import argparse
import uuid
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from analysis.confidence_score import compute_confidence, DEFAULT_CONFIDENCE_THRESHOLD
from reasoning_log.decision_trail import DecisionTrail


# ---------------------------------------------------------------------------
# MOCK UPSTREAM DATA — replace these with real calls into
# data_acquisition/ and detection/ once Member A's modules are ready.
# Expected contract is documented in each mock function's docstring.
# ---------------------------------------------------------------------------

def mock_fetch_and_quality_check(scenario: str) -> dict:
    """
    Contract expected from data_acquisition/quality_check.py:
      { "usable_pixel_pct": float, "retried": bool,
        "initial_usable_pct": float | None }
    """
    if scenario == "retry":
        return {"usable_pixel_pct": 88.4, "retried": True, "initial_usable_pct": 39.1}
    if scenario == "blocked":
        return {"usable_pixel_pct": 63.0, "retried": False, "initial_usable_pct": None}
    return {"usable_pixel_pct": 91.2, "retried": False, "initial_usable_pct": None}


def mock_detection_and_crosscheck(scenario: str) -> dict:
    """
    Contract expected from detection/opencanopy_model.py + ndvi_crosscheck.py:
      { "canopy_height_loss_m": float, "ndvi_model_agreement": float,
        "calibration_fit_score": float }
    """
    if scenario == "blocked":
        return {"canopy_height_loss_m": 4.2, "ndvi_model_agreement": 0.38, "calibration_fit_score": 0.41}
    return {"canopy_height_loss_m": 6.7, "ndvi_model_agreement": 0.83, "calibration_fit_score": 0.77}


def mock_temporal_gap_days() -> float:
    return 24.0


def mock_biomass_carbon(height_loss_m: float) -> dict:
    """Contract expected from analysis/biomass_estimate.py."""
    agb_loss = 0.067 * (height_loss_m ** 2.58)
    carbon_loss = agb_loss * 0.47
    return {"agb_loss_kg_per_ha": round(agb_loss, 2), "carbon_loss_kg_per_ha": round(carbon_loss, 2)}


# ---------------------------------------------------------------------------

def run_pipeline(
    scenario: str,
    region_name: str = "Test Forest Polygon A",
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
):
    """Execute the full mocked pipeline and return (DecisionTrail, ConfidenceResult).

    Shared by the CLI demo below and the Streamlit dashboard, so both surfaces
    exercise the same logic and produce the same audit artifacts.
    """
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    trail = DecisionTrail(run_id=run_id, region_name=region_name)

    trail.add_step("fetch_imagery", "ok", "Fetched Sentinel-2 L2A imagery for Date A and Date B (Google Earth Engine).")

    qc = mock_fetch_and_quality_check(scenario)
    if qc["retried"]:
        trail.add_step(
            "quality_check", "retry",
            f"Initial usable-pixel % ({qc['initial_usable_pct']:.1f}%) below threshold — auto re-queried a different date window.",
            details={"initial_usable_pct": qc["initial_usable_pct"], "resolved_usable_pct": qc["usable_pixel_pct"]},
            is_boundary=True,
        )
    else:
        trail.add_step("quality_check", "ok", f"Usable-pixel % {qc['usable_pixel_pct']:.1f}% — no retry needed.")

    trail.add_step("reproject_align", "ok", "Both dates reprojected/aligned to common CRS and grid.")

    det = mock_detection_and_crosscheck(scenario)
    trail.add_step(
        "run_opencanopy_model", "ok",
        f"Canopy height loss detected: {det['canopy_height_loss_m']:.1f}m.",
        details={"canopy_height_loss_m": det["canopy_height_loss_m"]},
    )
    trail.add_step(
        "ndvi_crosscheck", "ok",
        f"NDVI cross-check agreement with model: {det['ndvi_model_agreement']*100:.0f}%.",
    )
    trail.add_step(
        "per_region_calibration", "ok",
        f"Per-region NDVI baseline calibration fit: {det['calibration_fit_score']:.2f}.",
    )

    biomass = mock_biomass_carbon(det["canopy_height_loss_m"])
    trail.add_step(
        "biomass_carbon_estimate", "ok",
        f"Estimated carbon loss: {biomass['carbon_loss_kg_per_ha']:.1f} kg/ha "
        f"(AGB loss {biomass['agb_loss_kg_per_ha']:.1f} kg/ha, general allometric formula).",
        details=biomass,
    )

    gap_days = mock_temporal_gap_days()
    result = compute_confidence(
        usable_pixel_pct=qc["usable_pixel_pct"],
        ndvi_model_agreement=det["ndvi_model_agreement"],
        temporal_gap_days=gap_days,
        calibration_fit_score=det["calibration_fit_score"],
        threshold=threshold,
    )

    factor_details = {f.name: f"raw={f.raw_value}, norm={f.normalized:.2f}, contrib={f.contribution:.3f} — {f.reasoning}" for f in result.factors}

    if result.passed:
        trail.add_step(
            "confidence_gate", "ok",
            f"Confidence {result.score:.3f} ≥ threshold {result.threshold:.3f} — alert cleared for release.",
            details=factor_details, is_boundary=True,
        )
        trail.add_step("generate_output", "ok", "GeoJSON + decision trail generated. Alert released to dashboard.")
    else:
        trail.add_step(
            "confidence_gate", "blocked",
            f"Confidence {result.score:.3f} BELOW threshold {result.threshold:.3f} — alert withheld, flagged for human review.",
            details=factor_details, is_boundary=True,
        )
        trail.add_step("generate_output", "warning", "GeoJSON + decision trail generated. Flagged for human review, no alert fired.")

    return trail, result


def main(scenario: str):
    trail, _result = run_pipeline(scenario)
    json_path, md_path = trail.save()
    print(trail.to_markdown())
    print(f"\nSaved: {json_path}\nSaved: {md_path}")


if __name__ == "__main__":
    # Windows consoles default to a legacy code page (e.g. cp1252) that cannot
    # encode the trail's status icons (✅ 🔁 🛑) — force UTF-8 output.
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=["pass", "retry", "blocked"], default="pass")
    args = parser.parse_args()
    main(args.scenario)
