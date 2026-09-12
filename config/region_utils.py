"""Validation helpers for user-provided ArborPulse study boundaries."""
from __future__ import annotations

from typing import Any


def validate_region_geojson(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a single Polygon/MultiPolygon boundary and return its geometry."""
    kind = payload.get("type")
    if kind == "FeatureCollection":
        features = payload.get("features", [])
        if len(features) != 1:
            raise ValueError("Upload one study-area feature at a time.")
        geometry = features[0].get("geometry")
    elif kind == "Feature":
        geometry = payload.get("geometry")
    else:
        geometry = payload

    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("The uploaded GeoJSON must contain one Polygon or MultiPolygon.")
    if not geometry.get("coordinates"):
        raise ValueError("The study-area geometry has no coordinates.")
    return geometry
