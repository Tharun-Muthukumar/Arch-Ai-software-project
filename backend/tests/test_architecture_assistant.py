import uuid

import pytest

from app.services.ai.client import OllamaStructuredClient


def create_workspace(client):
    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": f"Assistant Workspace {uuid.uuid4().hex[:8]}",
            "description": (
                "Build an EV charging station booking platform where drivers find stations, "
                "reserve available connectors, pay online, and monitor charging sessions."
            ),
            "business_context": "Operators need one traceable booking and charging workflow.",
            "constraints": [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_architecture_question_does_not_change_workspace(client, monkeypatch):
    workspace = create_workspace(client)
    architecture = workspace["architectures"][0]

    def fake_generate(_self, stage, _input_data, **_kwargs):
        if stage != "architecture-chat":
            return None
        return {
            "type": "question",
            "answer": f"{architecture['components'][0]['name']} is on the current request path.",
            "affected_components": [architecture["components"][0]["name"]],
            "recommendations": ["Measure the path before changing capacity."],
        }

    monkeypatch.setattr(OllamaStructuredClient, "generate", fake_generate)
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={
            "message": "Where is the most concentrated request path?",
            "architecture_id": architecture["id"],
            "history": [],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["type"] == "question"
    assert body["proposal"] is None
    unchanged = client.get(f"/api/v1/workspaces/{workspace['id']}").json()
    assert unchanged["updated_at"] == workspace["updated_at"]
    assert unchanged["architectures"] == workspace["architectures"]


def test_component_ownership_question_is_fast_and_grounded(client, monkeypatch):
    workspace = create_workspace(client)
    architecture = workspace["architectures"][0]
    def component_score(component):
        responsibility = component["responsibility"].casefold()
        interactions = " ".join(component["interactions"]).casefold()
        return sum(
            (3 if token in responsibility else 0) +
            (2 if token in interactions else 0)
            for token in ("charging", "session")
        )

    expected = max(architecture["components"], key=component_score)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Ollama should not be called for a grounded ownership lookup")

    monkeypatch.setattr(OllamaStructuredClient, "generate", fail_if_called)
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={
            "message": "Which component owns charging-session state, and what evidence supports that answer?",
            "architecture_id": architecture["id"],
            "history": [],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["type"] == "question"
    assert body["affected_components"] == [expected["name"]]
    assert expected["name"] in body["answer"]
    assert expected["responsibility"] in body["answer"]
    assert "Identity and Access" not in body["answer"]


def test_vague_quality_change_requests_clarification_without_ollama(client, monkeypatch):
    workspace = create_workspace(client)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Ollama should not be called before critical targets are known")

    monkeypatch.setattr(OllamaStructuredClient, "generate", fail_if_called)
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={"message": "Improve scalability", "history": []},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["type"] == "question"
    assert body["proposal"] is None
    assert "will not invent numeric targets or technologies" in body["answer"]


def test_change_requires_apply_and_rejects_stale_proposal(client, monkeypatch):
    workspace = create_workspace(client)
    architecture = workspace["architectures"][0]
    component = architecture["components"][0]
    updated_component = {
        **component,
        "responsibility": component["responsibility"] + " It also owns validated cache policy.",
    }

    def fake_generate(_self, stage, _input_data, **_kwargs):
        if stage != "architecture-chat":
            return None
        return {
            "type": "architecture_change",
            "answer": "I prepared a focused component update for review.",
            "summary": "Add an explicit cache policy",
            "reasoning": "The requested change is scoped to the selected component.",
            "architecture_changes": [
                {
                    "operation": "update_component",
                    "component_name": component["name"],
                    "component": updated_component,
                }
            ],
            "requirement_additions": [
                {
                    "target_type": "non_functional_requirement",
                    "text": "The architecture must define a validated cache policy.",
                }
            ],
            "affected_components": [component["name"]],
            "recommendations": [],
            "tradeoffs": ["Cache invalidation must be defined."],
            "risk_level": "medium",
        }

    monkeypatch.setattr(OllamaStructuredClient, "generate", fake_generate)
    proposed = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={
            "message": "Add a validated cache policy to this component.",
            "architecture_id": architecture["id"],
            "history": [],
        },
    )
    assert proposed.status_code == 200, proposed.text
    proposal = proposed.json()["proposal"]

    before_apply = client.get(f"/api/v1/workspaces/{workspace['id']}").json()
    assert before_apply["architectures"] == workspace["architectures"]

    applied = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat/apply",
        json={"proposal": proposal},
    )
    assert applied.status_code == 200, applied.text
    changed = applied.json()["workspace"]
    selected = next(item for item in changed["architectures"] if item["id"] == architecture["id"])
    changed_component = next(item for item in selected["components"] if item["name"] == component["name"])
    assert "validated cache policy" in changed_component["responsibility"]
    assert any(
        "validated cache policy" in item
        for item in changed["requirements"]["non_functional_requirements"]
    )
    assert changed["can_undo"] is True
    assert changed["causal_graph"]["nodes"]
    assert changed["documentation_markdown"]

    stale = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat/apply",
        json={"proposal": proposal},
    )
    assert stale.status_code == 409
    assert "changed after you opened" in stale.text


