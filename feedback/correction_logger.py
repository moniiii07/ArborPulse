"""Persist human feedback for ArborPulse screening results.

Two compatible interfaces are retained: Member B's ``CorrectionLogger`` for
the decision trail and the dashboard's richer ``log_review`` outcomes.
Both append JSON Lines locally, ready for later analysis or model retraining.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

DEFAULT_LOG_PATH = "feedback/correction_log.jsonl"
VALID_OUTCOMES = {
    "confirmed_forest_loss",
    "seasonal_change",
    "fire_or_burn_scar",
    "agriculture_or_harvest",
    "false_alarm",
    "needs_more_evidence",
}


@dataclass
class Correction:
    run_id: str
    region_name: str
    system_confidence: float
    system_verdict: str
    human_verdict: str
    reviewer_notes: str = ""
    logged_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CorrectionLogger:
    """Member B's append-only decision-trail correction log."""

    def __init__(self, log_path: str = DEFAULT_LOG_PATH):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_correction(
        self, run_id: str, region_name: str, system_confidence: float,
        system_verdict: str, human_verdict: str, reviewer_notes: str = "",
    ) -> Correction:
        correction = Correction(
            run_id, region_name, system_confidence, system_verdict, human_verdict, reviewer_notes
        )
        with self.log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(asdict(correction)) + "\n")
        return correction

    def get_all_corrections(self) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        with self.log_path.open(encoding="utf-8") as log_file:
            return [json.loads(line) for line in log_file if line.strip()]

    def summary_stats(self) -> dict[str, int]:
        corrections = self.get_all_corrections()
        stats = {"total": len(corrections), "confirmed_change": 0, "false_positive": 0, "uncertain": 0}
        for correction in corrections:
            verdict = correction.get("human_verdict", "uncertain")
            if verdict in stats:
                stats[verdict] += 1
        return stats


def log_review(
    *, handoff_path: str, region: str, pipeline_status: str, outcome: str,
    note: str = "", output_path: str | Path = "outputs/reviews/reviews.jsonl",
) -> Path:
    """Append a dashboard review outcome; feedback is local and excluded from Git."""
    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"Unknown review outcome: {outcome}")
    record: dict[str, Any] = {
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "handoff_path": handoff_path,
        "region": region,
        "pipeline_status": pipeline_status,
        "outcome": outcome,
        "note": note.strip(),
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as review_file:
        review_file.write(json.dumps(record) + "\n")
    return destination


def get_reviews(path: str | Path = "outputs/reviews/reviews.jsonl") -> list[dict[str, Any]]:
    """Return newest dashboard review records first; tolerate a missing log."""
    source = Path(path)
    if not source.exists():
        return []
    with source.open(encoding="utf-8") as review_file:
        records = [json.loads(line) for line in review_file if line.strip()]
    return list(reversed(records))
