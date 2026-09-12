"""Earth Engine authentication and Sentinel-2 surface-reflectance access."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import ee

S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"


def init_ee(project_id: str | None = None, *, interactive: bool = True) -> None:
    """Initialise Earth Engine; authenticate in a browser when needed."""
    try:
        ee.Initialize(project=project_id)
    except Exception as error:
        if not interactive:
            raise RuntimeError("Earth Engine is not authenticated. Run authenticate first.") from error
        ee.Authenticate()
        ee.Initialize(project=project_id)


def load_region(path: str | Path) -> ee.Geometry:
    """Load a Polygon, MultiPolygon, Feature, or single-feature collection."""
    payload: dict[str, Any] = json.loads(Path(path).read_text())
    kind = payload.get("type")
    if kind == "FeatureCollection":
        features = payload.get("features", [])
        if len(features) != 1:
            raise ValueError("Region GeoJSON must contain exactly one feature.")
        return ee.Geometry(features[0]["geometry"])
    if kind == "Feature":
        return ee.Geometry(payload["geometry"])
    return ee.Geometry(payload)


def get_sentinel2_collection(region: ee.Geometry, start_date: str, end_date: str) -> ee.ImageCollection:
    """Return Sentinel-2 L2A imagery covering a region and date interval."""
    return (
        ee.ImageCollection(S2_COLLECTION)
        .filterBounds(region)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", 90))
    )

