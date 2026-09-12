"""Check ArborPulse readiness before a demo, analysis run, or schedule."""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(label: str, condition: bool, detail: str = "") -> bool:
    marker = "PASS" if condition else "FAIL"
    print(f"[{marker}] {label}" + (f" — {detail}" if detail else ""))
    return condition


def main() -> None:
    parser = argparse.ArgumentParser(description="Check ArborPulse local readiness.")
    parser.add_argument("--project", help="Also initialise Earth Engine against this Cloud project.")
    parser.add_argument("--region", default="config/region.geojson")
    args = parser.parse_args()

    region = ROOT / args.region
    passed = [
        check("Project root", (ROOT / "run_pipeline.py").exists()),
        check("Dashboard", (ROOT / "dashboard/app.py").exists()),
        check("Study boundary", region.exists(), str(region.relative_to(ROOT))),
        check("Earth Engine package", importlib.util.find_spec("ee") is not None),
        check("Streamlit package", importlib.util.find_spec("streamlit") is not None),
    ]
    for directory in ("outputs", "outputs/monitoring", "outputs/reviews"):
        path = ROOT / directory
        path.mkdir(parents=True, exist_ok=True)
        passed.append(check(f"Output directory: {directory}", path.is_dir()))

    if args.project:
        try:
            from data_acquisition.earth_engine_client import init_ee

            init_ee(args.project, interactive=False)
            passed.append(check("Earth Engine connection", True, args.project))
        except Exception as error:
            passed.append(check("Earth Engine connection", False, str(error).splitlines()[0]))

    if all(passed):
        print("\nArborPulse is ready.")
    else:
        print("\nArborPulse needs attention before it is run.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
