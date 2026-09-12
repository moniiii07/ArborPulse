"""
decision_trail.py

Builds the structured, human-readable audit trail — SylvaSense's core novelty
artifact. Every pipeline stage (data fetch, quality check, detection,
calibration, confidence scoring, boundary decisions) appends a DecisionStep
here. The trail is what a judge — or a real MRV auditor — reads to see not
just what SylvaSense concluded, but exactly why, including the moments it
chose not to trust itself.

Two boundary types get a dedicated `is_boundary` flag so the dashboard can
visually highlight them (Boundary #1: retry, Boundary #2: confidence gate).
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional
import json
from pathlib import Path

VALID_STATUSES = {"ok", "retry", "warning", "blocked"}


@dataclass
class DecisionStep:
    step_name: str
    status: str                      # one of VALID_STATUSES
    summary: str                     # one-line, human-readable
    details: dict = field(default_factory=dict)   # structured data for this step
    is_boundary: bool = False        # True for autonomous boundary decisions
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if self.status not in VALID_STATUSES:
            raise ValueError(f"status must be one of {VALID_STATUSES}, got {self.status!r}")


class DecisionTrail:
    def __init__(self, run_id: str, region_name: str):
        self.run_id = run_id
        self.region_name = region_name
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.steps: list[DecisionStep] = []

    def add_step(
        self,
        step_name: str,
        status: str,
        summary: str,
        details: Optional[dict] = None,
        is_boundary: bool = False,
    ) -> DecisionStep:
        step = DecisionStep(
            step_name=step_name,
            status=status,
            summary=summary,
            details=details or {},
            is_boundary=is_boundary,
        )
        self.steps.append(step)
        return step

    def boundary_steps(self) -> list[DecisionStep]:
        return [s for s in self.steps if s.is_boundary]

    def final_status(self) -> str:
        """Blocked wins over warning wins over retry wins over ok — the trail
        reports the most serious thing that happened during the run."""
        priority = {"blocked": 3, "warning": 2, "retry": 1, "ok": 0}
        if not self.steps:
            return "ok"
        return max(self.steps, key=lambda s: priority[s.status]).status

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "region_name": self.region_name,
            "started_at": self.started_at,
            "final_status": self.final_status(),
            "boundary_count": len(self.boundary_steps()),
            "steps": [asdict(s) for s in self.steps],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_markdown(self) -> str:
        """Readable render for the Streamlit dashboard / README screenshots."""
        lines = [
            f"# Decision Trail — {self.region_name}",
            f"Run `{self.run_id}` · started {self.started_at}",
            f"**Final status:** {self.final_status().upper()}"
            f"  ·  **Boundary decisions triggered:** {len(self.boundary_steps())}",
            "",
        ]
        status_icon = {"ok": "✅", "retry": "🔁", "warning": "⚠️", "blocked": "🛑"}
        for i, step in enumerate(self.steps, 1):
            marker = " **[BOUNDARY]**" if step.is_boundary else ""
            lines.append(f"### {i}. {status_icon[step.status]} {step.step_name}{marker}")
            lines.append(step.summary)
            if step.details:
                for k, v in step.details.items():
                    lines.append(f"  - *{k}*: {v}")
            lines.append("")
        return "\n".join(lines)

    def save(self, out_dir: str = "outputs/decision_logs") -> tuple[str, str]:
        """Writes both JSON (machine-readable audit artifact) and Markdown
        (human-readable) versions. Returns (json_path, md_path)."""
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        json_path = f"{out_dir}/{self.run_id}.json"
        md_path = f"{out_dir}/{self.run_id}.md"
        Path(json_path).write_text(self.to_json(), encoding="utf-8")
        Path(md_path).write_text(self.to_markdown(), encoding="utf-8")
        return json_path, md_path


if __name__ == "__main__":
    trail = DecisionTrail(run_id="demo_run_001", region_name="Test Forest Polygon A")
    trail.add_step("fetch_imagery", "ok", "Fetched Sentinel-2 L2A for Date A and Date B.")
    trail.add_step(
        "quality_check", "retry", "Usable-pixel % below threshold on first query — re-queried a nearby date window.",
        details={"initial_usable_pct": 41.2, "retried_usable_pct": 89.6}, is_boundary=True,
    )
    trail.add_step("confidence_gate", "ok", "Confidence 0.78 ≥ threshold 0.60 — alert cleared.", is_boundary=True)
    print(trail.to_markdown())