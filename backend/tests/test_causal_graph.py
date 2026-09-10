from app.schemas.domain import (
    Actor,
    CausalGraph,
    CausalGraphNode,
    DomainEntityHint,
    DomainWorkflowHint,
    RequirementModel,
)
from app.services.causal_graph import CausalGraphService
from app.services.requirement_analyzer import RequirementAnalyzer


def _uncatalogued_requirements() -> RequirementModel:
    return RequirementModel(
        summary="A field observation coordination system.",
        domain="Uncatalogued field observation coordination",
        scale_profile="unknown",
        functional_requirements=[
            "Field operators can record observations from remote instruments.",
            "Supervisors can view live instrument locations on a map.",
            "Operators can review the processing history for an observation.",
        ],
        non_functional_requirements=[
            "Observation history must be auditable.",
            "The required availability target is unknown and must be clarified.",
        ],
        actors=[
            Actor(name="Field operator", description="Records remote observations."),
            Actor(name="Supervisor", description="Coordinates active field work."),
        ],
        domain_entities=[
            DomainEntityHint(
                name="Observation",
                description="A reading recorded from a remote instrument.",
            ),
            DomainEntityHint(
                name="Instrument",
                description="A remote instrument with a changing location.",
            ),
        ],
        domain_workflows=[
            DomainWorkflowHint(
                name="Record observations",
                description="Field operators can record observations from remote instruments.",
                primary_actor="Field operator",
                related_entities=["Observation", "Instrument"],
            ),
            DomainWorkflowHint(
                name="View instrument locations",
                description="Supervisors can view live instrument locations on a map.",
                primary_actor="Supervisor",
                related_entities=["Instrument"],
            ),
            DomainWorkflowHint(
                name="Review observation history",
                description="Operators can review the processing history for an observation.",
                primary_actor="Field operator",
                related_entities=["Observation"],
            ),
        ],
        constraints=[],
        assumptions=[],
        integrations=[],
        data_characteristics=["Location observations change while instruments are active."],
        open_questions=["What availability target is required?"],
        analysis_source="ollama-pretrained",
    )


def _create_uncatalogued_workspace(client, monkeypatch):
    requirements = _uncatalogued_requirements()
    monkeypatch.setattr(
        RequirementAnalyzer,
        "analyze",
        lambda self, **kwargs: requirements.model_copy(deep=True),
    )
    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": "Field Observations",
            "description": "Coordinate remote field observations without assuming a deployment scale.",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_unknown_domain_graph_serializes_and_traces_requirements(client, monkeypatch):
    workspace = _create_uncatalogued_workspace(client, monkeypatch)
    graph = CausalGraph.model_validate(workspace["causal_graph"])

    node_ids = [node.id for node in graph.nodes]
    edge_ids = [edge.id for edge in graph.edges]
    assert len(node_ids) == len(set(node_ids))
    assert len(edge_ids) == len(set(edge_ids))
    assert all(
        edge.source_node_id in node_ids and edge.target_node_id in node_ids
        for edge in graph.edges
    )
    assert any(node.id.startswith("TECH-DATA-") for node in graph.nodes)
    assert any(
        edge.source_node_id.startswith("NFR-")
        and edge.relationship == "satisfies"
        and edge.target_node_id.startswith("DEC-")
        for edge in graph.edges
    )

    graph_response = client.get(
        f"/api/v1/workspaces/{workspace['id']}/causal-graph"
    )
    assert graph_response.status_code == 200
    assert graph_response.json()["version"] == "6"
    assert not any(
        "evaluated against FR-" in edge.reason for edge in graph.edges
    )

    api_node = next(node for node in graph.nodes if node.type == "api")
    assert api_node.metadata["endpoint_details"]
    assert all(
        {"method", "path", "purpose", "auth_required"}.issubset(endpoint)
        for endpoint in api_node.metadata["endpoint_details"]
    )
    requirement_by_id = {
        node.id: node
        for node in graph.nodes
        if node.type in {"functional_requirement", "non_functional_requirement", "constraint"}
    }
    for candidate in (node for node in graph.nodes if node.type == "api"):
        linked_requirements = [
            requirement_by_id[edge.source_node_id]
            for edge in graph.edges
            if edge.target_node_id == candidate.id
            and edge.source_node_id in requirement_by_id
        ]
        linked_ids = {item.id for item in linked_requirements}
        explicit_ids = {
            requirement_id
            for endpoint in candidate.metadata["endpoint_details"]
            for requirement_id in endpoint["requirement_ids"]
            if requirement_id in requirement_by_id
        }
        assert explicit_ids
        assert explicit_ids <= linked_ids

    component = next(
        node for node in graph.nodes if node.type in {"architecture_component", "service_module"}
    )
    trace_response = client.get(
        f"/api/v1/workspaces/{workspace['id']}/causal-graph/nodes/{component.id}"
    )
    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["why_it_exists"]
    assert any(item["type"] == "functional_requirement" for item in trace["requirements"])

    linked_api = next(
        node
        for node in graph.nodes
        if node.type == "api"
        and any(
            edge.target_node_id == node.id
            and edge.source_node_id.startswith(("FR-", "NFR-", "CON-"))
            for edge in graph.edges
        )
    )
    api_trace_response = client.get(
        f"/api/v1/workspaces/{workspace['id']}/causal-graph/nodes/{linked_api.id}"
    )
    assert api_trace_response.status_code == 200
    api_trace = api_trace_response.json()
    assert api_trace["requirements"]
    assert all(item["name"] for item in api_trace["requirements"])


def test_nfr_reaches_architecture_decision_and_orphans_are_detected(client, monkeypatch):
    workspace = _create_uncatalogued_workspace(client, monkeypatch)
    graph = CausalGraph.model_validate(workspace["causal_graph"])
    service = CausalGraphService()

    selected_decision = next(
        node
        for node in graph.nodes
        if node.type == "architecture_decision" and node.metadata.get("recommended")
    )
    supporting_ids = {
        node.id for node in service.requirements_for_component(graph, selected_decision.id)
    }
    assert "NFR-001" in supporting_ids
    assert "NFR-002" in supporting_ids
    assert graph.orphan_node_ids == []

    graph.nodes.append(
        CausalGraphNode(
            id="CMP-ORPHAN",
            type="architecture_component",
            name="Unjustified component",
            description="A deliberately disconnected test component.",
            source="test",
        )
    )
    assert "CMP-ORPHAN" in service.find_orphan_components(graph)


def test_change_impact_uses_causal_nodes_and_persists_adr(client, monkeypatch):
    workspace = _create_uncatalogued_workspace(client, monkeypatch)
    initial_adr_count = len(workspace["adrs"])

    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/changes",
        json={"change_request": "Allow supervisors to export selected observation history."},
    )
    assert response.status_code == 200
    changed = response.json()
    impact = changed["impact_history"][-1]

    assert changed["requirements"]["functional_requirements"][-1] == (
        "Allow supervisors to export selected observation history."
    )
    assert impact["directly_affected_node_ids"]
    assert impact["affected_artifacts"]
    assert impact["impacted_modules"][0] == "requirements"
    assert "recommendation" in impact["impacted_modules"]
    assert len(changed["adrs"]) == initial_adr_count + 1
    assert any(node["type"] == "adr" for node in changed["causal_graph"]["nodes"])
    assert "## Requirement-to-Architecture Traceability" in changed["documentation_markdown"]
