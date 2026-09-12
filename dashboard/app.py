"""ArborPulse dashboard: read the real Earth Engine handoff JSON."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

HANDOFF_CANDIDATES = (
    Path("outputs/member_a_handoff.json"),
    Path("../Arborpulse/outputs/member_a_handoff.json"),
)
DEFAULT_HANDOFF = next((path for path in HANDOFF_CANDIDATES if path.exists()), HANDOFF_CANDIDATES[0])
MODEL_EVALUATION = Path("outputs/model_evaluation.json")


def load_handoff(path: Path) -> dict:
    with path.open(encoding="utf-8") as handoff_file:
        return json.load(handoff_file)


st.set_page_config(page_title="ArborPulse", page_icon="🌿", layout="wide")
st.title("🌿 ArborPulse")
st.caption("Explainable vegetation-change screening for the Rondônia pilot area")

path_text = st.sidebar.text_input("Member A handoff JSON", str(DEFAULT_HANDOFF))
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
