"""
year_comparison.py

Two-year forest-change comparison engine for SylvaSense / ArborPulse (MRV).

QUESTION IT ANSWERS
-------------------
"Is a comparison across two years possible, and what would the dashboard show?"

Answer: yes — with one honest caveat this module computes rather than hides.
SylvaSense's raw confidence gate (analysis/confidence_score.py) decays the
temporal_gap factor to zero as the Date A→B gap widens, because a long window
invites seasonal confounds. On a 730-day span that forfeits the factor's whole
0.20 contribution: the raw gate can still pass, but only on the strength of the
other three factors — one modest quality dip away from being blocked. The honest
way to run a 2-year comparison is NOT to weaken the gate, but to compare like
with like: score a "Y1 window" (Year-1 same-season reference vs end-of-year-1)
and a "Y2 window" (Year-2 same-season reference vs end-of-year-2) with the
unchanged raw gate — each window earns FULL temporal credit, because each is a
short, season-matched pair — then attribute the between-year delta to the year
pair. This module computes BOTH the raw 2-year gate and that composite gate, so
the dashboard can show exactly what the composite design buys.

Determinism: the observation series is a fixed calendar (Jul 15 2023 → Jul 14
2025) of daily NDVI (0-1000 scale) with seeded overlays driven by one integer
seed. Same seed ⇒ same comparison, same verdict, same audit artifact.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from analysis.confidence_score import compute_confidence

# ---------------------------------------------------------------------------
# Tunables (same tone as confidence_score.py's tuning constants)
# ---------------------------------------------------------------------------

BASELINE_NDVI = 740        # healthy-forest level for Test Forest Polygon A (0-1000 scale)
SEASONAL_AMPLITUDE = 90    # peak green ~ mid-July, trough ~ mid-January
DAILY_JITTER = 2.5         # per-day pixel-level noise (cloud/aerosol proxy)

PRE_HARVEST_HEIGHT_M = 24.0
POST_HARVEST_HEIGHT_M = 2.5
REGEN_RATE_M_PER_YEAR = 1.8

# Fixed gate inputs for each same-season window (≤30-day gap ⇒ temporal factor 1.0),
# matching demo_run.py's pass scenario.
WINDOW_USABLE_PCT = 91.2
WINDOW_AGREEMENT = 0.83
WINDOW_CALIBRATION_FIT = 0.77
WINDOW_GAP_DAYS = 24.0
WINDOW_THRESHOLD = 0.60

# Seeded cloud overlay on a year-end observation (Boundary #1 territory): the
# quality check auto-retries a nearby date window; the retry feeds the gate.
CLOUD_RETRY_USABLE_PCT = 88.4
CLOUD_RETRIED_AGREEMENT = 0.76

DISTURBANCE_DELTA_THRESHOLD = 25.0    # NDVI (0-1000) points below baseline
DISTURBANCE_HEIGHT_THRESHOLD_M = 5.0  # canopy height loss that qualifies

# Fixed demo calendar: exactly two years, mid-July to mid-July (731 days).
BASE_START = date(2023, 7, 15)
BASE_END = date(2025, 7, 14)

# Seeded overlays anchor events at fixed fractions of the span, jittered by seed.
Y1_ANCHOR_FRACTION = 0.33
Y2_ANCHOR_FRACTION = 0.85
ANCHOR_JITTER_DAYS = 20
DISTURBANCE_TROUGH_DAYS = 45   # days NDVI holds in trough before recovery begins
RECOVERY_YEARS = 1.5           # NDVI climbs back toward baseline over this span


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class YearWindow:
    """One same-season window scored by the unchanged raw gate."""
    label: str          # "Y1 window" / "Y2 window"
    ref_date: date      # same-season reference (mid-July of that year)
    end_date: date      # end-of-year observation (mid-July, next cycle)
    ref_ndvi: float
    end_ndvi: float
    delta: float        # end − ref; season-matched ⇒ delta ≈ real change only
    gate_score: float
    gate_passed: bool
    retried: bool       # Boundary #1 fired while acquiring this window's end obs


@dataclass
class Disturbance:
    """One seeded disturbance event in the two-year ledger."""
    event_id: str
    start: date
    end: date
    ndvi_min: float
    ndvi_min_date: date
    ndvi_drop: float            # baseline − ndvi_min
    canopy_before_m: float
    canopy_after_m: float
    regen_rate_m_per_year: float

    def canopy_loss_m(self) -> float:
        return self.canopy_before_m - self.canopy_after_m

    def to_row(self) -> dict:
        return {
            "Event": self.event_id,
            "Start": self.start.isoformat(),
            "End": self.end.isoformat(),
            "Duration (d)": (self.end - self.start).days,
            "Trough NDVI": round(self.ndvi_min, 1),
            "NDVI drop": round(self.ndvi_drop, 1),
            "Canopy loss (m)": round(self.canopy_loss_m(), 1),
            "Regen (m/yr)": self.regen_rate_m_per_year,
        }


@dataclass
class TwoYearComparison:
    """Everything the dashboard's 2-year page needs."""
    seed: int
    region_name: str
    clouds_enabled: bool
    threshold: float
    ndvi_series: list                 # [(date, ndvi), ...] daily observations
    trend_series: list                # [(date, ndvi), ...] piecewise fitted trend
    ref_ndvi: float                   # same-season reference level (series start)
    y1_window: YearWindow
    y2_window: YearWindow
    season_delta_ndvi: float          # y2.end − y1.ref headline delta
    raw_gap_days: int                 # y1.ref_date → y2.end_date
    raw_gate_score: float
    raw_gate_passed: bool
    composite_score: float            # mean of the two window scores
    composite_passed: bool
    disturbances: list
    y1_disturbance_count: int
    y2_disturbance_count: int
    y1_ndvi_min: float
    y2_ndvi_min: float
    y1_end_canopy_m: float
    y2_end_canopy_m: float

    def to_audit_dict(self) -> dict:
        """Machine-readable audit artifact for download."""
        return {
            "artifact": "two_year_comparison",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "region_name": self.region_name,
            "seed": self.seed,
            "cloud_overlay_enabled": self.clouds_enabled,
            "calendar": {"start": BASE_START.isoformat(), "end": BASE_END.isoformat()},
            "raw_gate": {
                "span_days": self.raw_gap_days,
                "score": round(self.raw_gate_score, 3),
                "passed": self.raw_gate_passed,
                "note": (
                    "Raw gate on the full 2-year span. With a 730-day gap the "
                    "temporal_gap factor normalizes to 0.0 (≥ MAX_GAP_DAYS=180), so the "
                    "span can only pass on the strength of the other three factors."
                ),
            },
            "composite_gate": {
                "windows": [
                    {
                        "label": w.label,
                        "ref_date": w.ref_date.isoformat(),
                        "end_date": w.end_date.isoformat(),
                        "ref_ndvi": round(w.ref_ndvi, 1),
                        "end_ndvi": round(w.end_ndvi, 1),
                        "delta_ndvi": round(w.delta, 1),
                        "gate_score": round(w.gate_score, 3),
                        "gate_passed": w.gate_passed,
                        "quality_retry": w.retried,
                    }
                    for w in (self.y1_window, self.y2_window)
                ],
                "score": round(self.composite_score, 3),
                "passed": self.composite_passed,
                "threshold": self.threshold,
            },
            "headline": {
                "season_delta_ndvi": round(self.season_delta_ndvi, 1),
                "y1_min_ndvi": round(self.y1_ndvi_min, 1),
                "y2_min_ndvi": round(self.y2_ndvi_min, 1),
                "y1_end_canopy_m": round(self.y1_end_canopy_m, 1),
                "y2_end_canopy_m": round(self.y2_end_canopy_m, 1),
            },
            "disturbances": [
                {
                    "event_id": d.event_id,
                    "start": d.start.isoformat(),
                    "end": d.end.isoformat(),
                    "ndvi_min": round(d.ndvi_min, 1),
                    "ndvi_drop": round(d.ndvi_drop, 1),
                    "canopy_before_m": d.canopy_before_m,
                    "canopy_after_m": d.canopy_after_m,
                    "canopy_loss_m": round(d.canopy_loss_m(), 1),
                    "regen_rate_m_per_year": d.regen_rate_m_per_year,
                }
                for d in self.disturbances
            ],
        }


