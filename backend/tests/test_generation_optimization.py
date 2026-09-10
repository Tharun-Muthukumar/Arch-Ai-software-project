import json
import threading
import uuid
from datetime import datetime, timezone

from app.schemas.domain import WorkspaceCreateRequest
from app.services.generation_runtime import (
    GENERATOR_VERSION,
    PROJECT_GENERATION_CACHE,
    ProjectGenerationCache,
)
from app.services.workspace_orchestrator import WorkspaceOrchestrator


class MemoryRepository:
    def __init__(self):
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


def pharmacy_payload() -> WorkspaceCreateRequest:
    return WorkspaceCreateRequest(
        title="Prescription Operations",
        description=(
            "Build an online pharmacy where customers upload prescriptions, pharmacists "
            "verify them, and delivery partners track fulfilled medicine orders."
        ),
        business_context="Protect prescription data and retain a clear verification trail.",
        constraints=["Prescription verification is required before fulfillment."],
        team_size=12,
    )


def test_unknown_project_uses_one_bundled_llm_call_and_compact_input(monkeypatch):
    PROJECT_GENERATION_CACHE.clear()
    orchestrator = WorkspaceOrchestrator(MemoryRepository())
    calls = []

    def bundled_extraction(stage, input_data, **_kwargs):
        calls.append((stage, input_data))
        return {
            "domain": "Quantum Magnetometer Calibration",
            "summary": "Field technicians calibrate magnetometers and preserve calibration history for laboratory auditors.",
            "functional_requirements": [
                "Field technicians calibrate quantum magnetometers.",
                "Field technicians export calibration certificates to laboratory auditors.",
            ],
            "non_functional_requirements": ["Preserve immutable calibration history."],
            "actors": ["Field technicians"],
            "domain_entities": ["Quantum magnetometers", "Calibration certificates"],
            "domain_workflows": ["Calibrate quantum magnetometers", "Export calibration certificates"],
            "integrations": ["Sensor readings"],
            "data_characteristics": ["Immutable calibration history"],
            "explicit_constraints": [],
            "assumptions": [],
            "open_questions": ["What calibration throughput is required?"],
        }

    monkeypatch.setattr(
        orchestrator.requirement_analyzer.ai_client,
        "generate",
        bundled_extraction,
    )
    workspace = orchestrator.create_workspace(
        WorkspaceCreateRequest(
            title="Quantum magnetometer calibration",
            description=(
                "Field technicians calibrate quantum magnetometers, ingest sensor readings, "
                "and export calibration certificates to laboratory auditors. The software "
                "must preserve immutable calibration history."
            ),
        )
    )

    assert workspace.requirements.domain == "Quantum Magnetometer Calibration"
    assert len(calls) == 1
    assert calls[0][0] == "unknown-domain-requirement-extraction"
    assert set(calls[0][1]) == {"project_id", "raw_requirement"}
    assert "architectures" not in calls[0][1]
    assert "previous_generated_content" not in calls[0][1]


def test_generation_cache_is_project_isolated_and_versioned():
    cache = ProjectGenerationCache(max_entries=8)
    calls = []

    def produce(label):
        calls.append(label)
        return {"owner": label}

    first, first_hit, _ = cache.get_or_compute(
        "project-a", "requirements", {"brief": "same"}, lambda: produce("a")
    )
    repeated, repeated_hit, _ = cache.get_or_compute(
        "project-a", "requirements", {"brief": "same"}, lambda: produce("leak")
    )
    other, other_hit, _ = cache.get_or_compute(
        "project-b", "requirements", {"brief": "same"}, lambda: produce("b")
    )

    assert first == repeated == {"owner": "a"}
    assert other == {"owner": "b"}
    assert (first_hit, repeated_hit, other_hit) == (False, True, False)
    assert calls == ["a", "b"]
    assert GENERATOR_VERSION in cache.key("project-a", "hash", "requirements")


def test_known_domain_uses_no_llm_and_blueprint_does_not_invent_features(monkeypatch):
    PROJECT_GENERATION_CACHE.clear()
    orchestrator = WorkspaceOrchestrator(MemoryRepository())

    def unexpected_llm(*_args, **_kwargs):
        raise AssertionError("Known-domain generation must not call an LLM")

    monkeypatch.setattr(
        orchestrator.requirement_analyzer.ai_client,
        "generate",
        unexpected_llm,
    )
    workspace = orchestrator.create_workspace(pharmacy_payload())
    artifact_text = " ".join(
        [
            *workspace.requirements.functional_requirements,
            *(entity.name for entity in workspace.requirements.domain_entities),
            *(entity.name for entity in workspace.database_design.entities),
            *(endpoint.path for group in workspace.api_design.groups for endpoint in group.endpoints),
        ]
    ).casefold()

    assert workspace.requirements.analysis_source == "predefined-blueprint"
    assert "prescription" in artifact_text
    assert "checkout" not in artifact_text
    assert "payment" not in artifact_text
    assert "notification" not in artifact_text


