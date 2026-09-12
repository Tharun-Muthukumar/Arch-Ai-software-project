from app.schemas.domain import WorkspaceCreateRequest
from app.services.project_description_analyzer import (
    ProjectDescriptionAnalysisError,
    ProjectDescriptionAnalyzer,
)


class FakeAiClient:
    def __init__(self, result: dict | None) -> None:
        self.result = result
        self.calls: list[tuple[str, dict, dict]] = []

    def generate(self, stage: str, input_data: dict, **kwargs):
        self.calls.append((stage, input_data, kwargs))
        return self.result


def test_analyzer_sends_raw_prompt_to_ollama_and_returns_creation_payload():
    prompt = (
        "Build an observatory scheduling system for university researchers. "
        "The first release supports a national telescope network. It must run on GCP. "
        "Our team has 7 engineers."
    )
    ai_client = FakeAiClient(
        {
            "title": "Observatory Scheduling System",
            "business_context_excerpts": [
                "The first release supports a national telescope network"
            ],
            "explicit_constraint_excerpts": ["It must run on GCP"],
            "preferred_cloud": "GCP",
            "team_size": 7,
        }
    )

    result = ProjectDescriptionAnalyzer(ai_client).analyze(prompt)

    assert result.description == prompt
    assert result.title == "Observatory Scheduling System"
    assert result.business_context == (
        "The first release supports a national telescope network"
    )
    assert result.preferred_cloud == "GCP"
    assert result.constraints == ["It must run on GCP"]
    assert result.team_size == 7
    stage, input_data, kwargs = ai_client.calls[0]
    assert stage == "project-description-extraction"
    assert input_data["raw_requirement"] == prompt
    assert kwargs["response_schema"]


def test_analyzer_discards_unsupported_values_from_model():
    prompt = (
        "Create a marine specimen catalog where researchers record collection notes "
        "and compare taxonomy revisions."
    )
    ai_client = FakeAiClient(
        {
            "title": "Marine Specimen Catalog",
            "business_context_excerpts": ["Global rollout for commercial laboratories"],
            "explicit_constraint_excerpts": ["Must use Kafka"],
            "preferred_cloud": "Azure",
            "team_size": 50,
        }
    )

    result = ProjectDescriptionAnalyzer(ai_client).analyze(prompt)

    assert result.description == prompt
    assert result.business_context is None
    assert result.preferred_cloud is None
    assert result.constraints == []
    assert result.team_size is None


def test_analyze_description_endpoint_returns_existing_workspace_shape(client, monkeypatch):
    prompt = (
        "Build a legal evidence intake portal where case workers upload documents "
        "and record chain-of-custody events."
    )
    expected = WorkspaceCreateRequest(
        title="Legal Evidence Intake",
        description=prompt,
        constraints=[],
    )
    monkeypatch.setattr(
        ProjectDescriptionAnalyzer,
        "analyze",
        lambda self, source: expected,
    )

    response = client.post(
        "/api/v1/workspaces/analyze-description",
        json={"prompt": prompt},
    )

    assert response.status_code == 200
    assert response.json() == expected.model_dump(mode="json")


def test_analyze_description_endpoint_rejects_short_prompt(client):
    response = client.post(
        "/api/v1/workspaces/analyze-description",
        json={"prompt": "Build an app."},
    )

    assert response.status_code == 422
    assert "at least 40 characters and 8 words" in response.text


def test_analyze_description_endpoint_reports_ollama_failure(client, monkeypatch):
    prompt = (
        "Build a field research notebook where ecologists capture observations "
        "and organize specimen photographs."
    )

    def fail_analysis(self, source):
        raise ProjectDescriptionAnalysisError("Ollama analysis is unavailable.")

    monkeypatch.setattr(ProjectDescriptionAnalyzer, "analyze", fail_analysis)
    response = client.post(
        "/api/v1/workspaces/analyze-description",
        json={"prompt": prompt},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Ollama analysis is unavailable."