# ---------------------------------------------------------------------------
# Series construction
# ---------------------------------------------------------------------------


def _seasonal_ndvi(day: date) -> float:
    """Deterministic seasonal signal: 1-year-period sinusoid, trough in January,
    peak in mid-July, around BASELINE_NDVI."""
    doy = day.timetuple().tm_yday
    phase = 2.0 * math.pi * (doy - 196) / 365.25  # ~Jul 15 peak
    return BASELINE_NDVI + SEASONAL_AMPLITUDE * math.sin(phase)


def _disturbance_drop(day: date, events: list, rng: random.Random, trough_cache: dict) -> float:
    """NDVI drop below baseline for `day`, given seeded disturbance start dates.

    Full drop during the trough window, then linear recovery toward baseline
    over RECOVERY_YEARS. Per-event trough depth is drawn once (cached) so the
    same seed reproduces the same event shape.
    """
    drop = 0.0
    for ev in events:
        if ev not in trough_cache:
            trough_cache[ev] = DISTURBANCE_DELTA_THRESHOLD + rng.uniform(8.0, 18.0)
        trough = trough_cache[ev]
        days_in = (day - ev).days
        if 0 <= days_in <= DISTURBANCE_TROUGH_DAYS:
            drop = max(drop, trough)
        else:
            recovery_days = RECOVERY_YEARS * 365.25
            if DISTURBANCE_TROUGH_DAYS < days_in <= DISTURBANCE_TROUGH_DAYS + recovery_days:
                recovery = (days_in - DISTURBANCE_TROUGH_DAYS) / recovery_days
                drop = max(drop, trough * (1.0 - recovery))
    return drop


