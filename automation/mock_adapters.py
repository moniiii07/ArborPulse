"""
mock_adapters.py

Simulated stand-ins for Member A's real modules (data_acquisition/ and
detection/). Unlike demo_run.py's old scenario-flag mocks, these introduce
realistic randomness so the orchestrator's retry logic has something genuine
to react to — the system doesn't know in advance whether a query will
succeed, just like it won't in production.

Swap these for real calls once Member A's modules exist — the orchestrator
only cares about the function signature, not the implementation.
"""

import random


def mock_fetch_and_quality_check(region_name: str, date_offset: int = 0) -> dict:
    """
    Simulates data_acquisition/quality_check.py.
    date_offset lets the orchestrator ask for a *different* date window on retry.
    Returns: {"usable_pixel_pct": float}
    Quality improves somewhat with each offset, mimicking "try a clearer day."
    """
    base = random.uniform(35, 60)
    improvement = date_offset * random.uniform(15, 25)
    usable_pct = min(98.0, base + improvement)
    return {"usable_pixel_pct": round(usable_pct, 1)}


def mock_detection_and_crosscheck(region_name: str) -> dict:
    """
    Simulates detection/opencanopy_model.py + ndvi_crosscheck.py.
    Returns: {"canopy_height_loss_m", "ndvi_model_agreement", "calibration_fit_score"}
    """
    return {
        "canopy_height_loss_m": round(random.uniform(1.0, 9.0), 1),
        "ndvi_model_agreement": round(random.uniform(0.3, 0.95), 2),
        "calibration_fit_score": round(random.uniform(0.4, 0.9), 2),
    }


def mock_temporal_gap_days() -> float:
    return float(random.randint(10, 60))


def mock_biomass_carbon(height_loss_m: float) -> dict:
    """Real formula — not mocked, since this part of the pipeline is already final."""
    agb_loss = 0.067 * (height_loss_m ** 2.58)
    carbon_loss = agb_loss * 0.47
    return {"agb_loss_kg_per_ha": round(agb_loss, 2), "carbon_loss_kg_per_ha": round(carbon_loss, 2)}