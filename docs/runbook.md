# ArborPulse runbook

## First-time setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Earth Engine authenticates the person running the project. Do not create, download, commit, or share service-account keys for the prototype. The first interactive `run_pipeline.py` execution opens the Earth Engine authentication flow.

## Run an analysis

```bash
python run_pipeline.py \
  --project composed-arch-476417-e5 \
  --region config/region.geojson \
  --before 2025-01-15 \
  --after 2026-01-15
```

Choose same-season dates when possible. The pipeline records any seasonal mismatch in the JSON handoff and dashboard.

## Preflight check

Before a demo or scheduled run, verify local readiness:

```bash
python scripts/preflight_check.py --project composed-arch-476417-e5
```

The command checks the boundary, required Python packages, output folders, and the Earth Engine connection. It does not alter satellite data or credentials.

## Run the dashboard

```bash
streamlit run dashboard/app.py
```

## Security rules

- Keep `.env`, Earth Engine tokens, and any service-account keys out of Git.
- Treat user-uploaded study boundaries and generated review records as local data.
- Before cloud deployment, use the host's encrypted secret manager; do not add credentials to source files.