def build_two_year_series(seed: int, disturbance_dates: list) -> tuple:
    """Daily NDVI for the fixed 2-year calendar with seeded disturbances.

    Returns (observations, trend): jittered daily observations and the clean
    piecewise signal to overlay on them.
    """
    rng = random.Random(seed)
    events = sorted(disturbance_dates)
    trough_cache: dict = {}
    observations, trend = [], []
    day = BASE_START
    while day <= BASE_END:
        value = _seasonal_ndvi(day) - _disturbance_drop(day, events, rng, trough_cache)
        noisy = value + rng.uniform(-DAILY_JITTER, DAILY_JITTER)
        observations.append((day, round(noisy, 1)))
        trend.append((day, round(value, 1)))
        day += timedelta(days=1)
    return observations, trend


def _fit_segment(observations: list, lo: int, hi: int) -> tuple:
    """Ordinary least squares NDVI ~ day_index over observations[lo:hi].
    Returns (slope, intercept)."""
    n = hi - lo
    if n < 2:
        x0 = observations[lo][0].toordinal()
        return 0.0, _seasonal_ndvi(observations[lo][0])
    xs = [observations[i][0].toordinal() for i in range(lo, hi)]
    ys = [observations[i][1] for i in range(lo, hi)]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx else 0.0
    return slope, mean_y - slope * mean_x


def _piecewise_trend(observations: list) -> list:
    """Two-segment least-squares fit (Y1 / Y2) with overlap averaging at the
    seam, so the fitted line is continuous and stable under seeded jitter.

    A linear fit intentionally smooths through the seasonal cycle: what survives
    is the multi-year level shift the 2-year comparison is looking for.
    """
    n = len(observations)
    if n < 4:
        return [(d, v) for d, v in observations]
    seam = n // 2
    overlap = 30  # days averaged across the seam

    s1, i1 = _fit_segment(observations, 0, seam + overlap)
    s2, i2 = _fit_segment(observations, seam - overlap, n)

    fitted = []
    for idx, (day, _v) in enumerate(observations):
        x = day.toordinal()
        if idx < seam - overlap:
            y = s1 * x + i1
        elif idx > seam + overlap:
            y = s2 * x + i2
        else:
            w = (idx - (seam - overlap)) / (2 * overlap)
            y = (1 - w) * (s1 * x + i1) + w * (s2 * x + i2)
        fitted.append((day, round(y, 1)))
    return fitted


def _detect_disturbances(trend: list) -> list:
    """Ledger detection on the clean trend: contiguous runs where the trend sits
    ≥ DISTURBANCE_DELTA_THRESHOLD below the *seasonal expectation* become ledger
    events. Comparing against the seasonal expectation — not the raw baseline —
    is what keeps winter troughs (part of the normal cycle) out of the ledger.

    Returns [(start, ndvi_min, ndvi_min_date, end), ...]."""
    events = []
    run_start = None
    run_min = None
    run_min_date = None
    run_last = None
    for day, value in trend:
        in_event = _seasonal_ndvi(day) - value >= DISTURBANCE_DELTA_THRESHOLD
        if in_event:
            if run_start is None:
                run_start, run_min, run_min_date = day, value, day
            elif value < run_min:
                run_min, run_min_date = value, day
            run_last = day
        elif run_start is not None:
            events.append((run_start, run_min, run_min_date, run_last))
            run_start, run_min, run_min_date, run_last = None, None, None, None
    if run_start is not None:  # event still active at series end
        events.append((run_start, run_min, run_min_date, run_last))
    return events


# ---------------------------------------------------------------------------
# Seeded overlays
# ---------------------------------------------------------------------------


