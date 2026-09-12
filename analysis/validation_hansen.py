"""Independent, annual reference check using Hansen Global Forest Change.

Hansen loss is a Landsat-derived *stand-replacement tree-cover loss* product,
not ground truth or a same-day deforestation label. ArborPulse uses it only as
an explanatory corroboration metric for a reviewed NDVI-change signal.
"""
from __future__ import annotations

import ee

HANSEN_DATASET = "UMD/hansen/global_forest_change_2025_v1_13"


def validate_against_hansen(
    ndvi_delta: ee.Image,
    region: ee.Geometry,
    *,
    reference_year: int,
    loss_threshold: float = -0.20,
    scale: int = 30,
) -> dict[str, float | int | str]:
    """Compare NDVI review pixels to Hansen loss attributed to one calendar year.

    `reference_year` must be from 2001 through 2025, the coverage of the
    current v1.13 catalog image. The comparison is made only where the NDVI
    delta is valid, avoiding an apparent disagreement caused by cloud masking.
    """
    if not 2001 <= reference_year <= 2025:
        raise ValueError("Hansen v1.13 supports reference years from 2001 through 2025.")

    ndvi_review = ndvi_delta.lte(loss_threshold).rename("ndvi_review")
    loss_year_code = reference_year - 2000
    hansen_loss = (
        ee.Image(HANSEN_DATASET)
        .select("lossyear")
        .eq(loss_year_code)
        .updateMask(ndvi_delta.mask())
        .rename("hansen_loss")
    )
    overlap = ndvi_review.And(hansen_loss).rename("overlap")

    reduction = ee.Image.cat([ndvi_review, hansen_loss, overlap]).reduceRegion(
        reducer=ee.Reducer.mean(), geometry=region, scale=scale, maxPixels=10_000_000
    ).getInfo() or {}
    review_fraction = float(reduction.get("ndvi_review") or 0)
    reference_fraction = float(reduction.get("hansen_loss") or 0)
    overlap_fraction = float(reduction.get("overlap") or 0)
    return {
        "reference_dataset": "Hansen Global Forest Change v1.13",
        "reference_year": reference_year,
        "reference_loss_pixel_pct": round(100 * reference_fraction, 2),
        "ndvi_review_pixel_pct_at_30m": round(100 * review_fraction, 2),
        "overlap_pixel_pct": round(100 * overlap_fraction, 2),
        "ndvi_review_overlap_pct": round(100 * overlap_fraction / review_fraction, 2) if review_fraction else 0.0,
        "interpretation": "Annual reference corroboration only; not ground-truth validation or a deforestation verdict.",
    }
