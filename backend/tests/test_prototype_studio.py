import uuid

from app.core.database import SessionLocal
from app.models.workspace import Workspace
from app.services.ai.client import OllamaStructuredClient


def create_workspace(client, *, title: str, description: str):
    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": f"{title} {uuid.uuid4().hex[:8]}",
            "description": description,
            "business_context": "Keep every generated artifact traceable to validated project facts.",
            "constraints": [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def project_action(client, workspace, action):
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/project-actions",
        json={"action": action, "expected_updated_at": workspace["updated_at"]},
    )
    assert response.status_code == 200, response.text
    return response.json()["workspace"]


def test_prototype_is_domain_specific_interactive_and_traceable(client):
    workspace = create_workspace(
        client,
        title="EV charging booking",
        description=(
            "Drivers can find nearby charging stations on a map, filter connector types, "
            "reserve an available charging slot, pay for the reservation, and monitor the "
            "charging session with live status updates. Station operators manage chargers "
            "and availability."
        ),
    )

    prototype = workspace["prototype"]
    names = {screen["name"] for screen in prototype["screens"]}
    assert {"Explore", "Bookings", "Payments", "Live status"}.issubset(names)
    assert prototype["theme"]["pattern"] == "scheduling"
    assert prototype["theme"]["realtime"] is True
    assert prototype["roles"]
    assert any(
        action["action_type"] == "navigate" and action["target_screen_id"]
        for screen in prototype["screens"]
        for component in screen["components"]
        for action in component["actions"]
    )
    assert all(
        requirement_id.startswith(("FR-", "NFR-"))
        for screen in prototype["screens"]
        for requirement_id in screen["source_requirement_ids"]
    )
    graph = workspace["causal_graph"]
    assert any(node["type"] == "prototype_screen" for node in graph["nodes"])
    assert any(edge["target_node_id"].startswith("PROTO-SCREEN-") for edge in graph["edges"])


def test_niche_domain_prototype_does_not_fall_back_to_generic_commerce(client):
    workspace = create_workspace(
        client,
        title="Cryogenic specimen custody",
        description=(
            "Lab custodians register cryogenic specimen aliquots, scan tamper-evident seals "
            "at freezer handoffs, record thaw cycles, reconcile chain-of-custody discrepancies, "
            "and continue working offline inside shielded facilities before synchronizing records."
        ),
    )

    prototype = workspace["prototype"]
    rendered = " ".join(
        [screen["name"] + " " + screen["purpose"] for screen in prototype["screens"]]
        + [
            component["description"] or ""
            for screen in prototype["screens"]
            for component in screen["components"]
        ]
    ).casefold()
    assert "specimen" in rendered
    assert "custody" in rendered or "seal" in rendered
    assert "payments" not in {screen["name"].casefold() for screen in prototype["screens"]}
    assert prototype["theme"]["offline"] is True
    assert any("Offline" in screen["states"] for screen in prototype["screens"])


def test_opening_an_existing_workspace_persists_a_missing_prototype(client):
    workspace = create_workspace(
        client,
        title="Existing booking workspace",
        description="Drivers find charging stations and reserve available charging slots.",
    )
    with SessionLocal() as session:
        record = session.get(Workspace, workspace["id"])
        assert record is not None
        record.prototype_json = {}
        session.commit()

    response = client.get(
        "/api/v1/workspaces",
        params={"active_workspace_id": workspace["id"]},
    )
    assert response.status_code == 200, response.text
    restored = next(item for item in response.json() if item["id"] == workspace["id"])
    assert restored["prototype"]["screens"]

    with SessionLocal() as session:
        persisted = session.get(Workspace, workspace["id"])
        assert persisted is not None
        assert persisted.prototype_json.get("screens")


