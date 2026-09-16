"""Dashboard-local helpers for validating and creating study boundaries."""
from __future__ import annotations

import math
from typing import Any


def validate_region_geojson(payload: dict[str, Any]) -> dict[str, Any]:
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
    geometry = validate_region_geojson(geometry)

    def walk(values: Any) -> list[tuple[float, float]]:
        if isinstance(values[0], (int, float)):
            return [(float(values[0]), float(values[1]))]
        return [point for value in values for point in walk(value)]

    points = walk(geometry["coordinates"])
    longitudes, latitudes = zip(*points)
    return ((min(longitudes) + max(longitudes)) / 2, (min(latitudes) + max(latitudes)) / 2)


def square_study_area(longitude: float, latitude: float, radius_km: float, name: str) -> dict[str, Any]:
    lat_offset = radius_km / 111.32
    lon_offset = radius_km / (111.32 * max(math.cos(math.radians(latitude)), 0.01))
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": name, "source": "dashboard_location_search", "radius_km": radius_km},
            "geometry": {"type": "Polygon", "coordinates": [[
                [longitude - lon_offset, latitude - lat_offset],
                [longitude + lon_offset, latitude - lat_offset],
                [longitude + lon_offset, latitude + lat_offset],
                [longitude - lon_offset, latitude + lat_offset],
                [longitude - lon_offset, latitude - lat_offset],
            ]]},
        }],
    }
