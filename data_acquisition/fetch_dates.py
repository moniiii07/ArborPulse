"""Select least-cloudy Sentinel-2 scenes in resilient date windows."""
from __future__ import annotations

from datetime import date, timedelta

import ee

from .earth_engine_client import get_sentinel2_collection


def select_best_scene(region: ee.Geometry, target_date: str, window_days: int = 7) -> ee.Image:
    target = date.fromisoformat(target_date)
    start = (target - timedelta(days=window_days)).isoformat()
    end = (target + timedelta(days=window_days + 1)).isoformat()
    collection = get_sentinel2_collection(region, start, end).sort("CLOUDY_PIXEL_PERCENTAGE")
    if collection.size().getInfo() == 0:
        raise ValueError(f"No Sentinel-2 scenes within ±{window_days} days of {target_date}.")
    return ee.Image(collection.first()).set({"target_date": target_date, "window_days": window_days})


def candidate_scenes(
    region: ee.Geometry, target_date: str, window_days: int = 7, max_candidates: int = 5
) -> list[ee.Image]:
    """Return a small set of least-cloudy metadata candidates for SCL QA.

    Tile-level cloud metadata is only a coarse filter. ArborPulse evaluates the
    Scene Classification Layer over its actual study boundary before selecting
    a scene, so a scene with a slightly higher metadata cloud score can win.
    """
    target = date.fromisoformat(target_date)
    start = (target - timedelta(days=window_days)).isoformat()
    end = (target + timedelta(days=window_days + 1)).isoformat()
    collection = get_sentinel2_collection(region, start, end).sort("CLOUDY_PIXEL_PERCENTAGE")
    count = min(int(collection.size().getInfo()), max_candidates)
    if count == 0:
        return []
    images = collection.toList(count)
    return [ee.Image(images.get(index)).set({"target_date": target_date, "window_days": window_days}) for index in range(count)]