def test_requirement_actions_synchronize_and_remove_prototype_behavior(client):
    workspace = create_workspace(
        client,
        title="Calibration registry",
        description="Technicians register instruments and review their calibration records.",
    )
    original_count = len(workspace["requirements"]["functional_requirements"])
    unique_requirement = (
        "Field technicians can capture tamper-evident seal handoffs for cryogenic sample transfers."
    )

    changed = project_action(client, workspace, {
        "action": "add_requirement",
        "requirement_type": "functional_requirement",
        "value": unique_requirement,
        "rationale": "Explicit user request.",
    })
    new_id = f"FR-{original_count + 1:03d}"
    assert unique_requirement in changed["requirements"]["functional_requirements"]
    assert any(new_id in screen["source_requirement_ids"] for screen in changed["prototype"]["screens"])

    restored = project_action(client, changed, {
        "action": "delete_requirement",
        "requirement_type": "functional_requirement",
        "target_id": new_id,
        "rationale": "Explicit user request.",
    })
    assert unique_requirement not in restored["requirements"]["functional_requirements"]
    assert all(new_id not in screen["source_requirement_ids"] for screen in restored["prototype"]["screens"])
    assert "tamper-evident" not in " ".join(
        screen["purpose"] for screen in restored["prototype"]["screens"]
    ).casefold()


def test_visual_screen_edit_does_not_mutate_canonical_requirements(client):
    workspace = create_workspace(
        client,
        title="Equipment maintenance",
        description="Maintenance coordinators assign work orders and technicians record inspection results.",
    )
    screen = workspace["prototype"]["screens"][0]
    renamed = {**screen, "name": "Command overview", "visual_overrides": {"name": "Command overview"}}
    changed = project_action(client, workspace, {
        "action": "update_prototype_screen",
        "target_id": screen["id"],
        "value": renamed,
        "rationale": "Visual label refinement only.",
    })

    assert changed["requirements"] == workspace["requirements"]
    assert next(item for item in changed["prototype"]["screens"] if item["id"] == screen["id"])["name"] == "Command overview"
    assert changed["can_undo"] is True

    regenerated = project_action(client, changed, {
        "action": "regenerate_affected",
        "rationale": "Verify visual overrides survive regeneration.",
    })
    assert next(item for item in regenerated["prototype"]["screens"] if item["id"] == screen["id"])["name"] == "Command overview"


def test_actor_action_updates_roles_and_can_be_undone(client):
    workspace = create_workspace(
        client,
        title="Workshop scheduling",
        description="Customers request workshop appointments and coordinators schedule service work.",
    )
    actor_name = "Safety Inspector"
    changed = project_action(client, workspace, {
        "action": "add_actor",
        "value": {
            "name": actor_name,
            "description": "Reviews safety evidence when that responsibility is confirmed.",
            "actor_type": "human",
            "responsibilities": [],
            "permissions": [],
            "source_evidence": [{
                "source_id": "USER-ACTION",
                "source": "Explicit user request",
                "status": "confirmed",
                "excerpt": actor_name,
            }],
        },
        "rationale": "Explicit user request.",
    })
    assert actor_name in {actor["name"] for actor in changed["requirements"]["actors"]}
    assert actor_name in {role["name"] for role in changed["prototype"]["roles"]}

    restored = project_action(client, changed, {"action": "undo", "rationale": "Undo actor addition."})
    assert actor_name not in {actor["name"] for actor in restored["requirements"]["actors"]}


def test_assistant_renames_actor_without_waiting_for_ollama(client, monkeypatch):
    workspace = create_workspace(
        client,
        title="Driver workspace",
        description="Drivers find charging stations and reserve available charging slots.",
    )
    actor = workspace["requirements"]["actors"][0]

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("An exact actor rename must not call Ollama")

    monkeypatch.setattr(OllamaStructuredClient, "generate", fail_if_called)
    proposed = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={
            "message": f"change the actor name {actor['name']} to Charging User",
            "history": [],
        },
    )
    assert proposed.status_code == 200, proposed.text
    proposal = proposed.json()["proposal"]
    assert proposal["project_actions"][0]["action"] == "update_actor"
    assert proposal["project_actions"][0]["value"]["name"] == "Charging User"
    assert proposal["project_actions"][0]["value"]["responsibilities"] == actor["responsibilities"]
    assert proposal["auto_apply_safe"] is True

    applied = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat/apply",
        json={"proposal": proposal},
    )
    assert applied.status_code == 200, applied.text
    changed = applied.json()["workspace"]
    assert "Charging User" in {item["name"] for item in changed["requirements"]["actors"]}
    assert "Charging User" in {item["name"] for item in changed["prototype"]["roles"]}


