"""ArborPulse dashboard: read the real Earth Engine handoff JSON."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from config.region_utils import geometry_center, validate_region_geojson
from feedback.correction_logger import VALID_OUTCOMES, get_reviews, log_review

HANDOFF_CANDIDATES = (
    Path("outputs/member_a_handoff.json"),
    Path("../Arborpulse/outputs/member_a_handoff.json"),
)
DEFAULT_HANDOFF = next((path for path in HANDOFF_CANDIDATES if path.exists()), HANDOFF_CANDIDATES[0])
SAME_SEASON_CANDIDATES = (
    Path("outputs/member_a_handoff_same_season.json"),
    Path("../Arborpulse/outputs/member_a_handoff_same_season.json"),
)
SAME_SEASON_HANDOFF = next((path for path in SAME_SEASON_CANDIDATES if path.exists()), None)
MODEL_EVALUATION = Path("outputs/model_evaluation.json")
MONITORING_DIRECTORIES = (Path("outputs/monitoring"), Path("../Arborpulse/outputs/monitoring"))


def load_handoff(path: Path) -> dict:
    with path.open(encoding="utf-8") as handoff_file:
        return json.load(handoff_file)


def latest_monitoring_handoff() -> Path | None:
    candidates = [file for directory in MONITORING_DIRECTORIES if directory.exists() for file in directory.glob("handoff_*.json")]
    return max(candidates, key=lambda file: file.name) if candidates else None


st.set_page_config(page_title="ArborPulse", page_icon="🌿", layout="wide")
st.title("🌿 ArborPulse")
st.caption("Explainable vegetation-change screening for the Rondônia pilot area")

st.sidebar.subheader("Study area")
upload = st.sidebar.file_uploader("Upload a Polygon GeoJSON", type=["geojson", "json"])
if upload is not None:
    try:
        uploaded_region = json.loads(upload.getvalue().decode("utf-8"))
        validate_region_geojson(uploaded_region)
        custom_region_path = Path("config/user_region.geojson")
        custom_region_path.write_text(json.dumps(uploaded_region, indent=2) + "\n", encoding="utf-8")
        st.sidebar.success("Boundary validated and saved locally.")
        st.sidebar.code(
            "python run_pipeline.py --project composed-arch-476417-e5 "
            "--region config/user_region.geojson --before YYYY-MM-DD --after YYYY-MM-DD",
            language="bash",
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        st.sidebar.error(f"Invalid study-area file: {error}")

options = {"Original comparison: Jan 2025 → Aug 2025": DEFAULT_HANDOFF}
if SAME_SEASON_HANDOFF:
    options["Same-season comparison: Jan 2025 → Jan 2026"] = SAME_SEASON_HANDOFF
selected_label = st.sidebar.selectbox("Analysis scenario", list(options))
path_text = st.sidebar.text_input("Member A handoff JSON", str(options[selected_label]))
handoff_path = Path(path_text)
if not handoff_path.exists():
    st.info("Run `python run_pipeline.py ...` first, then refresh this page.")
    st.stop()

data = load_handoff(handoff_path)
decision = data.get("decision", {})
confidence = data.get("confidence", {})
before, after = data["before"], data["after"]
change = data["ndvi_change"]
timing = data.get("comparison_timing")

region_payload = json.loads(Path("config/region.geojson").read_text(encoding="utf-8"))
if Path("config/user_region.geojson").exists():
    region_payload = json.loads(Path("config/user_region.geojson").read_text(encoding="utf-8"))
longitude, latitude = geometry_center(region_payload)

status = decision.get("status", "unknown")
if status == "review_required":
    st.warning(decision.get("headline", "Review required"))
elif status == "no_strong_signal":
    st.success(decision.get("headline", "No strong signal"))
else:
    st.info(decision.get("headline", "Pipeline result available"))

metrics = st.columns(4)
metrics[0].metric(
    "Data confidence", confidence.get("label", "unknown").title(), confidence.get("score"),
    help="Based on usable imagery and calibration availability; it is not certainty that deforestation occurred.",
)
metrics[1].metric("Mean NDVI change", f"{change['mean_delta']:+.4f}")
metrics[2].metric("Review-queue area", f"{change['loss_pixel_pct']:.2f}%")
metrics[3].metric("Usable pixels", f"{before['usable_pixel_pct']:.1f}% → {after['usable_pixel_pct']:.1f}%")

if timing:
    if timing["same_season"]:
        st.success(f"Comparison timing: same season · {timing['day_gap']} days apart")
    else:
        st.warning(f"Comparison timing: seasonal mismatch · {timing['day_gap']} days apart")
    st.caption(timing["interpretation"])

st.subheader("Evidence")
for item in decision.get("evidence", []):
    st.write(f"• {item}")

validation = data.get("hansen_validation")
if validation:
    st.subheader("Independent annual reference")
    reference = st.columns(3)
    reference[0].metric("Hansen loss pixels", f"{validation['reference_loss_pixel_pct']:.2f}%")
    reference[1].metric("NDVI / Hansen overlap", f"{validation['ndvi_review_overlap_pct']:.2f}%")
    reference[2].metric("Overlap area", f"{validation['overlap_pixel_pct']:.2f}%")
    st.caption(validation["interpretation"])

st.subheader("Decision trail")
for item in decision.get("limitations", []):
    st.write(f"• {item}")
st.info(decision.get("recommendation", "Inspect the Earth Engine map before acting."))

latest_monitor = latest_monitoring_handoff()
if latest_monitor:
    monitor = load_handoff(latest_monitor)
    monitor_decision = monitor.get("decision", {})
    st.subheader("Latest scheduled monitoring run")
    monitor_metrics = st.columns(3)
    monitor_metrics[0].metric("Monitoring status", monitor_decision.get("status", "unknown").replace("_", " ").title())
    monitor_metrics[1].metric("NDVI change", f"{monitor['ndvi_change']['mean_delta']:+.4f}")
    monitor_metrics[2].metric("Data confidence", monitor.get("confidence", {}).get("label", "unknown").title())
    st.caption(f"Source: {latest_monitor.name} · {monitor_decision.get('recommendation', '')}")

st.subheader("Visual validation")
st.caption("Open satellite imagery to inspect the review area before recording an outcome. Imagery date and resolution vary by provider.")
st.link_button(
    "Open satellite imagery for this study area",
    f"https://www.google.com/maps/@{latitude:.6f},{longitude:.6f},14z/data=!3m1!1e3",
)

st.subheader("Human review")
st.caption("Record what a reviewer found after inspecting the flagged area. Feedback stays local and is not committed to Git.")
with st.form("human_review"):
    outcome = st.selectbox("Review outcome", sorted(VALID_OUTCOMES))
    note = st.text_area("Reviewer note (optional)", placeholder="What imagery or field evidence supports this outcome?")
    submitted = st.form_submit_button("Save review")
if submitted:
    saved_path = log_review(
        handoff_path=str(handoff_path),
        region=data.get("region", "unknown"),
        pipeline_status=decision.get("status", "unknown"),
        outcome=outcome,
        note=note,
    )
    st.success(f"Review saved locally to {saved_path}.")

reviews = get_reviews()
if reviews:
    st.caption(f"Saved review history ({len(reviews)} record{'s' if len(reviews) != 1 else ''})")
    st.dataframe(
        [
            {
                "Reviewed at": review["reviewed_at"],
                "Outcome": review["outcome"].replace("_", " "),
                "Pipeline status": review["pipeline_status"].replace("_", " "),
                "Note": review["note"] or "—",
            }
            for review in reviews
        ],
        hide_index=True,
        use_container_width=True,
    )

if MODEL_EVALUATION.exists():
    model = load_handoff(MODEL_EVALUATION)
    st.subheader("Custom Random Forest screening model")
    model_metrics = st.columns(4)
    model_metrics[0].metric("Spatial hold-out accuracy", f"{model['overall_accuracy'] * 100:.2f}%")
    model_metrics[1].metric("Loss precision", f"{model['loss_class_precision'] * 100:.2f}%")
    model_metrics[2].metric("Loss recall", f"{model['loss_class_recall'] * 100:.2f}%")
    model_metrics[3].metric("Loss F1", f"{model['loss_class_f1'] * 100:.2f}%")
    st.caption(
        f"Trained on {model['training_samples']:,} balanced samples; tested on "
        f"{model['testing_samples']:,} geographically held-out samples. {model['interpretation']}"
    )

with st.expander("Raw Member A handoff"):
    st.json(data)

"""
dashboard/app.py — SylvaSense / ArborPulse MRV dashboard
=========================================================

