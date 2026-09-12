"""Create one scheduled, same-season ArborPulse monitoring run."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an ArborPulse same-season monitoring comparison.")
    parser.add_argument("--project", required=True, help="Earth Engine-enabled Google Cloud project ID")
    parser.add_argument("--region", default="config/region.geojson", help="Polygon/MultiPolygon GeoJSON path")
    parser.add_argument("--date", default=date.today().isoformat(), help="Monitoring date in YYYY-MM-DD format")
    parser.add_argument("--lookback-days", type=int, default=365, help="Reference-date gap; default preserves season")
    parser.add_argument("--window-days", type=int, default=14, help="Initial Sentinel-2 search window")
    args = parser.parse_args()

    after = date.fromisoformat(args.date)
    before = after - timedelta(days=args.lookback_days)
    root = Path(__file__).resolve().parents[1]
    output = root / "outputs/monitoring" / f"handoff_{after.isoformat()}.json"
    output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        str(root / "run_pipeline.py"),
        "--project", args.project,
        "--region", args.region,
        "--before", before.isoformat(),
        "--after", after.isoformat(),
        "--window-days", str(args.window_days),
        "--output", str(output),
    ]
    # Hansen's current catalog covers through 2025; omit the comparison for
    # later runs rather than attaching an invalid annual reference year.
    if after.year <= 2025:
        command.extend(["--hansen-year", str(after.year)])
    subprocess.run(command, check=True, cwd=root)
    print(f"Monitoring handoff written to {output}")


if __name__ == "__main__":
    main()