def test_invalid_chat_output_is_handled(client, monkeypatch):
    workspace = create_workspace(client)
    monkeypatch.setattr(
        OllamaStructuredClient,
        "generate",
        lambda _self, stage, _input_data, **_kwargs: (
            {"type": "architecture_change", "answer": "Malformed"}
            if stage == "architecture-chat"
            else None
        ),
    )
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={"message": "Change the current architecture.", "history": []},
    )
    assert response.status_code == 503
    assert "invalid response" in response.text


def test_explicit_replacement_recovers_missing_model_patch_without_applying(client, monkeypatch):
    workspace = create_workspace(client)
    architecture = workspace["architectures"][0]
    existing_value = architecture["components"][0]["name"]
    monkeypatch.setattr(
        OllamaStructuredClient,
        "generate",
        lambda _self, stage, _input_data, **_kwargs: (
            {
                "type": "architecture_change",
                "answer": "The replacement is proposed for review.",
                "risk_level": "medium",
            }
            if stage == "architecture-chat"
            else None
        ),
    )

    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={
            "message": f"Replace {existing_value} with ReplacementStore in the current architecture.",
            "architecture_id": architecture["id"],
            "history": [],
        },
    )

    assert response.status_code == 200, response.text
    proposal = response.json()["proposal"]
    assert proposal["auto_apply_safe"] is True
    assert proposal["architecture_changes"] == [
        {
            "operation": "replace_text",
            "component_name": None,
            "component": None,
            "field": None,
            "from_value": existing_value,
            "to_value": "ReplacementStore",
        }
    ]
    unchanged = client.get(f"/api/v1/workspaces/{workspace['id']}").json()
    assert unchanged["updated_at"] == workspace["updated_at"]
    assert unchanged["architectures"] == workspace["architectures"]


@pytest.mark.parametrize(
    ("message", "target_type", "collection_name", "text"),
    [
        (
            "Add a functional requirement: Operators can export charging reports",
            "functional_requirement",
            "functional_requirements",
            "Operators can export charging reports",
        ),
        (
            "Add an NFR: Charging session updates must remain responsive",
            "non_functional_requirement",
            "non_functional_requirements",
            "Charging session updates must remain responsive",
        ),
        (
            "Add a constraint: Customer data must stay within India",
            "constraint",
            "constraints",
            "Customer data must stay within India",
        ),
        (
            "Add an assumption: Operators provide correct connector status",
            "assumption",
            "assumptions",
            "Operators provide correct connector status",
        ),
    ],
)
def test_explicit_project_item_is_instant_and_applies_through_workspace_editor(
    client, monkeypatch, message, target_type, collection_name, text
):
    workspace = create_workspace(client)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Ollama should not be called for an explicit requirement command")

    monkeypatch.setattr(OllamaStructuredClient, "generate", fail_if_called)
    proposed = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={
            "message": message,
            "history": [],
        },
    )

    assert proposed.status_code == 200, proposed.text
    proposal = proposed.json()["proposal"]
    assert proposal["auto_apply_safe"] is True
    assert proposal["requirement_additions"] == [{
        "target_type": target_type,
        "text": text,
    }]

    applied = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat/apply",
        json={"proposal": proposal},
    )
    assert applied.status_code == 200, applied.text
    collection = applied.json()["workspace"]["requirements"][collection_name]
    assert text in collection


def test_fast_risk_analysis_does_not_call_ollama(client, monkeypatch):
    workspace = create_workspace(client)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Fast risk checks should not call Ollama")

    monkeypatch.setattr(OllamaStructuredClient, "generate", fail_if_called)
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/risk-analysis",
        json={
            "architecture_id": workspace["recommendation"]["recommended_architecture_id"],
            "include_ai": False,
        },
    )
    assert response.status_code == 200, response.text
    assert "Fast structured checks completed" in response.json()["overview"]


