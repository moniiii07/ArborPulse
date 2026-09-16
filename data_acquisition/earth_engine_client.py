"""Earth Engine authentication and Sentinel-2 surface-reflectance access."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import ee

S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"


def init_ee(project_id: str | None = None, *, interactive: bool = True) -> None:
    """Initialise Earth Engine; authenticate in a browser when needed."""
    try:
        service_account = os.environ.get("EE_SERVICE_ACCOUNT")
        private_key = os.environ.get("EE_PRIVATE_KEY")
        if service_account and private_key:
            credentials = ee.ServiceAccountCredentials(
                service_account,
                key_data=private_key.replace("\\n", "\n"),
            )
            ee.Initialize(credentials=credentials, project=project_id)
        else:
            ee.Initialize(project=project_id)
    except Exception as error:
        if not interactive:
            raise RuntimeError("Earth Engine is not authenticated. Run authenticate first.") from error
        if os.environ.get("ARBORPULSE_CLOUD_RUN"):
            raise RuntimeError(
                "Earth Engine credentials are missing in this deployment. "
                "Add EE_SERVICE_ACCOUNT and EE_PRIVATE_KEY to Streamlit Secrets."
            ) from error
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
