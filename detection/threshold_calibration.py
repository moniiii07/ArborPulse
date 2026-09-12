"""Local, transparent NDVI baseline calibration."""
from __future__ import annotations

import ee


def calibrate_region_baseline(ndvi: ee.Image, region: ee.Geometry, scale: int = 20) -> dict[str, float]:
    stats = ndvi.reduceRegion(
        ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True), region, scale, maxPixels=10_000_000
    ).getInfo() or {}
    # Earth Engine returns null for a fully masked region. Preserve that state in
    # a stable schema so the quality gate—not a conversion error—controls retry.
    mean_value = stats.get("NDVI_mean")
    std_value = stats.get("NDVI_stdDev")
    mean = float(mean_value) if mean_value is not None else 0.0
    std = float(std_value) if std_value is not None else 0.0
    return {
        "ndvi_mean": round(mean, 4),
        "ndvi_stddev": round(std, 4),
        "loss_threshold": round(mean - std, 4),
        "valid": mean_value is not None and std_value is not None,
    }