Streamlit front end for the Member B pipeline slice: multi-factor confidence
scoring and the auditable decision trail.

Pages
-----
1. Overview          — what SylvaSense is, the confidence formula, the two
                       autonomous boundaries (quality-check retry, confidence
                       gate), and a status snapshot of the run history.
2. Run pipeline      — execute the full mocked pipeline (pass / retry /
                       blocked), watch the decision trail render live, download
                       the JSON audit artifact.
3. Confidence
   calculator        — manual what-if tool: drag the four factors, see exactly
                       how the gate verdict changes. Uses the same
                       compute_confidence() as the pipeline.
4. Run history       — every past run from outputs/decision_logs/, final
                       status, confidence over time, per-factor breakdown.
5. 2-year comparison — proves a two-year Year 1 vs Year 2 comparison is
                       possible: seeded synthetic observations for a fixed
                       2-year calendar, headline deltas, a disturbance ledger,
                       and BOTH gate verdicts (raw full-span vs composite of
                       two season-matched windows) with a JSON audit artifact.
6. Real-time sensing — type any location and get its LIVE picture: a nearby
                       green-cover survey (OpenStreetMap), today's NASA
                       satellite imagery, current weather + air quality,
                       nearby geotagged photos, optional fire hotspots, and
                       an auto-written summary report. Real APIs, no mocks,
                       no API keys.

Deployment
----------
Runs on Streamlit Community Cloud with zero secrets. It only reads/writes
local files under outputs/, and all upstream data (Member A's data_acquisition/
and detection/ modules) is mocked inside demo_run.py until those land.

Run locally from the repo root:
    streamlit run dashboard/app.py