def test_assistant_proposes_requirement_before_new_functional_screen(client, monkeypatch):
    workspace = create_workspace(
        client,
        title="Fleet workshop",
        description="Dispatchers schedule vehicle inspections and review completed work orders.",
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("A direct typed screen request should not wait for Ollama")

    monkeypatch.setattr(OllamaStructuredClient, "generate", fail_if_called)
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={
            "message": "Add a prototype screen for parts warranty claims",
            "page_context": "/prototype",
            "history": [],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["type"] == "architecture_change"
    assert body["proposal"]["requirement_additions"] == [{
        "target_type": "functional_requirement",
        "text": "Users can access parts warranty claims.",
    }]
    assert body["proposal"]["project_actions"][0]["action"] == "regenerate_affected"
    assert body["proposal"]["auto_apply_safe"] is False


def test_project_action_rejects_stale_workspace_version(client):
    workspace = create_workspace(
        client,
        title="Stale action check",
        description="Operators review equipment inspection records.",
    )
    changed = project_action(client, workspace, {
        "action": "add_requirement",
        "requirement_type": "functional_requirement",
        "value": "Operators can annotate an inspection exception.",
    })
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/project-actions",
        json={
            "action": {
                "action": "add_requirement",
                "requirement_type": "functional_requirement",
                "value": "Operators can close an inspection exception.",
            },
            "expected_updated_at": workspace["updated_at"],
        },
    )
    assert changed["updated_at"] != workspace["updated_at"]
    assert response.status_code == 409


def test_assistant_removes_exact_actor_through_reviewed_typed_action(client, monkeypatch):
    workspace = create_workspace(
        client,
        title="Actor removal",
        description="Dispatchers assign vehicle inspections and technicians record inspection results.",
    )
    actor = workspace["requirements"]["actors"][0]

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("An exact actor deletion should use deterministic project actions")

    monkeypatch.setattr(OllamaStructuredClient, "generate", fail_if_called)
    proposed = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={"message": f"Remove actor {actor['name']}", "history": []},
    )
    assert proposed.status_code == 200, proposed.text
    proposal = proposed.json()["proposal"]
    assert proposal["project_actions"][0]["action"] == "delete_actor"
    assert proposal["auto_apply_safe"] is False

    applied = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat/apply",
        json={"proposal": proposal},
    )
    assert applied.status_code == 200, applied.text
    changed = applied.json()["workspace"]
    assert actor["name"] not in {item["name"] for item in changed["requirements"]["actors"]}
    assert actor["name"] not in {item["name"] for item in changed["prototype"]["roles"]}


def test_selection_aware_api_explanation_uses_current_endpoint(client, monkeypatch):
    workspace = create_workspace(
        client,
        title="Selected API",
        description="Customers create service bookings and view the status of each booking.",
    )
    group_index = next(
        index for index, group in enumerate(workspace["api_design"]["groups"])
        if group["endpoints"]
    )
    endpoint = workspace["api_design"]["groups"][group_index]["endpoints"][0]

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Selected endpoint facts should be answered without Ollama")

    monkeypatch.setattr(OllamaStructuredClient, "generate", fail_if_called)
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={
            "message": "Why is this here?",
            "page_context": "/interfaces",
            "selection": {
                "object_type": "api_endpoint",
                "object_id": f"API-GROUP-{group_index}-ENDPOINT-0",
                "name": f"{endpoint['method']} {endpoint['path']}",
            },
            "history": [],
        },
    )
    assert response.status_code == 200, response.text
    answer = response.json()["answer"]
    assert endpoint["method"] in answer
    assert endpoint["path"] in answer
    assert endpoint["purpose"] in answer


def test_assistant_preserves_exact_user_availability_target(client, monkeypatch):
    workspace = create_workspace(
        client,
        title="Availability update",
        description="Operators review equipment service records.",
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("An exact numeric deployment edit should not use Ollama")

    monkeypatch.setattr(OllamaStructuredClient, "generate", fail_if_called)
    proposed = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={"message": "Set availability to 99.95%", "history": []},
    )
    assert proposed.status_code == 200, proposed.text
    proposal = proposed.json()["proposal"]
    action = proposal["project_actions"][0]
    assert action["action"] == "update_deployment"
    assert action["value"]["availability_target_percent"] == 99.95
    assert proposal["auto_apply_safe"] is False
