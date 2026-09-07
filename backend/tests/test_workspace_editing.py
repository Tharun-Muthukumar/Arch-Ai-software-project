import uuid


def create_workspace(client):
    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": f"Edit Workspace {uuid.uuid4().hex[:8]}",
            "description": (
                "Build an EV charging station booking platform with station discovery, "
                "live charger availability, bookings, payments, and operator controls."
            ),
            "business_context": "Keep requirements and implementation artifacts traceable.",
            "constraints": [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_requirement_preview_apply_ai_fallback_and_undo_redo(client):
    workspace = create_workspace(client)
    workspace_id = workspace["id"]
    edit = {
        "target_type": "functional_requirement",
        "operation": "add",
        "value": "Drivers can see charger location and availability live.",
        "use_ai": True,
        "expected_updated_at": workspace["updated_at"],
    }

    preview_response = client.post(
        f"/api/v1/workspaces/{workspace_id}/edits/preview", json=edit
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["suggestion"]["source"] == "deterministic-fallback"
    assert any(
        "Real-time" in item for item in preview["suggestion"]["inferred_characteristics"]
    )
    assert any(
        "Geospatial" in item for item in preview["suggestion"]["inferred_characteristics"]
    )
    assert any(item["area"] == "API" for item in preview["impact"]["items"])

    apply_response = client.post(
        f"/api/v1/workspaces/{workspace_id}/edits",
        json={**preview["edit"], "use_ai": False},
    )
    assert apply_response.status_code == 200, apply_response.text
    changed = apply_response.json()["workspace"]
    assert edit["value"] in changed["requirements"]["functional_requirements"]
    assert changed["can_undo"] is True
    assert changed["causal_graph"]["nodes"]
    assert "Drivers can see charger location" in changed["documentation_markdown"]
    assert "charger" in changed["diagrams"]["use_case"]["mermaid"]
    assert "location" in changed["diagrams"]["use_case"]["mermaid"]

    undo = client.post(f"/api/v1/workspaces/{workspace_id}/edits/undo")
    assert undo.status_code == 200, undo.text
    undone = undo.json()["workspace"]
    assert edit["value"] not in undone["requirements"]["functional_requirements"]
    assert "Drivers can see charger" not in undone["diagrams"]["use_case"]["mermaid"]
    assert undone["can_redo"] is True

    redo = client.post(f"/api/v1/workspaces/{workspace_id}/edits/redo")
    assert redo.status_code == 200, redo.text
    redone = redo.json()["workspace"]
    assert edit["value"] in redone["requirements"]["functional_requirements"]


def test_api_database_deployment_and_visual_edits_are_validated(client):
    workspace = create_workspace(client)
    workspace_id = workspace["id"]
    first_endpoint = workspace["api_design"]["groups"][0]["endpoints"][0]
    duplicate_endpoint = {
        **first_endpoint,
        "service": workspace["architectures"][0]["components"][0]["name"],
        "requirement_ids": ["FR-001"],
    }
    duplicate = client.post(
        f"/api/v1/workspaces/{workspace_id}/edits",
        json={
            "target_type": "api_endpoint",
            "operation": "add",
            "parent_id": "0",
            "value": duplicate_endpoint,
        },
    )
    assert duplicate.status_code == 422
    assert "Duplicate API endpoint" in duplicate.text

    entity = workspace["database_design"]["entities"][0]
    entity["description"] = "Updated through the canonical data editor."
    data_edit = client.post(
        f"/api/v1/workspaces/{workspace_id}/edits",
        json={
            "target_type": "database_entity",
            "operation": "update",
            "target_id": "ENTITY-001",
            "value": entity,
        },
    )
    assert data_edit.status_code == 200, data_edit.text
    assert (
        data_edit.json()["workspace"]["database_design"]["entities"][0]["description"]
        == entity["description"]
    )

    deployment = data_edit.json()["workspace"]["deployment_plan"]
    deployment.update(
        {
            "replicas": 3,
            "regions": ["user-selected-region"],
            "deployment_strategy": "Rolling",
        }
    )
    deployment_edit = client.post(
        f"/api/v1/workspaces/{workspace_id}/edits",
        json={
            "target_type": "deployment",
            "operation": "update",
            "target_id": "deployment",
            "value": deployment,
        },
    )
    assert deployment_edit.status_code == 200, deployment_edit.text
    assert deployment_edit.json()["workspace"]["deployment_plan"]["replicas"] == 3

    visual_edit = client.post(
        f"/api/v1/workspaces/{workspace_id}/edits",
        json={
            "target_type": "diagram_layout",
            "operation": "update",
            "target_id": "component",
            "value": {"note": "Move the ownership boundary closer to its client."},
        },
    )
    assert visual_edit.status_code == 200, visual_edit.text
    body = visual_edit.json()
    assert body["workspace"]["diagram_layouts"]["component"]["note"]
    assert body["impact"]["items"][0]["level"] == "visual"


def test_edit_rejects_stale_workspace_version(client):
    workspace = create_workspace(client)
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/edits/preview",
        json={
            "target_type": "constraint",
            "operation": "add",
            "value": "Must preserve the audit trail.",
            "expected_updated_at": "2020-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 409
    assert "changed after you opened" in response.text
