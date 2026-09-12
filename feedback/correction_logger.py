"""
correction_logger.py

Stores human corrections on runs SylvaSense/ArborPulse flagged for review
(confidence_gate = "blocked"). This is the "Memory" claim from the pitch:
"a correction log storing human feedback for future retraining." No live
retraining happens (explicitly out of scope for the 30-hour build per the
build doc), but the labeled examples accumulate here as the first real step
toward it — worth saying exactly that in the demo, since it's a true claim,
not an inflated one.

Storage: local JSON Lines (.jsonl) — matches the "Local JSON/CSV, no
database needed at this scale" decision in the tech stack doc. Append-only,
so it's safe against concurrent runs and trivial to inspect or replay later.
"""

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_LOG_PATH = "feedback/correction_log.jsonl"


@dataclass
class Correction:
    run_id: str
    region_name: str
    system_confidence: float
    system_verdict: str          # "blocked" (the only case a correction makes sense for)
    human_verdict: str           # "confirmed_change" | "false_positive" | "uncertain"
    reviewer_notes: str = ""
    logged_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CorrectionLogger:
    def __init__(self, log_path: str = DEFAULT_LOG_PATH):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_correction(
        self,
        run_id: str,
        region_name: str,
        system_confidence: float,
        system_verdict: str,
        human_verdict: str,
        reviewer_notes: str = "",
    ) -> Correction:
        correction = Correction(
            run_id=run_id,
            region_name=region_name,
            system_confidence=system_confidence,
            system_verdict=system_verdict,
            human_verdict=human_verdict,
            reviewer_notes=reviewer_notes,
        )
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(correction)) + "\n")
        return correction

    def get_all_corrections(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        with open(self.log_path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def summary_stats(self) -> dict:
        """Quick counts — useful for a dashboard panel: 'X corrections logged,
        Y confirmed real changes, Z false positives caught.'"""
        corrections = self.get_all_corrections()
        stats = {"total": len(corrections), "confirmed_change": 0, "false_positive": 0, "uncertain": 0}
        for c in corrections:
            verdict = c.get("human_verdict", "uncertain")
            if verdict in stats:
                stats[verdict] += 1
        return stats


if __name__ == "__main__":
    logger = CorrectionLogger()
    logger.log_correction(
        run_id="run_c093822f",
        region_name="Test Forest Polygon A",
        system_confidence=0.60,
        system_verdict="blocked",
        human_verdict="false_positive",
        reviewer_notes="Shadow from adjacent cloud cover, not real canopy loss.",
    )
    print(logger.summary_stats())
    print(logger.get_all_corrections())