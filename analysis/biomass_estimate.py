"""Transparent allometric biomass and carbon estimates."""
from __future__ import annotations

import numpy as np

COEFFS = {"general": (0.067, 2.58), "conifer": (0.118, 2.53), "broadleaf": (0.052, 2.69), "mixed": (0.067, 2.58)}
CARBON_FRACTION = 0.47


def agb(height_m: np.ndarray | float, forest_type: str = "general") -> np.ndarray:
    if forest_type not in COEFFS:
        raise ValueError(f"Unknown forest type: {forest_type}. Choose from {sorted(COEFFS)}.")
    a, b = COEFFS[forest_type]
    height = np.maximum(np.asarray(height_m, dtype=float), 0)
    return a * height**b


def carbon_from_agb(agb_value: np.ndarray | float) -> np.ndarray:
    return np.asarray(agb_value, dtype=float) * CARBON_FRACTION

