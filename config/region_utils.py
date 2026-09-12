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


def geometry_center(geometry: dict[str, Any]) -> tuple[float, float]:
    """Return a simple longitude/latitude bounding-box centre for a geometry."""
    geometry = validate_region_geojson(geometry)

    def walk(values: Any) -> list[tuple[float, float]]:
        if not values:
            return []
        if isinstance(values[0], (int, float)):
            return [(float(values[0]), float(values[1]))]
        points: list[tuple[float, float]] = []
        for value in values:
            points.extend(walk(value))
        return points

    points = walk(geometry["coordinates"])
    longitudes, latitudes = zip(*points)
    return ((min(longitudes) + max(longitudes)) / 2, (min(latitudes) + max(latitudes)) / 2)
