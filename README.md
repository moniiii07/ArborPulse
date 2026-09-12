# Own model

`scripts/train_loss_classifier.js` trains ArborPulse's own Random Forest forest-loss screening classifier in Google Earth Engine. It uses historical Sentinel-2 change features and Hansen 2023 labels, with a geographic hold-out evaluation. See [the model workflow](docs/own_model.md) before presenting its metrics.

## Date comparability

The pipeline records whether its before/after dates are seasonally comparable. Dates from the same month or adjacent months are marked `same_season`; other comparisons are marked `seasonal_mismatch` and visibly carry a seasonal-confounding warning in the dashboard. Use the same month in different years whenever possible.
