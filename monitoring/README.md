# Scheduled monitoring

`run_monitor.py` creates one same-season comparison: the requested monitoring date against the date 365 days earlier. It writes a dated JSON handoff to `outputs/monitoring/`.

Run it manually first:

```bash
python monitoring/run_monitor.py --project composed-arch-476417-e5 --date 2026-01-15
```

For a weekly Mac schedule, create a scheduled job that runs the same command after the project virtual environment is configured. Run it manually once after any dependency or Earth Engine credential change. The runner does not send notifications or commit secrets; a later notification layer should alert only for `review_required` results.
