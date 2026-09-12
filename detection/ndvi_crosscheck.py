"""Vegetation-index checks calculated in Earth Engine."""
from __future__ import annotations

import ee


def compute_ndvi(image: ee.Image) -> ee.Image:
    return image.normalizedDifference(["B8", "B4"]).rename("NDVI")


def regional_ndvi_mean(ndvi: ee.Image, region: ee.Geometry, scale: int = 10) -> float:
    value = ndvi.reduceRegion(ee.Reducer.mean(), region, scale, maxPixels=10_000_000).get("NDVI").getInfo()
    return round(float(value or 0), 4)


def summarise_ndvi_change(
    before: ee.Image, after: ee.Image, region: ee.Geometry, *, loss_threshold: float = -0.20, scale: int = 20
) -> dict[str, float | str]:
    """Summarise post-minus-pre NDVI; a negative delta indicates vegetation decline.

    The threshold is a transparent screening rule for the demo, not a final
    deforestation classifier. It should be calibrated and visually validated per
    target region before making operational claims.
    """
    delta = after.subtract(before).rename("NDVI_delta")
    change_mask = delta.lte(loss_threshold).rename("ndvi_loss")
    mean_delta = delta.reduceRegion(
        ee.Reducer.mean(), region, scale, maxPixels=10_000_000
    ).get("NDVI_delta").getInfo()
    loss_pct = change_mask.reduceRegion(
        ee.Reducer.mean(), region, scale, maxPixels=10_000_000
    ).get("ndvi_loss").getInfo()
    return {
        "definition": "after_ndvi_minus_before_ndvi",
        "mean_delta": round(float(mean_delta or 0), 4),
        "loss_threshold": loss_threshold,
        "loss_pixel_pct": round(100 * float(loss_pct or 0), 2),
    }
