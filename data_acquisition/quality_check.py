"""Plain-language quality gates used by the pipeline and dashboard."""
from __future__ import annotations

from typing import Any


def check_and_retry(usable_pct: float, threshold: float = 60.0) -> dict[str, Any]:
    if usable_pct < threshold:
        return {
            "status": "retry",
            "usable_pixel_pct": usable_pct,
            "threshold_pct": threshold,
            "reason": f"Only {usable_pct:.1f}% of pixels are usable; minimum is {threshold:.1f}%.",
        }
    return {"status": "ok", "usable_pixel_pct": usable_pct, "threshold_pct": threshold, "reason": "Scene passed quality gate."}

