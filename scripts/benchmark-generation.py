#!/usr/bin/env python3
"""Measure the optimized pipeline and replay the removed legacy LLM stage."""

from __future__ import annotations

import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.schemas.domain import WorkspaceCreateRequest  # noqa: E402
from app.services.ai.client import OllamaStructuredClient  # noqa: E402
from app.services.generation_runtime import (  # noqa: E402
    GENERATION_TELEMETRY,
    PROJECT_GENERATION_CACHE,
)
from app.services.workspace_orchestrator import WorkspaceOrchestrator  # noqa: E402


class MemoryRepository:
    def __init__(self) -> None:
        self.items = {}

    def add(self, workspace):
        now = datetime.now(timezone.utc)
        workspace.created_at = workspace.created_at or now
        workspace.updated_at = workspace.updated_at or now
        self.items[workspace.id] = workspace
        return workspace

    def save(self, workspace):
        workspace.updated_at = datetime.now(timezone.utc)
        self.items[workspace.id] = workspace
        return workspace

    def get(self, workspace_id):
        return self.items.get(workspace_id)

    def list(self):
        return list(self.items.values())


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    PROJECT_GENERATION_CACHE.clear()
    orchestrator = WorkspaceOrchestrator(MemoryRepository())
    payload = WorkspaceCreateRequest(
        title="Quantum magnetometer calibration",
        description=(
            "Field technicians calibrate quantum magnetometers, ingest sensor readings, "
            "and export calibration certificates to laboratory auditors. The software "
            "must preserve immutable calibration history and support bursty overnight "
            "laboratory batches."
        ),
        business_context=(
            "Calibration evidence must remain traceable to the technician and instrument."
        ),
        constraints=["Calibration history must be immutable."],
        team_size=10,
    )
    optimized_project_id = f"benchmark-optimized-{uuid.uuid4()}"
    workspace = orchestrator.create_workspace(
        payload,
        project_id=optimized_project_id,
    )
    optimized = GENERATION_TELEMETRY.snapshot(optimized_project_id) or {}

    # Replay only the LLM stage removed by this refactor. The rest of the
    # reconstructed legacy duration uses the measured section timings from
    # this exact run, summed as they were before parallel execution.
    legacy_project_id = f"benchmark-legacy-{uuid.uuid4()}"
    GENERATION_TELEMETRY.start(legacy_project_id)
    requirements = workspace.requirements
    answers = workspace.answers
    scores = orchestrator.architecture_generator._suitability_scores(requirements, answers)
    deterministic = orchestrator.architecture_generator._deterministic_shortlist(
        requirements, answers
    )
    selection_started = perf_counter()
    OllamaStructuredClient().generate(
        "architecture-selection",
        {
            "project_id": legacy_project_id,
            "domain": requirements.domain,
            "summary": requirements.summary,
            "scale_profile": requirements.scale_profile,
            "candidate_ids": list(scores),
            "candidates": [
                {"id": option_id, "score": round(score, 1)}
                for option_id, score in scores.items()
            ],
            "deterministic_shortlist": deterministic,
            "signals": orchestrator.architecture_generator._signals(requirements, answers),
        },
        response_schema={
            "type": "object",
            "properties": {
                "selected_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "rationale": {"type": "string"},
            },
            "required": ["selected_ids", "rationale"],
        },
        num_predict=220,
        num_ctx=4096,
        minimum_timeout_seconds=60,
    )
    selection_ms = round((perf_counter() - selection_started) * 1000, 2)
    legacy_llm_metrics = GENERATION_TELEMETRY.finish(legacy_project_id)

    section_times = optimized.get("section_times_ms", {})
    phase_one = [section_times.get(name, 0.0) for name in ("clarification", "architectures", "database")]
    phase_two = [section_times.get(name, 0.0) for name in ("comparison", "api")]
    parallel_savings_ms = round(
        (sum(phase_one) - max(phase_one, default=0.0))
        + (sum(phase_two) - max(phase_two, default=0.0)),
        2,
    )
    optimized_ms = float(optimized.get("generation_time_ms", 0.0))
    reconstructed_before_ms = round(
        optimized_ms + selection_ms + parallel_savings_ms,
        2,
    )

    print(
        json.dumps(
            {
                "scenario": "unseen calibration domain",
                "before": {
                    "llm_calls": 2,
                    "generation_time_ms": reconstructed_before_ms,
                    "method": "measured optimized stages serialized + measured removed architecture-selection call",
                },
                "after": {
                    "llm_calls": optimized.get("llm_calls"),
                    "llm_stages": optimized.get("llm_stages"),
                    "generation_time_ms": optimized_ms,
                    "cache_hits": optimized.get("cache_hits"),
                    "cache_misses": optimized.get("cache_misses"),
                },
                "measured_removed_selection_ms": selection_ms,
                "measured_parallel_savings_ms": parallel_savings_ms,
                "legacy_replay_llm_calls": legacy_llm_metrics.get("llm_calls"),
                "quality_counts": {
                    "analysis_source": workspace.requirements.analysis_source,
                    "analysis_warnings": workspace.requirements.analysis_warnings,
                    "functional_requirements": len(workspace.requirements.functional_requirements),
                    "actors": len(workspace.requirements.actors),
                    "entities": len(workspace.database_design.entities),
                    "api_groups": len(workspace.api_design.groups),
                    "architecture_options": len(workspace.architectures),
                    "consistency_issues": len(workspace.consistency_issues),
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
