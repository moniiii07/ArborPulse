# Canopy-height model decision

## Decision

ArborPulse will **not** run the Open-Canopy checkpoint in the current Rondônia Sentinel-2 workflow.

## Why

Open-Canopy is a benchmark for very-high-resolution (1.5 m) canopy-height and change estimation over France, using SPOT 6/7 imagery and aerial-LiDAR supervision. ArborPulse uses 10 m Sentinel-2 L2A imagery over Amazonian tropical forest. Reusing its checkpoint would cross imagery type, spatial-resolution, geography, and forest-domain boundaries without validation.

## Consequence for the demo

- The app reports NDVI-based vegetation-change screening, cloud-quality evidence, and Hansen annual-loss corroboration.
- It does **not** report canopy-height loss, biomass loss, carbon loss, or a final deforestation verdict.
- The JSON handoff retains `model_status: pending_open_canopy_checkpoint_validation` to make this explicit to the dashboard.

## Future path

Select a canopy-height model trained and evaluated for global/tropical Sentinel-2 data, verify its bands, temporal inputs, normalisation, uncertainty outputs, and licence, then validate it against an independent reference before enabling biomass estimates.

## Sources

- Open-Canopy official repository: <https://github.com/fajwel/open-canopy>
- AI4Forest Global Canopy Height Map repository: <https://github.com/AI4Forest/Global-Canopy-Height-Map>