"""

import json
import sys
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis.confidence_score import (  # noqa: E402
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_WEIGHTS,
    IDEAL_GAP_DAYS,
    MAX_GAP_DAYS,
    compute_confidence,
)
from demo_run import run_pipeline  # noqa: E402
from analysis.year_comparison import (  # noqa: E402
    DISTURBANCE_DELTA_THRESHOLD,
    build_two_year_comparison,
)
from analysis.realtime_sensing import (  # noqa: E402
    build_report,
    geocode,
)

DECISION_LOG_DIR = REPO_ROOT / "outputs" / "decision_logs"

STATUS_ICON = {"ok": "✅", "retry": "🔁", "warning": "⚠️", "blocked": "🛑"}
FACTOR_LABELS = {
    "data_quality": "Data quality (usable pixels)",
    "model_agreement": "Model agreement (Open-Canopy vs NDVI)",
    "temporal_gap": "Temporal gap (Date A → B)",
    "calibration_fit": "Calibration fit (NDVI baseline)",
}

# Simulated region footprint (Test Forest Polygon A). A real deployment swaps
# this for Member A's generated GeoJSON; config/region.geojson is currently a
# placeholder stub, so a fixed demo footprint is used for the map.
DEMO_FOOTPRINT = {
    "type": "Feature",
    "properties": {"name": "Test Forest Polygon A"},
    "geometry": {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [0.0, 0.02], [0.02, 0.02], [0.02, 0.0], [0.0, 0.0]]],
    },
}


# ---------------------------------------------------------------------------
# Page config + session state
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="SylvaSense — MRV Dashboard",
    page_icon="🌲",
    layout="wide",
    initial_sidebar_state="expanded",
)

if "history" not in st.session_state:
    st.session_state.history = []  # list of run dicts, newest first


# ---------------------------------------------------------------------------
# Shared render helpers
# ---------------------------------------------------------------------------
def render_confidence_breakdown(result) -> None:
    """Per-factor contribution table + bar chart, shared by Run pipeline and
    Confidence calculator pages so both surfaces look identical."""
    rows = [
        {
            "Factor": FACTOR_LABELS.get(f.name, f.name),
            "Raw input": f.raw_value,
            "Normalized (0–1)": f.normalized,
            "Weight": f.weight,
            "Contribution": f.contribution,
            "Reasoning": f.reasoning,
        }
        for f in result.factors
    ]
    df = pd.DataFrame(rows)
    st.dataframe(
        df.style.format(
            {"Raw input": "{:.2f}", "Normalized (0–1)": "{:.2f}", "Weight": "{:.2f}", "Contribution": "{:.3f}"}
        ),
        use_container_width=True,
        hide_index=True,
    )
    chart_df = df.set_index("Factor")[["Contribution"]]
    st.bar_chart(chart_df, height=280)


def render_trail(run: dict) -> None:
    """Decision trail with boundary decisions visually highlighted.

    Accepts a run dict (the shape DecisionTrail.to_dict() produces), so the
    same renderer handles freshly executed runs and runs loaded from disk.
    """
    status = run["final_status"]
    icon = STATUS_ICON[status]
    color = {"ok": "green", "retry": "orange", "warning": "orange", "blocked": "red"}[status]
    steps = run.get("steps", [])
    boundary_count = sum(1 for s in steps if s.get("is_boundary"))
    st.markdown(
        f"#### Run `{run['run_id']}` — final status: :{color}[{icon} {status.upper()}] "
        f"· {boundary_count} boundary decision(s)"
    )

    for i, s in enumerate(steps, 1):
        step_icon = STATUS_ICON[s["status"]]
        if s.get("is_boundary"):
            color = {"ok": "green", "retry": "orange", "blocked": "red"}[s["status"]]
            header = f"**{i}. {step_icon} {s['step_name']}** — :{color}[**⚡ BOUNDARY**]"
        else:
            header = f"**{i}. {step_icon} {s['step_name']}**"
        with st.expander(f"{header} — {s['summary']}", expanded=s.get("is_boundary", False)):
            st.write(s["summary"])
            if s.get("details"):
                st.json(json.loads(json.dumps(s["details"])), expanded=True)


def render_region_footprint(footprint: dict) -> None:
    """Render the region's GeoJSON footprint via pydeck's GeoJsonLayer.

    st.map() cannot take a GeoJSON dict (it expects a lat/lon DataFrame), and
    Member A will hand us polygons — so we go one level lower. Falls back to a
    text caption if the map layer ever fails, so a rendering hiccup can never
    take down the trail display above it.
    """
    try:
        layer = pdk.Layer(
            "GeoJsonLayer",
            data=footprint,
            stroked=True,
            filled=True,
            get_fill_color="[46, 125, 50, 80]",
            get_line_color="[46, 125, 50]",
            line_width_min_pixels=2,
        )
        view = pdk.ViewState(latitude=0.01, longitude=0.01, zoom=8, pitch=0)
        deck = pdk.Deck(layers=[layer], initial_view_state=view, map_provider="carto", map_style="light")
        st.pydeck_chart(deck, use_container_width=True)
    except Exception as e:  # noqa: BLE001 — never let a map glitch kill the audit view
        st.caption(f"Region footprint: {footprint['properties']['name']} (map unavailable: {e})")


def load_history_from_disk() -> list[dict]:
    """Runs saved by the CLI demo (demo_run.py) appear here automatically."""
    runs = []
    if DECISION_LOG_DIR.exists():
        for jf in sorted(DECISION_LOG_DIR.glob("run_*.json")):
            try:
                runs.append(json.loads(jf.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue  # a torn/partial write from a crashed run shouldn't break the dashboard
    return runs


# ---------------------------------------------------------------------------
# Sidebar — navigation + global threshold
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## 🌲 SylvaSense")
    st.caption("Autonomous deforestation detection · auditable by design")
    page = st.radio(
        "Navigation",
        [
            "Overview",
            "Run pipeline",
            "Confidence calculator",
            "2-year comparison",
            "Real-time sensing",
            "Run history",
        ],
        label_visibility="collapsed",
    )
    st.divider()
    threshold = st.slider(
        "Confidence gate threshold",
        min_value=0.0,
        max_value=1.0,
        value=DEFAULT_CONFIDENCE_THRESHOLD,
        step=0.05,
        help="Runs scoring below this withhold their alert and flag for human review [Boundary #2].",
    )

# ---------------------------------------------------------------------------
# Page 1 — Overview
# ---------------------------------------------------------------------------
if page == "Overview":
    st.title("🌲 SylvaSense — MRV Confidence & Audit Dashboard")
    st.markdown(
        "SylvaSense detects deforestation from satellite imagery and decides — autonomously — "
        "whether each detection is trustworthy enough to raise an alert. This dashboard exposes "
        "**the decision layer**: the multi-factor confidence score and the decision trail that "
        "records not just *what* the system concluded, but *why*, including the moments it chose "
        "not to trust itself."
    )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### The confidence formula")
        w = DEFAULT_WEIGHTS
        st.markdown(
            f"**Confidence = 0.35·data_quality + 0.30·model_agreement + 0.20·temporal_gap "
            f"+ 0.15·calibration_fit**\n\n"
            f"- **Data quality** carries the highest weight: bad input pixels are the least "
            f"recoverable failure mode.\n"
            f"- **Model agreement** cross-validates the Open-Canopy detector against the "
            f"independent NDVI signal.\n"
            f"- **Temporal gap** penalizes long Date A→B windows (confounds like seasonal growth); "
            f"full credit up to {IDEAL_GAP_DAYS} days, zero at {MAX_GAP_DAYS}.\n"
            f"- **Calibration fit** reflects per-region NDVI baseline convergence."
        )
    with c2:
        st.markdown("##### Two autonomous boundaries")
        st.markdown(
            "**⚡ Boundary #1 — quality-check retry.** If the first imagery query fails the "
            "usable-pixel threshold, the system re-queries a nearby date window instead of "
            "alerting on bad data — and records that it did so.\n\n"
            "**⚡ Boundary #2 — confidence gate.** Below the threshold "
            f"(currently **{threshold:.2f}**, adjustable in the sidebar), the alert is *withheld* "
            "and the detection is flagged for human review. Withholding a low-confidence alert "
            "is a decision the system makes about itself."
        )
        st.info(
            "Every boundary decision is tagged `is_boundary` in the trail and highlighted "
            "on the Run pipeline page."
        )

    st.divider()
    st.markdown("##### Current run history snapshot")
    history = st.session_state.history + load_history_from_disk()
    if not history:
        st.info("No runs yet — execute your first run on the **Run pipeline** page.")
    else:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total runs", len(history))
        m2.metric("Alerts released", sum(1 for r in history if r["final_status"] == "ok"))
        m3.metric("Withheld (blocked)", sum(1 for r in history if r["final_status"] == "blocked"))
        m4.metric(
            "Boundary events",
            sum(r.get("boundary_count", 0) for r in history),
        )

# ---------------------------------------------------------------------------
# Page 2 — Run pipeline
# ---------------------------------------------------------------------------
elif page == "Run pipeline":
    st.title("▶️ Run pipeline")
    st.markdown(
        "Executes the full pipeline — imagery fetch, quality check (with autonomous retry), "
        "detection, NDVI cross-check, calibration, biomass estimate, and the confidence gate — "
        "using mocked upstream data until Member A's modules land. The CLI (`python demo_run.py`) "
        "runs this exact same code path."
    )

    scenario = st.radio(
        "Scenario",
        ["pass", "retry", "blocked"],
        horizontal=True,
        help=(
            "**pass** — clean imagery, strong agreement → alert released. "
            "**retry** — poor first query, auto re-queried (Boundary #1) → alert released. "
            "**blocked** — weak evidence → confidence gate withholds the alert (Boundary #2)."
        ),
    )
    region_name = st.text_input("Region name", value="Test Forest Polygon A")

    if st.button("🚀 Execute pipeline run", type="primary"):
        with st.spinner("Fetching imagery → quality check → detection → calibration → confidence gate…"):
            trail, result = run_pipeline(scenario, region_name=region_name, threshold=threshold)
            trail.save()
        st.session_state.history.insert(0, trail.to_dict())

        # Verdict banner
        if result.passed:
            st.success(
                f"**ALERT RELEASED** — confidence **{result.score:.3f}** ≥ threshold "
                f"**{result.threshold:.3f}**"
            )
        else:
            st.error(
                f"**ALERT WITHHELD** — confidence **{result.score:.3f}** < threshold "
                f"**{result.threshold:.3f}** — flagged for human review"
            )

        left, right = st.columns([3, 2])
        with left:
            st.markdown("##### Decision trail")
            render_trail(trail.to_dict())
        with right:
            st.markdown("##### Confidence breakdown")
            render_confidence_breakdown(result)

            st.markdown("##### Region footprint")
            render_region_footprint(DEMO_FOOTPRINT)

            st.download_button(
                "⬇️ Download JSON audit artifact",
                data=trail.to_json(),
                file_name=f"{trail.run_id}.json",
                mime="application/json",
            )

# ---------------------------------------------------------------------------
# Page 3 — Confidence calculator
# ---------------------------------------------------------------------------
elif page == "Confidence calculator":
    st.title("🧮 Confidence calculator")
    st.markdown(
        "Manual what-if tool for the exact gate the pipeline uses. Drag the four factors and "
        "watch the verdict flip — useful for calibrating the threshold and demoing *why* the "
        "weights are ordered the way they are."
    )

    cc1, cc2 = st.columns(2)
    with cc1:
        usable_pct = st.slider("Usable pixels after cloud masking (%)", 0.0, 100.0, 91.2, 0.1)
        agreement = st.slider("NDVI / model agreement (0–1)", 0.0, 1.0, 0.83, 0.01)
    with cc2:
        gap_days = st.slider(f"Temporal gap (days, 0–{MAX_GAP_DAYS})", 0, MAX_GAP_DAYS, 24, 1)
        calib = st.slider("Calibration fit (0–1)", 0.0, 1.0, 0.77, 0.01)

    result = compute_confidence(
        usable_pixel_pct=usable_pct,
        ndvi_model_agreement=agreement,
        temporal_gap_days=float(gap_days),
        calibration_fit_score=calib,
        threshold=threshold,
    )

    if result.passed:
        st.success(f"**{result.summary_line()}**")
    else:
        st.error(f"**{result.summary_line()}**")

    render_confidence_breakdown(result)

# ---------------------------------------------------------------------------
# Page 4 — 2-year comparison
# ---------------------------------------------------------------------------
elif page == "2-year comparison":
    st.title("📅 2-year comparison")
    st.markdown(
        "Is a comparison between two years possible? **Yes — and this page proves it end to "
        "end.** A full 2-year raw comparison pushes the Date A→B gap far past the gate's "
        f"{MAX_GAP_DAYS}-day comfort zone, forfeiting the entire temporal-gap factor. The fix is "
        "not to weaken the gate but to compare like with like: score each year as a short, "
        "**season-matched window** (mid-July reference vs mid-July end) that earns full "
        "temporal credit, then attribute the between-year delta to the year pair. Both verdicts "
        "are shown side by side below."
    )

    # Controls -----------------------------------------------------------------
    yc1, yc2, yc3 = st.columns([2, 2, 3])
    with yc1:
        seed = st.number_input(
            "Scenario seed", min_value=0, max_value=999_999, value=42, step=1,
            help="Drives the seeded disturbance placement, trough depth, and cloud overlay. Same seed ⇒ same comparison — the comparison is fully deterministic.",
        )
    with yc2:
        clouds_enabled = st.toggle(
            "Cloud overlay", value=True,
            help="When a year-end observation is cloud-affected, Boundary #1 fires: the quality check auto-retries a nearby date window, and the retry's resolved quality feeds the gate.",
        )
    with yc3:
        st.metric("Calendar", "Jul 2023 → Jul 2025", help="Fixed demo calendar: 731 daily observations, mid-July to mid-July, exactly two years.")

    cmp = build_two_year_comparison(seed=int(seed), clouds_enabled=clouds_enabled, threshold=threshold)

    # Verdict banner -----------------------------------------------------------
    if cmp.composite_passed:
        if cmp.season_delta_ndvi <= -DISTURBANCE_DELTA_THRESHOLD:
            st.error(
                f"**DEFORESTATION ALERT RELEASED** — Y2 is **{abs(cmp.season_delta_ndvi):.1f} NDVI points** "
                f"below Y1 (same-season comparison). Composite confidence **{cmp.composite_score:.3f}** ≥ "
                f"threshold **{cmp.threshold:.3f}** — strong-enough evidence to act on."
            )
        else:
            st.success(
                f"**NO SIGNIFICANT CHANGE** — Y2 is {cmp.season_delta_ndvi:+.1f} NDVI points vs Y1 "
                f"(same-season). Composite confidence **{cmp.composite_score:.3f}** ≥ threshold "
                f"**{cmp.threshold:.3f}**."
            )
    else:
        st.warning(
            f"**COMPARISON WITHHELD** — composite confidence **{cmp.composite_score:.3f}** < threshold "
            f"**{cmp.threshold:.3f}** — flagged for human review [Boundary #2]."
        )

    # Headline deltas ----------------------------------------------------------
    y1d, y2d = cmp.y1_window, cmp.y2_window
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric(
        "Season ΔNDVI (Y2 − Y1)", f"{cmp.season_delta_ndvi:+.1f}",
        delta="decline" if cmp.season_delta_ndvi < 0 else "stable/improved",
        delta_color="inverse" if cmp.season_delta_ndvi < 0 else "normal",
    )
    k2.metric("Y1 canopy (end of year)", f"{cmp.y1_end_canopy_m:.1f} m")
    k3.metric("Y2 canopy (end of year)", f"{cmp.y2_end_canopy_m:.1f} m",
              delta=f"{cmp.y2_end_canopy_m - cmp.y1_end_canopy_m:+.1f} m",
              delta_color="inverse")
    k4.metric("Disturbance events", f"Y1: {cmp.y1_disturbance_count} · Y2: {cmp.y2_disturbance_count}")
    k5.metric("Composite confidence", f"{cmp.composite_score:.3f}")

    st.divider()

    # NDVI charts --------------------------------------------------------------
    obs_df = pd.DataFrame(cmp.ndvi_series, columns=["Date", "NDVI (observed)"]).set_index("Date")
    trend_df = pd.DataFrame(cmp.trend_series, columns=["Date", "NDVI (2-yr trend)"]).set_index("Date")
    st.line_chart({"NDVI (observed)": obs_df["NDVI (observed)"], "NDVI (2-yr trend)": trend_df["NDVI (2-yr trend)"]}, height=320)
    st.caption(
        "Daily NDVI (0–1000 scale) on the fixed 2-year calendar. The seasonal sine wave is "
        "expected behavior — the comparison reads the *level shift between like-for-like "
        "seasons*, which is why the trend line and the window deltas, not the seasonal "
        "troughs, drive the verdict."
    )

    st.markdown("##### Year-over-year, season-matched")
    yoy_df = pd.DataFrame(cmp.ndvi_series, columns=["Date", "NDVI"]).set_index("Date")
    yoy_df.index = pd.to_datetime(yoy_df.index)  # date objects → DatetimeIndex, else .dayofyear fails
    yoy_df["Year"] = yoy_df.index.map(lambda d: "Year 1" if d < pd.Timestamp("2024-07-15") else "Year 2")
    yoy_pivot = yoy_df.pivot_table(index=yoy_df.index.dayofyear, columns="Year", values="NDVI")
    st.line_chart(yoy_pivot, height=280)
    st.caption(
        "Both years plotted on a shared seasonal axis (day-of-year). The vertical gap between "
        "the two lines at any point is the season-matched Y1→Y2 difference — the comparison "
        "the headline delta summarizes."
    )

    # Delta table + ledger -----------------------------------------------------
    left, right = st.columns([2, 3])
    with left:
        st.markdown("##### Window deltas")
        delta_rows = [
            {
                "Window": y1d.label,
                "Ref (mid-Jul '23)": round(y1d.ref_ndvi, 1),
                "End (mid-Jul '24)": round(y1d.end_ndvi, 1),
                "Δ NDVI": round(y1d.delta, 1),
            },
            {
                "Window": y2d.label,
                "Ref (mid-Jul '24)": round(y2d.ref_ndvi, 1),
                "End (mid-Jul '25)": round(y2d.end_ndvi, 1),
                "Δ NDVI": round(y2d.delta, 1),
            },
            {
                "Window": "Y1 → Y2",
                "Ref (mid-Jul '23)": round(y1d.ref_ndvi, 1),
                "End (mid-Jul '25)": round(y2d.end_ndvi, 1),
                "Δ NDVI": round(cmp.season_delta_ndvi, 1),
            },
        ]
        st.dataframe(pd.DataFrame(delta_rows), use_container_width=True, hide_index=True)

        st.markdown("##### Year-end canopy")
        st.bar_chart(
            pd.DataFrame({"Canopy height (m)": {"Y1 end": cmp.y1_end_canopy_m, "Y2 end": cmp.y2_end_canopy_m}}),
            height=220,
        )

    with right:
        st.markdown("##### Disturbance ledger")
        if not cmp.disturbances:
            st.info("No disturbance events crossed the ledger threshold for this seed — the region held steady.")
        else:
            st.dataframe(
                pd.DataFrame([d.to_row() for d in cmp.disturbances]),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                f"Events where NDVI fell ≥ {DISTURBANCE_DELTA_THRESHOLD:.0f} points below the "
                "seasonal expectation (winter troughs never count). Canopy resets to stump and "
                "regenerates at 1.8 m/yr. Y1/Y2 attribution is by event start date."
            )

    # Gate comparison ----------------------------------------------------------
    st.divider()
    st.markdown("##### Two verdicts for the same 2-year evidence")
    gc1, gc2 = st.columns(2)
    with gc1:
        st.markdown("**A. Raw gate on the full 730-day span**")
        st.markdown(
            f"Score **{cmp.raw_gate_score:.3f}** vs threshold **{cmp.threshold:.3f}** → "
            + (":green[PASS]" if cmp.raw_gate_passed else ":red[BLOCKED — Boundary #2]")
        )
        st.markdown(
            "The 730-day gap zeroes the temporal-gap factor (0.000 of its 0.200 "
            "contribution) and the span inherits the *worst* quality of its two year-end "
            "observations. It can still pass — but on a thin margin: one modest quality "
            "dip flips it to blocked. This is the fragile path."
        )
        st.progress(min(1.0, cmp.raw_gate_score), text=f"{cmp.raw_gate_score:.3f}")
    with gc2:
        st.markdown("**B. Composite of two season-matched windows (used for the verdict above)")
        st.markdown(
            f"Score **{cmp.composite_score:.3f}** vs threshold **{cmp.threshold:.3f}** → "
            + (":green[PASS]" if cmp.composite_passed else ":red[BLOCKED — Boundary #2]")
        )
        w_retry = " · ".join(
            f"{w.label}: {'🔁 retried' if w.retried else '✅ clean'} ({w.gate_score:.3f})"
            for w in (y1d, y2d)
        )
        st.markdown(
            f"Each window is a ≤30-day, season-matched pair, so each earns **full temporal "
            f"credit** — no factor is sacrificed. {w_retry}. The between-year delta is then "
            "attributed to the year pair, which is what makes a *credible* 2-year comparison "
            "possible without touching the gate."
        )
        st.progress(min(1.0, cmp.composite_score), text=f"{cmp.composite_score:.3f}")

    # Boundary trail -----------------------------------------------------------
    st.markdown("##### Boundary events in this comparison")
    retry_windows = [w for w in (y1d, y2d) if w.retried]
    boundary_lines = []
    if retry_windows:
        for w in retry_windows:
            boundary_lines.append(
                f"**⚡ Boundary #1 — quality-check retry ({w.label}).** The year-end observation "
                "was cloud-affected; the quality check auto-re-queried a nearby date window and "
                "the retry's resolved quality fed the gate."
            )
    if cmp.raw_gate_passed and not cmp.composite_passed:
        boundary_lines.append(
            f"**⚡ Boundary #2 — confidence gate.** Raw span confidence {cmp.raw_gate_score:.3f} "
            "passed, but the composite verdict withheld the comparison — flagged for human review."
        )
    elif not cmp.composite_passed:
        boundary_lines.append(
            f"**⚡ Boundary #2 — confidence gate.** Composite confidence {cmp.composite_score:.3f} "
            f"< threshold {cmp.threshold:.3f} — comparison withheld, flagged for human review."
        )
    if not boundary_lines:
        st.info(
            "No boundary events fired for this seed: both year-end observations were clean and "
            "the composite gate passed. Try other seeds or toggle the cloud overlay to see the "
            "boundaries in action."
        )
    else:
        for line in boundary_lines:
            st.markdown(line)

    st.download_button(
        "⬇️ Download 2-year comparison audit artifact (JSON)",
        data=json.dumps(cmp.to_audit_dict(), indent=2),
        file_name=f"two_year_comparison_seed{cmp.seed}.json",
        mime="application/json",
    )

# ---------------------------------------------------------------------------
# Page 5 — Real-time sensing
# ---------------------------------------------------------------------------
elif page == "Real-time sensing":
    st.title("🛰️ Real-time sensing")
    st.markdown(
        "Type any location — city, forest, region — and SylvaSense assembles its **live** picture: "
        "a nearby green-cover survey from OpenStreetMap, the latest NASA satellite imagery, current "
        "weather and air quality, nearby geotagged photos, optional active-fire hotspots, and an "
        "auto-written summary report. Every source is a free, keyless, real-time public API — the "
        "'sense' layer that would feed the pipeline for real."
    )

    @st.cache_data(ttl=900, show_spinner=False)
    def _cached_geocode(q: str):
        return geocode(q)

    @st.cache_data(ttl=900, show_spinner=False)
    def _cached_report(name, lat, lon, admin1, country, radius_m):
        from analysis.realtime_sensing import GeoResult

        place = GeoResult(name=name, lat=lat, lon=lon, admin1=admin1, country=country)
        return build_report(place, radius_m=radius_m)

    rc1, rc2, rc3 = st.columns([3, 1, 2])
    with rc1:
        query = st.text_input(
            "Location",
            value="Manaus",
            help="Any place name — e.g. 'Manaus', 'Sundarbans', 'Yasuni National Park', 'Borneo'.",
            label_visibility="collapsed",
        )
    with rc2:
        radius_km = st.select_slider("Survey radius", options=[1, 2, 5, 10, 20], value=5, format_func=lambda v: f"{v} km", label_visibility="collapsed")
    with rc3:
        st.write("")
        run_btn = st.button("🛰️ Sense location", type="primary", use_container_width=True)

    if run_btn:
        st.session_state.rt_query = query

    active_query = st.session_state.get("rt_query")
    if not active_query:
        st.info("Enter a location and press **Sense location** to pull live data.")
    else:
        if query != active_query:
            st.caption("Press **Sense location** to update the report for the new query.")
        candidates = _cached_geocode(active_query)
        if not candidates:
            st.error(f"Could not resolve location '{active_query}'. Try a different spelling.")
        else:
            if len(candidates) > 1:
                labels = [c.display for c in candidates]
                pick = st.selectbox("Matching locations", labels, help="The geocoder found several matches — pick one.")
                place = candidates[labels.index(pick)]
            else:
                place = candidates[0]

            with st.spinner("Surveying OSM → fetching satellite tile → conditions → photos…"):
                report = _cached_report(place.name, place.lat, place.lon, place.admin1, place.country, int(radius_km) * 1000)

            st.subheader(f"📍 {place.display}")
            st.caption(f"{place.lat:.4f}, {place.lon:.4f} · geocoded via {place.source} · report generated {report.generated_at[:16].replace('T', ' ')} UTC")

            # Green-cover verdict line ----------------------------------------
            gs = report.survey.green_score if report.survey else None
            if gs is None:
                st.markdown(":gray[**Green-cover verdict: unavailable**] — the OSM survey did not respond this time.")
            elif gs >= 0.66:
                st.markdown(f":green[**Green-cover verdict: DENSE** ({gs:.2f})] — heavily forested / well-vegetated surroundings.")
            elif gs >= 0.33:
                st.markdown(f":orange[**Green-cover verdict: MODERATE** ({gs:.2f})] — mixed green cover.")
            else:
                st.markdown(f":red[**Green-cover verdict: SPARSE** ({gs:.2f})] — little tagged green cover here.")

            # Headline metrics -------------------------------------------------
            def _fmt(v, suffix="", nd=1):
                return "—" if v is None else f"{v:.{nd}f}{suffix}"

            cond = report.conditions
            m1, m2, m3, m4, m5, m6 = st.columns(6)
            m1.metric("Green features (OSM)", report.survey.total if report.survey else "—",
                      delta=f"{report.survey.named_count} named" if report.survey and report.survey.named_count else None)
            m2.metric("Green score", f"{gs:.2f}" if gs is not None else "—")
            m3.metric("Temperature", _fmt(cond.temperature_c if cond else None, " °C"))
            m4.metric("Cloud cover", _fmt(cond.cloud_pct if cond else None, "%", nd=0))
            m5.metric("PM2.5", _fmt(cond.pm2_5 if cond else None, "", nd=0))
            m6.metric("Fire hotspots", len(report.fires))

            st.divider()

            # Summary report ---------------------------------------------------
            st.markdown("##### 📝 Summary report")
            with st.container(border=True):
                st.markdown(report.summary_text)

            # Satellite imagery -------------------------------------------------
            st.markdown("##### 🛰️ Latest satellite imagery")
            if report.satellite:
                st.image(report.satellite[0], use_container_width=True,
                         caption=f"NASA GIBS · MODIS Terra true color · {report.satellite[1]} · zoom-8 tile (≈1.2 km/px)")
            else:
                st.warning("No satellite tile available for the last 6 days — try again later.")

            # Nearby survey ------------------------------------------------------
            st.markdown("##### 🌳 Nearby survey (OpenStreetMap)")
            if report.survey and report.survey.features:
                s1, s2 = st.columns([3, 2])
                with s1:
                    st.dataframe(
                        pd.DataFrame([f.to_row() for f in report.survey.features[:25]]),
                        use_container_width=True, hide_index=True,
                    )
                    st.caption(f"Closest {min(25, report.survey.total)} of {report.survey.total} features within {report.survey.radius_m / 1000:.0f} km.")
                with s2:
                    counts_df = pd.Series(report.survey.counts, name="Features").sort_values(ascending=False)
                    st.bar_chart(counts_df, height=300)
                    st.caption("Feature counts by category — the raw census behind the green score.")
            elif report.survey:
                st.info(report.survey.note or "No tagged green/land features found in this radius.")
            else:
                st.info("OpenStreetMap survey unavailable right now (rate limit) — the rest of the report is unaffected.")

            # Nearby images ------------------------------------------------------
            st.markdown("##### 🖼️ Nearby geotagged photos")
            if report.images:
                for row_start in range(0, len(report.images), 4):
                    cols = st.columns(4)
                    for col, im in zip(cols, report.images[row_start:row_start + 4]):
                        with col:
                            if im.thumb_url:
                                st.image(im.thumb_url, use_container_width=True, caption=im.title[:48])
                                if im.page_url:
                                    st.markdown(f"<span style='font-size:0.8em'>[open on Wikipedia]({im.page_url})</span>", unsafe_allow_html=True)
                            else:
                                st.caption(im.title[:48])
            else:
                st.info("No geotagged Wikipedia photos within 10 km of this location.")

            # Fire hotspots ------------------------------------------------------
            st.markdown("##### 🔥 Active fire hotspots")
            if report.fires:
                st.dataframe(pd.DataFrame(report.fires), use_container_width=True, hide_index=True)
                st.caption(report.fires_note)
            else:
                st.caption(report.fires_note)

            st.download_button(
                "⬇️ Download real-time report (JSON)",
                data=json.dumps(report.to_dict(), indent=2),
                file_name=f"realtime_{place.name.lower().replace(' ', '_')}.json",
                mime="application/json",
            )

# ---------------------------------------------------------------------------
# Page 6 — Run history
# ---------------------------------------------------------------------------
else:
    st.title("📚 Run history")
    st.markdown(
        "Every pipeline run — from this dashboard and from the CLI (`demo_run.py`) — lands in "
        "`outputs/decision_logs/`. The JSON files are the machine-readable audit artifacts; "
        "this page is the human-readable view over them."
    )

    history = st.session_state.history + load_history_from_disk()
    if not history:
        st.info("No runs recorded yet.")
    else:
        # Deduplicate (session runs are also saved to disk) and sort newest first.
        seen, unique = set(), []
        for r in history:
            if r["run_id"] not in seen:
                seen.add(r["run_id"])
                unique.append(r)
        history = sorted(unique, key=lambda r: r["started_at"], reverse=True)

        rows = [
            {
                "Run ID": r["run_id"],
                "Region": r["region_name"],
                "Started": r["started_at"][:19].replace("T", " "),
                "Final status": r["final_status"],
                "Boundaries": r.get("boundary_count", 0),
                "Steps": len(r.get("steps", [])),
            }
            for r in history
        ]
        df = pd.DataFrame(rows)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Final status": st.column_config.TextColumn("Final status"),
            },
        )

        # Confidence over time
        st.markdown("##### Confidence over time")
        conf_rows = []
        for r in history:
            score = None
            for s in r.get("steps", []):
                if s["step_name"] == "confidence_gate":
                    text = s.get("summary", "")
                    # Gate summaries read "Confidence 0.596 ≥ threshold 0.600 — …"
                    for token in text.replace("≥", " ").replace("BELOW", " ").split():
                        if (token.startswith("0.") or token.startswith("1.")) and len(token) >= 5:
                            try:
                                score = float(token)
                                break
                            except ValueError:
                                continue
            if score is not None:
                conf_rows.append({"Run": r["run_id"], "Confidence": score})
        if conf_rows:
            st.bar_chart(pd.DataFrame(conf_rows).set_index("Run"), height=250)
        else:
            st.caption("No confidence scores recorded in these runs.")

        # Per-run drill-down
        st.markdown("##### Inspect a run")
        run_choice = st.selectbox(
            "Run",
            [f"{r['run_id']} — {r['final_status'].upper()}" for r in history],
        )
        chosen = history[[f"{r['run_id']} — {r['final_status'].upper()}" for r in history].index(run_choice)]
        render_trail(chosen)
