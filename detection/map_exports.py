"""Small, display-ready Earth Engine map exports for the ArborPulse dashboard."""
from __future__ import annotations

from pathlib import Path

import ee


def _download_thumbnail(image: ee.Image, region: ee.Geometry, destination: Path, **visualisation: object) -> str:
    """Save an authenticated, region-cropped thumbnail to a local PNG file."""
    params = {
        "region": region.getInfo(),
        "dimensions": 640,
        "format": "png",
        **visualisation,
    }
    thumbnail_id = image.getThumbId(params)["thumbid"]
    pixels = ee.data._execute_cloud_call(  # Earth Engine's authenticated Cloud API request.
        ee.data._get_cloud_projects_raw().thumbnails().getPixels(name=thumbnail_id)
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(pixels)
    return str(destination)


def dashboard_visuals(
    before_image: ee.Image, after_image: ee.Image, region: ee.Geometry, output_directory: Path
) -> dict[str, str]:
    """Save before, after, and review-mask previews for the dashboard.

    Earth Engine thumbnail endpoints require authentication, so the pipeline
    downloads small local PNG files while authenticated. The review mask is a
    screening layer, not a verdict.
    """
    delta = after_image.normalizedDifference(["B8", "B4"]).subtract(
        before_image.normalizedDifference(["B8", "B4"])
    )
    review_mask = delta.lte(-0.20).selfMask().visualize(palette=["d73027"])
    return {
        "before_true_color": _download_thumbnail(
            before_image, region, output_directory / "before_true_color.png",
            bands=["B4", "B3", "B2"], min=0, max=3000,
        ),
        "after_true_color": _download_thumbnail(
            after_image, region, output_directory / "after_true_color.png",
            bands=["B4", "B3", "B2"], min=0, max=3000,
        ),
        "ndvi_review_mask": _download_thumbnail(
            review_mask, region, output_directory / "ndvi_review_mask.png"
        ),
        "note": "Red pixels meet the NDVI vegetation-decline review rule; they are not confirmed deforestation.",
    }