def test_image_question_uses_configured_vision_model(client, monkeypatch):
    workspace = create_workspace(client)
    captured = {}
    image_data = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "/x8AAusB9Wl2nWQAAAAASUVORK5CYII="
    )

    def fake_generate(_self, stage, _input_data, **kwargs):
        assert stage == "architecture-image-chat"
        captured.update(kwargs)
        return {
            "answer": "The image shows a project artifact that needs user confirmation.",
            "suggested_item": None,
            "affected_components": [],
        }

    monkeypatch.setattr(OllamaStructuredClient, "generate", fake_generate)
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={
            "message": "Analyze this image without inventing hidden details.",
            "history": [],
            "images": [{
                "name": "diagram.png",
                "media_type": "image/png",
                "data": image_data,
            }],
        },
    )

    assert response.status_code == 200, response.text
    assert captured["model"] == "qwen3-vl:4b-instruct"
    assert "response_schema" not in captured
    assert captured["num_predict"] == 100
    assert captured["images"] == [image_data]


def test_image_derived_project_item_requires_review(client, monkeypatch):
    workspace = create_workspace(client)
    image_data = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "/x8AAusB9Wl2nWQAAAAASUVORK5CYII="
    )

    def fake_generate(_self, stage, input_data, **_kwargs):
        assert stage == "architecture-image-chat"
        assert input_data["requested_item_type"] == "constraint"
        return {
            "answer": "The visible note requires operator approval before tariff changes.",
            "suggested_item": "Operator approval is required before tariff changes",
            "affected_components": [],
        }

    monkeypatch.setattr(OllamaStructuredClient, "generate", fake_generate)
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={
            "message": "Add a constraint from this image",
            "history": [],
            "images": [{
                "name": "note.png",
                "media_type": "image/png",
                "data": image_data,
            }],
        },
    )

    assert response.status_code == 200, response.text
    proposal = response.json()["proposal"]
    assert proposal["auto_apply_safe"] is False
    assert proposal["requirement_additions"] == [{
        "target_type": "constraint",
        "text": "Operator approval is required before tariff changes",
    }]


def test_risk_analysis_filters_unknown_components_and_counts_results(client, monkeypatch):
    workspace = create_workspace(client)
    architecture = next(
        item
        for item in workspace["architectures"]
        if item["id"] == workspace["recommendation"]["recommended_architecture_id"]
    )
    component_name = architecture["components"][0]["name"]

    def fake_generate(_self, stage, _input_data, **_kwargs):
        if stage != "architecture-risk-analysis":
            return None
        return {
            "overview": "The review found one evidence-backed scaling concern.",
            "risks": [
                {
                    "title": "Capacity policy needs verification",
                    "category": "scalability",
                    "severity": "medium",
                    "description": "Potential risk: scaling behavior is not explicit.",
                    "evidence": f"{component_name} has no explicit capacity policy.",
                    "affected_components": [component_name, "Invented Service"],
                    "impact": "Load changes may require manual intervention.",
                    "recommendation": "Define capacity signals after confirming expected load.",
                    "confidence": 0.68,
                    "needs_verification": True,
                },
                {
                    "title": "Operational telemetry is not explicitly represented",
                    "category": "operations",
                    "severity": "medium",
                    "description": "Potential risk: monitoring and tracing are missing.",
                    "evidence": "No explicit observability controls are represented.",
                    "affected_components": [],
                    "impact": "Incidents may be harder to diagnose.",
                    "recommendation": "Add metrics and distributed tracing.",
                    "confidence": 0.7,
                    "needs_verification": True,
                }
            ],
        }

    monkeypatch.setattr(OllamaStructuredClient, "generate", fake_generate)
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/risk-analysis",
        json={"architecture_id": architecture["id"], "include_ai": True},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["analyzed_workspace_updated_at"] == workspace["updated_at"]
    assert all(
        set(risk["affected_components"]).issubset(
            {item["name"] for item in architecture["components"]}
        )
        for risk in result["risks"]
    )
    assert sum(result["summary"].values()) == len(result["risks"])
    assert any(risk["title"] == "Capacity policy needs verification" for risk in result["risks"])
    assert not any(
        risk["title"] == "Operational telemetry is not explicitly represented"
        for risk in result["risks"]
    )