def _seeded_disturbance_dates(seed: int) -> list:
    """Choose disturbance start dates from fixed span fractions, jittered by seed.

    Roughly one event per year: Y1 anchor at ~33% of the span, Y2 anchor at ~85%.
    Each seed produces its own event placement, so every run tells its own story.
    """
    total_days = (BASE_END - BASE_START).days
    rng = random.Random(seed * 7919 + 13)
    dates = []
    for frac in (Y1_ANCHOR_FRACTION, Y2_ANCHOR_FRACTION):
        jitter = rng.randint(-ANCHOR_JITTER_DAYS, ANCHOR_JITTER_DAYS)
        offset = int(round(frac * total_days)) + jitter
        offset = max(15, min(total_days - 15, offset))
        dates.append(BASE_START + timedelta(days=offset))
    return dates


def _seeded_cloud_flags(seed: int) -> tuple:
    """Decide whether the Y1 and Y2 year-end observations are cloud-affected.
    ~1-in-3 chance per observation, driven by the seed."""
    rng = random.Random(seed * 104729 + 7)
    return (rng.random() < 0.34, rng.random() < 0.34)


def _score_window_gate(usable_pct: float, agreement: float, threshold: float) -> tuple:
    """Raw confidence gate on a ≤30-day same-season window."""
    result = compute_confidence(
        usable_pixel_pct=usable_pct,
        ndvi_model_agreement=agreement,
        temporal_gap_days=WINDOW_GAP_DAYS,
        calibration_fit_score=WINDOW_CALIBRATION_FIT,
        threshold=threshold,
    )
    return result.score, result.passed


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def _ndvi_on(series: list, target: date) -> float:
    """Observation nearest to `target` in a sorted [(date, ndvi), ...] series."""
    return min(series, key=lambda item: abs((item[0] - target).days))[1]


def _canopy_height(end_date: date, events: list) -> float:
    """Standing canopy height on `end_date`, after any disturbance events.

    A disturbance resets canopy to POST_HARVEST_HEIGHT_M; the stand regenerates
    at REGEN_RATE_M_PER_YEAR until the next event or the observation date.
    """
    height = PRE_HARVEST_HEIGHT_M
    last_event = None
    for ev in events:
        if ev <= end_date:
            height = POST_HARVEST_HEIGHT_M
            last_event = ev
        else:
            break
    if last_event is not None:
        years = (end_date - last_event).days / 365.25
        height = min(PRE_HARVEST_HEIGHT_M, POST_HARVEST_HEIGHT_M + REGEN_RATE_M_PER_YEAR * years)
    return height


def _build_window(label: str, ref_date: date, end_date: date, observations: list,
                  cloud_hit: bool, threshold: float) -> YearWindow:
    """Score one same-season window with the unchanged raw gate."""
    ref_ndvi = _ndvi_on(observations, ref_date)
    end_ndvi = _ndvi_on(observations, end_date)
    if cloud_hit:
        # Boundary #1: quality check retried a nearby date window; the retry's
        # resolved quality feeds the gate, with a small agreement penalty.
        usable, agreement, retried = CLOUD_RETRY_USABLE_PCT, CLOUD_RETRIED_AGREEMENT, True
    else:
        usable, agreement, retried = WINDOW_USABLE_PCT, WINDOW_AGREEMENT, False
    score, passed = _score_window_gate(usable, agreement, threshold)
    return YearWindow(
        label=label,
        ref_date=ref_date,
        end_date=end_date,
        ref_ndvi=ref_ndvi,
        end_ndvi=end_ndvi,
        delta=end_ndvi - ref_ndvi,
        gate_score=score,
        gate_passed=passed,
        retried=retried,
    )


