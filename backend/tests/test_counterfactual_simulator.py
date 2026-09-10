from copy import deepcopy

import pytest

from app.schemas.domain import Actor, DomainEntityHint, DomainWorkflowHint, RequirementModel
from app.services.requirement_analyzer import RequirementAnalyzer


def _unseen_requirements() -> RequirementModel:
    return RequirementModel(
        summary="An uncatalogued workflow coordinates source records and device observations.",
        domain="Uncatalogued Device Workflow",
        scale_profile="unknown",
        functional_requirements=[
            "Reviewers register source records and reversible procedures.",
            "Device controllers provide environmental observations.",
            "Reviewers pause processing outside a defined operating envelope.",
        ],
        non_functional_requirements=["Maintain tamper-evident record provenance."],
        actors=[
            Actor(name="Reviewer", description="Registers and reviews procedures."),
            Actor(name="Device Controller", description="Provides environmental observations."),
        ],
        domain_entities=[
            DomainEntityHint(name="Source Record", description="Reviewed record."),
            DomainEntityHint(name="Procedure", description="Reversible process definition."),
            DomainEntityHint(name="Process Cycle", description="Controlled process run."),
        ],
        domain_workflows=[
            DomainWorkflowHint(
                name="Register Procedure",
                description="Reviewers register source records and reversible procedures.",
                primary_actor="Reviewer",
                related_entities=["Source Record", "Procedure"],
            ),
            DomainWorkflowHint(
                name="Monitor Process Cycle",
                description="Device controllers provide environmental observations.",
                primary_actor="Device Controller",
                related_entities=["Process Cycle"],
            ),
        ],
        analysis_source="ollama-pretrained",
    )


@pytest.fixture()
def unseen_workspace(client, monkeypatch):
    monkeypatch.setattr(
        RequirementAnalyzer,
        "analyze",
        lambda self, *args, **kwargs: _unseen_requirements(),
    )
    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": "Opaque Workflow",
            "description": "Coordinate reversible procedures and device observations.",
            "constraints": [],
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.parametrize(
    "change",
    [
        {"variable": "expected_users", "original_value": 100_000, "hypothetical_value": 5_000_000},
        {"variable": "availability_percent", "original_value": 99.9, "hypothetical_value": 99.99},
        {"variable": "team_size", "original_value": 15, "hypothetical_value": 5},
        {"variable": "realtime_required", "original_value": False, "hypothetical_value": True},
    ],
)
def test_counterfactual_variables_are_deterministic_and_isolated(client, unseen_workspace, change):
    original = deepcopy(unseen_workspace)
    response = client.post(
        f"/api/v1/workspaces/{unseen_workspace['id']}/counterfactual/simulate",
        json={"changes": [change]},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["changed_variables"][0]["variable"] == change["variable"]
    assert result["before"]["architecture_id"] == unseen_workspace["recommendation"]["recommended_architecture_id"]
    assert len(result["before_ranking"]) == len(unseen_workspace["architectures"])
    assert len(result["after_ranking"]) == len(unseen_workspace["architectures"])
    assert result["recommended_evolution_path"]
    assert result["estimate_notes"]

    persisted = client.get(f"/api/v1/workspaces/{unseen_workspace['id']}").json()
    for field in ("requirements", "architectures", "comparison", "recommendation", "adrs", "causal_graph"):
        assert persisted[field] == original[field]


def test_natural_language_multi_change_detects_conflict_and_traverses_graph(client, unseen_workspace):
    response = client.post(
        f"/api/v1/workspaces/{unseen_workspace['id']}/counterfactual/simulate",
        json={
            "scenario": (
                "What happens if our user base grows from 50K to 2 million, traffic increases 10x, "
                "availability changes from 99.9% to 99.99%, realtime becomes required, "
                "the team size falls from 15 to 5?"
            )
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    variables = {item["variable"] for item in result["changed_variables"]}
    assert {
        "expected_users", "peak_traffic_multiplier", "availability_percent",
        "realtime_required", "team_size",
    }.issubset(variables)
    assert result["directly_affected_node_ids"]
    assert result["indirectly_affected_node_ids"]
    assert result["affected_components"]
    assert result["conflicts"]
    assert any("extract only" in step.casefold() for step in result["recommended_evolution_path"])


def test_unrecognized_scenario_has_no_impact(client, unseen_workspace):
    response = client.post(
        f"/api/v1/workspaces/{unseen_workspace['id']}/counterfactual/simulate",
        json={"scenario": "Change the workshop wall color."},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["changed_variables"] == []
    assert result["before"]["suitability_score"] == result["after"]["suitability_score"]
    assert result["directly_affected_node_ids"] == []
    assert result["recommended_evolution_path"] == [
        "No architecture evolution is justified by the recognized hypothetical changes."
    ]
