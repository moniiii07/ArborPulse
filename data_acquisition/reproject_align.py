"""Pixel-grid alignment for two Earth Engine images."""
from __future__ import annotations

import ee


def align_to_reference(image: ee.Image, reference: ee.Image, scale: int = 10) -> ee.Image:
    """Align to the reference projection before exporting or comparing rasters."""
    projection = reference.select("B8").projection()
    return image.resample("bilinear").reproject(crs=projection, scale=scale)

