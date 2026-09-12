"""Run the Earth Engine acquisition and produce Member A's JSON handoff."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from analysis.acquisition_confidence import score
from analysis.decision_summary import build_decision_summary
from analysis.validation_hansen import validate_against_hansen
from data_acquisition.cloud_mask import mask_scl, usable_pixel_pct
from data_acquisition.earth_engine_client import init_ee, load_region
from data_acquisition.fetch_dates import candidate_scenes
from data_acquisition.quality_check import check_and_retry
from detection.ndvi_crosscheck import compute_ndvi, regional_ndvi_mean, summarise_ndvi_change
from detection.threshold_calibration import calibrate_region_baseline


def process_date(region, target_date: str, window_days: int) -> tuple[dict, object]:
    """Choose an SCL-validated scene, expanding the search only when needed."""
    search_windows = tuple(dict.fromkeys((window_days, 14, 30)))
    attempts: list[dict] = []
    seen_ids: set[str] = set()
    selected: tuple[object, object, float, dict] | None = None

    for window in search_windows:
        for scene in candidate_scenes(region, target_date, window):
            scene_id = scene.get("system:index").getInfo()
            if scene_id in seen_ids:
                continue
            seen_ids.add(scene_id)
            masked, valid = mask_scl(scene)
            usable = usable_pixel_pct(valid, region)
            quality = check_and_retry(usable)
            attempts.append({"window_days": window, "scene_id": scene_id, "usable_pixel_pct": usable, "status": quality["status"]})
            if selected is None or usable > selected[2]:
                selected = (scene, masked, usable, quality)
            if quality["status"] == "ok":
                selected = (scene, masked, usable, quality)
                break
        if selected is not None and selected[3]["status"] == "ok":
            break

    if selected is None:
        raise ValueError(f"No Sentinel-2 scenes within ±{max(search_windows)} days of {target_date}.")

    scene, masked, usable, quality = selected
    ndvi = compute_ndvi(masked)
    summary = {
        "target_date": target_date,
        "scene_id": scene.get("system:index").getInfo(),
        "usable_pixel_pct": usable,
        "quality": quality,
        "selection_attempts": attempts,
        "ndvi_mean": regional_ndvi_mean(ndvi, region),
        "calibration": calibrate_region_baseline(ndvi, region),
    }
    return summary, ndvi


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, help="Google Cloud project with Earth Engine enabled")
    parser.add_argument("--region", default="config/region.geojson")
    parser.add_argument("--before", required=True, help="YYYY-MM-DD")
    parser.add_argument("--after", required=True, help="YYYY-MM-DD")
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument(
        "--hansen-year", type=int, default=None,
        help="Optional 2001–2025 annual Hansen reference-loss comparison year.",
    )
    parser.add_argument("--output", default="outputs/member_a_handoff.json")
    args = parser.parse_args()
    init_ee(args.project)
    region = load_region(args.region)
    before, before_ndvi = process_date(region, args.before, args.window_days)
    after, after_ndvi = process_date(region, args.after, args.window_days)
    ndvi_change = summarise_ndvi_change(before_ndvi, after_ndvi, region)
    validation = None
    if args.hansen_year is not None:
        ndvi_delta = after_ndvi.subtract(before_ndvi).rename("NDVI_delta")
        validation = validate_against_hansen(ndvi_delta, region, reference_year=args.hansen_year)
    confidence = score(before["usable_pixel_pct"], after["usable_pixel_pct"], True)
    decision = build_decision_summary(before, after, ndvi_change, confidence, validation)
    handoff = {
        "schema_version": "1.3",
        "region": Path(args.region).stem,
        "before": before,
        "after": after,
        "ndvi_change": ndvi_change,
        "hansen_validation": validation,
        "confidence": confidence,
        "decision": decision,
        "model_status": "pending_open_canopy_checkpoint_validation",
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(handoff, indent=2) + "\n")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
