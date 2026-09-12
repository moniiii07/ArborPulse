"""Safe adapter point for canopy-height inference.

Open-Canopy is a France-focused 1.5 m SPOT 6/7 + aerial-LiDAR benchmark. It is
not a drop-in model for 10 m Sentinel-2 imagery over Amazonia, so this module
deliberately fails closed rather than generating unvalidated height estimates.
"""
from __future__ import annotations


class OpenCanopyNotConfigured(RuntimeError):
    pass


def predict_canopy_height(*_args, **_kwargs):
    raise OpenCanopyNotConfigured(
        "Open-Canopy is not compatible with ArborPulse's Sentinel-2 Amazon workflow. "
        "Do not derive canopy height or biomass until a validated compatible model is selected."
    )
