# Own model

`scripts/train_loss_classifier.js` trains ArborPulse's own Random Forest forest-loss screening classifier in Google Earth Engine. It uses historical Sentinel-2 change features and Hansen 2023 labels, with a geographic hold-out evaluation. See [the model workflow](docs/own_model.md) before presenting its metrics.

## Date comparability

The pipeline records whether its before/after dates are seasonally comparable. Dates from the same month or adjacent months are marked `same_season`; other comparisons are marked `seasonal_mismatch` and visibly carry a seasonal-confounding warning in the dashboard. Use the same month in different years whenever possible.

## Custom study areas

Upload one Polygon or MultiPolygon GeoJSON through the dashboard. ArborPulse validates it and saves it locally as `config/user_region.geojson`; rerun the pipeline with `--region config/user_region.geojson` and your chosen dates. The uploaded boundary is local and intentionally excluded from Git.

## Scheduled monitoring

Use `monitoring/run_monitor.py` to create a dated, same-season monitoring handoff. It compares a monitoring date against the date 365 days earlier and is designed for a weekly scheduler after local testing. See [scheduled monitoring](monitoring/README.md).

## Human review feedback

After inspecting a review queue, a user can record an outcome in the dashboard: confirmed forest loss, seasonal change, fire/burn scar, agriculture/harvest, false alarm, or needs more evidence. Reviews are saved locally in `outputs/reviews/reviews.jsonl` and are not committed to Git.

## Visual validation

The dashboard links reviewers to satellite imagery centred on the active study boundary. This is a human-review aid only: imagery recency and resolution vary, so the reviewer must confirm that it is suitable before assigning an outcome.