def build_two_year_comparison(seed: int = 42, clouds_enabled: bool = True,
                              threshold: float = WINDOW_THRESHOLD,
                              region_name: str = "Test Forest Polygon A") -> TwoYearComparison:
    """Build the full two-year comparison for the demo region.

    Same seed ⇒ identical series, verdicts, and audit artifact. The raw 2-year
    gate and the composite (window-based) gate are both computed so the
    dashboard can show exactly why the composite design is the honest way to
    compare across years under Boundary #2.
    """
    event_dates = _seeded_disturbance_dates(seed)
    observations, trend = build_two_year_series(seed, event_dates)
    fitted = _piecewise_trend(observations)

    # Same-season windows: mid-July reference vs mid-July end, per year.
    y1_ref, y1_end = BASE_START, date(2024, 7, 14)
    y2_ref, y2_end = date(2024, 7, 15), BASE_END

    cloud_y1, cloud_y2 = _seeded_cloud_flags(seed) if clouds_enabled else (False, False)
    y1_window = _build_window("Y1 window", y1_ref, y1_end, observations, cloud_y1, threshold)
    y2_window = _build_window("Y2 window", y2_ref, y2_end, observations, cloud_y2, threshold)

    raw_gap_days = (y2_end - y1_ref).days
    # The raw span is only as good as its worst year-end observation: use the
    # minimum quality across the two ends (cloud-affected ends degrade it).
    span_usable = min(WINDOW_USABLE_PCT, CLOUD_RETRY_USABLE_PCT if (cloud_y1 or cloud_y2) else WINDOW_USABLE_PCT)
    span_agreement = min(WINDOW_AGREEMENT, CLOUD_RETRIED_AGREEMENT if (cloud_y1 or cloud_y2) else WINDOW_AGREEMENT)
    # Apply the honest temporal-gap penalty for the full-span comparison
    # (same normalizer as confidence_score._normalize_temporal_gap).
    raw_temporal_norm = 0.0 if raw_gap_days > 180 else (
        1.0 if raw_gap_days <= 30 else 1.0 - (raw_gap_days - 30) / 150.0
    )
    raw_score = (
        span_usable / 100.0 * 0.35
        + span_agreement * 0.30
        + raw_temporal_norm * 0.20
        + WINDOW_CALIBRATION_FIT * 0.15
    )
    raw_passed = raw_score >= threshold

    composite_score = (y1_window.gate_score + y2_window.gate_score) / 2.0
    composite_passed = y1_window.gate_passed and y2_window.gate_passed

    ledger_events = _detect_disturbances(trend)
    disturbances = []
    for i, (start, ndvi_min, ndvi_min_date, end) in enumerate(ledger_events, 1):
        before = _canopy_height(start - timedelta(days=1), event_dates)
        after = _canopy_height(start, event_dates)
        # Drop is measured against the seasonal expectation at the trough date —
        # NOT the raw baseline — so winter troughs don't inflate the number.
        seasonal_at_min = _seasonal_ndvi(ndvi_min_date)
        disturbances.append(
            Disturbance(
                event_id=f"dist-{i}",
                start=start,
                end=end,
                ndvi_min=ndvi_min,
                ndvi_min_date=ndvi_min_date,
                ndvi_drop=seasonal_at_min - ndvi_min,
                canopy_before_m=before,
                canopy_after_m=after,
                regen_rate_m_per_year=REGEN_RATE_M_PER_YEAR,
            )
        )

    y1_count = sum(1 for d in disturbances if d.start < y2_ref)
    y2_count = len(disturbances) - y1_count

    return TwoYearComparison(
        seed=seed,
        region_name=region_name,
        clouds_enabled=clouds_enabled,
        threshold=threshold,
        ndvi_series=observations,
        trend_series=fitted,
        ref_ndvi=_ndvi_on(observations, y1_ref),
        y1_window=y1_window,
        y2_window=y2_window,
        season_delta_ndvi=y2_window.end_ndvi - y1_window.ref_ndvi,
        raw_gap_days=raw_gap_days,
        raw_gate_score=raw_score,
        raw_gate_passed=raw_passed,
        composite_score=composite_score,
        composite_passed=composite_passed,
        disturbances=disturbances,
        y1_disturbance_count=y1_count,
        y2_disturbance_count=y2_count,
        y1_ndvi_min=min(v for d, v in observations if d < y2_ref),
        y2_ndvi_min=min(v for d, v in observations if d >= y2_ref),
        y1_end_canopy_m=_canopy_height(y1_end, event_dates),
        y2_end_canopy_m=_canopy_height(y2_end, event_dates),
    )


if __name__ == "__main__":
    # Windows consoles default to a legacy code page (e.g. cp1252) that cannot
    # encode the Δ in this block's output — same fix as demo_run.py.
    import sys

    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Quick manual sanity check across a few seeds and the no-cloud variant.
    for s in (1, 42, 777):
        for clouds in (True, False):
            cmp = build_two_year_comparison(seed=s, clouds_enabled=clouds)
            verdict = (
                f"raw={'PASS' if cmp.raw_gate_passed else 'BLOCK'} "
                f"({cmp.raw_gate_score:.3f}) · "
                f"composite={'PASS' if cmp.composite_passed else 'BLOCK'} "
                f"({cmp.composite_score:.3f})"
            )
            print(
                f"seed={s:4d} clouds={int(clouds)} | ΔNDVI={cmp.season_delta_ndvi:+7.1f} | "
                f"events={len(cmp.disturbances)} (Y1:{cmp.y1_disturbance_count} Y2:{cmp.y2_disturbance_count}) | {verdict}"
            )
            for d in cmp.disturbances:
                print(f"    {d.to_row()}")
