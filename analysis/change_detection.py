"""Canopy-height and NDVI change calculations."""
from __future__ import annotations

import numpy as np


def canopy_height_loss(height_before: np.ndarray, height_after: np.ndarray) -> np.ndarray:
    """Positive values indicate canopy-height loss."""
    return np.asarray(height_before, dtype=float) - np.asarray(height_after, dtype=float)


def summarise_loss(loss: np.ndarray, threshold_m: float = 2.0) -> dict[str, float]:
    values = np.asarray(loss, dtype=float)
    changed = values >= threshold_m
    return {"mean_height_loss_m": round(float(np.nanmean(values)), 3), "loss_pixel_pct": round(float(np.nanmean(changed) * 100), 2)}

