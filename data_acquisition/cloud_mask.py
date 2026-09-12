"""Sentinel-2 Scene Classification Layer (SCL) masking."""
from __future__ import annotations

import ee

# SCL classes rejected: saturated/defective, cloud shadow, medium/high cloud, cirrus.
REJECTED_SCL = (1, 3, 8, 9, 10)


def scl_valid_mask(image: ee.Image) -> ee.Image:
    scl = image.select("SCL")
    invalid = scl.eq(REJECTED_SCL[0])
    for scl_class in REJECTED_SCL[1:]:
        invalid = invalid.Or(scl.eq(scl_class))
    return invalid.Not().rename("valid_scl")


def mask_scl(image: ee.Image) -> tuple[ee.Image, ee.Image]:
    """Mask cloud/shadow pixels and return (masked_image, binary_valid_mask)."""
    valid = scl_valid_mask(image)
    return image.updateMask(valid), valid


def usable_pixel_pct(valid_mask: ee.Image, region: ee.Geometry, scale: int = 20) -> float:
    """Calculate percentage of usable SCL pixels over the area of interest."""
    value = valid_mask.reduceRegion(
        reducer=ee.Reducer.mean(), geometry=region, scale=scale, maxPixels=10_000_000
    ).get("valid_scl").getInfo()
    return round(100 * float(value or 0), 2)