def test_independent_generation_phases_execute_in_parallel(monkeypatch):
    PROJECT_GENERATION_CACHE.clear()
    orchestrator = WorkspaceOrchestrator(MemoryRepository())
    payload = pharmacy_payload()
    answers = orchestrator._seed_answers(payload)
    requirements = orchestrator.requirement_analyzer.analyze(
        payload.title,
        payload.description,
        payload.business_context,
        answers,
        payload.constraints,
    )

    phase_one_barrier = threading.Barrier(3)
    phase_two_barrier = threading.Barrier(2)
    phase_one_threads = set()
    phase_two_threads = set()

    def parallel_wrapper(original, barrier, seen):
        def wrapped(*args, **kwargs):
            seen.add(threading.get_ident())
            barrier.wait(timeout=2)
            return original(*args, **kwargs)

        return wrapped

    monkeypatch.setattr(
        orchestrator.clarification_engine,
        "generate",
        parallel_wrapper(orchestrator.clarification_engine.generate, phase_one_barrier, phase_one_threads),
    )
    monkeypatch.setattr(
        orchestrator.architecture_generator,
        "generate",
        parallel_wrapper(orchestrator.architecture_generator.generate, phase_one_barrier, phase_one_threads),
    )
    monkeypatch.setattr(
        orchestrator.database_generator,
        "generate",
        parallel_wrapper(orchestrator.database_generator.generate, phase_one_barrier, phase_one_threads),
    )
    monkeypatch.setattr(
        orchestrator.comparison_engine,
        "compare",
        parallel_wrapper(orchestrator.comparison_engine.compare, phase_two_barrier, phase_two_threads),
    )
    monkeypatch.setattr(
        orchestrator.api_generator,
        "generate",
        parallel_wrapper(orchestrator.api_generator.generate, phase_two_barrier, phase_two_threads),
    )

    generated = orchestrator._generate_all(
        payload.title,
        payload.description,
        payload.business_context,
        answers,
        requirements,
        project_id=f"parallel-{uuid.uuid4()}",
    )

    assert len(phase_one_threads) == 3
    assert len(phase_two_threads) == 2
    assert generated["recommendation"].recommended_architecture_id


def test_selective_regeneration_only_runs_affected_dependency_chain(monkeypatch):
    PROJECT_GENERATION_CACHE.clear()
    repository = MemoryRepository()
    orchestrator = WorkspaceOrchestrator(repository)
    created = orchestrator.create_workspace(pharmacy_payload())
    workspace = repository.get(created.id)
    workspace.requirements_json["functional_requirements"].append(
        "Pharmacists archive prescription verification exceptions."
    )

    called = []

    def track(owner, method_name, label):
        original = getattr(owner, method_name)

        def wrapped(*args, **kwargs):
            called.append(label)
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, method_name, wrapped)

    track(orchestrator.clarification_engine, "generate", "clarifications")
    track(orchestrator.architecture_generator, "generate", "architectures")
    track(orchestrator.database_generator, "generate", "database")
    track(orchestrator.comparison_engine, "compare", "comparison")
    track(orchestrator.api_generator, "generate", "api")
    track(orchestrator.recommendation_engine, "recommend", "recommendation")
    track(orchestrator.deployment_generator, "generate", "deployment")
    track(orchestrator.diagram_generator, "generate", "diagrams")

    orchestrator._regenerate_sections(workspace, ["database"])

    assert set(called) == {"database", "api", "diagrams"}


def test_stream_endpoint_emits_progress_and_completion(client):
    response = client.post(
        "/api/v1/workspaces/stream",
        json=pharmacy_payload().model_dump(mode="json"),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: progress" in response.text
    assert "event: complete" in response.text
    complete_block = next(
        block for block in response.text.split("\n\n") if block.startswith("event: complete")
    )
    data = json.loads(next(line[6:] for line in complete_block.splitlines() if line.startswith("data: ")))
    assert data["workspace"]["id"]
    assert data["workspace"]["recommendation"]["recommended_architecture_id"]
    assert data["metrics"]["llm_calls"] == 0

    metrics = client.get(
        f"/api/v1/workspaces/{data['workspace']['id']}/generation-metrics"
    )
    assert metrics.status_code == 200
    assert metrics.json()["generation_time_ms"] >= 0
