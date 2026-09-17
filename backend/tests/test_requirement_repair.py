"""Repairing extraction artifacts in a project that already exists.

A requirement model is persisted when a project is created and is then edited
by the user, so unlike the diagrams it is never re-derived on read. That means
a fix to requirement extraction cannot reach a project created before it — the
user applies an upgrade, reloads their project and sees the same wrong diagram,
which reads as "nothing was fixed".

These tests cover the explicit path for that: detection must be precise enough
that it never touches a real requirement or a real actor, the repair must be
undoable, and it must rebuild everything downstream.
"""

import pytest

from app.schemas.domain import Actor, RequirementModel
from app.services.requirement_repair import (
    _actor_is_artifact,
    detect_requirement_artifacts,
    remove_requirement_artifacts,
)

BRIEF = (
    "EV charging station booking platform for fast-growing metro cities in India. "
    "Drivers discover nearby stations, reserve charging slots, pay securely, cancel "
    "bookings and request refunds. Operators control station and charger "
    "availability. Admins review analytics."
)


def workspace_payload(**overrides):
    payload = {
        "title": "ChargeltReserve",
        "description": BRIEF,
        "business_context": (
            "Station discovery, slot reservations, secure payment, cancellation and "
            "refund flows with operator controls and admin analytics."
        ),
        "constraints": [],
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------- detection


@pytest.mark.parametrize(
    "name",
    [
        "USER",        # normalizes to nothing: a generic noun, not a role
        "USERS",
        "user",
        "Sso Admin",   # an access mechanism is not part of a job title
        "SSO Admin",
        "Rbac Admin",
        "Oidc Operator",
        "Mfa User",
        "",
    ],
)
def test_a_non_role_actor_name_is_detected(name):
    assert _actor_is_artifact(name)


@pytest.mark.parametrize(
    "name",
    [
        "Driver",
        "Operator",
        # "Admin" stays: a brief that says "Admins review analytics" names a
        # real doer, and the name alone is not evidence of an artifact.
        "Admin",
        "ADMIN",
        "Warehouse Staff",
        "Payment Gateway",
        "Compliance Officer",
        "Delivery Partner",
        "Fraud Analyst",
        "Pharmacist",
    ],
)
def test_a_real_actor_is_not_detected(name):
    assert not _actor_is_artifact(name)


def test_the_briefs_own_title_sentence_is_detected_as_a_requirement(client):
    workspace = client.post("/api/v1/workspaces", json=workspace_payload()).json()
    requirements = RequirementModel.model_validate(workspace["requirements"])
    title = "EV charging station booking platform for fast-growing metro cities in India."
    requirements.functional_requirements = [title, *requirements.functional_requirements]

    found = detect_requirement_artifacts(requirements, BRIEF)
    assert found.title_requirements == [title]
    assert found.count == 1


def test_a_requirement_the_user_wrote_is_never_detected(client):
    """Detection matches the brief's opening sentence verbatim, so a
    requirement the user wrote is safe even if it reads like a description."""
    workspace = client.post("/api/v1/workspaces", json=workspace_payload()).json()
    requirements = RequirementModel.model_validate(workspace["requirements"])
    requirements.functional_requirements = [
        "An EV charging platform for metro cities must support slot booking.",
        "Station discovery for nearby charging stations.",
        *requirements.functional_requirements,
    ]
    found = detect_requirement_artifacts(requirements, BRIEF)
    assert found.title_requirements == []


def test_a_freshly_generated_project_has_no_artifacts(client):
    """The fixes are upstream, so a new project must come out clean — otherwise
    this repair would be papering over a live extraction bug."""
    workspace = client.post("/api/v1/workspaces", json=workspace_payload()).json()
    found = detect_requirement_artifacts(
        RequirementModel.model_validate(workspace["requirements"]),
        workspace["original_prompt"],
    )
    assert found.count == 0, found.summary()
    assert not any(
        issue["code"] == "requirement-extraction-artifact"
        for issue in workspace["consistency_issues"]
    )


def test_a_single_sentence_brief_is_never_stripped(client):
    """With one sentence, removing it would leave nothing at all."""
    requirements = RequirementModel.model_validate(
        client.post(
            "/api/v1/workspaces", json=workspace_payload()
        ).json()["requirements"]
    )
    requirements.functional_requirements = ["Freight logistics platform."]
    found = detect_requirement_artifacts(requirements, "Freight logistics platform.")
    assert found.title_requirements == []


# ---------------------------------------------------------------------- removal


def test_removal_keeps_the_workflow_and_drops_only_the_actor_reference(client):
    workspace = client.post("/api/v1/workspaces", json=workspace_payload()).json()
    requirements = RequirementModel.model_validate(workspace["requirements"])
    requirements.actors = [
        Actor(
            id="ACT-000",
            name="Sso Admin",
            description="SSO administrator.",
            actor_type="human",
            responsibilities=["Manages single sign-on."],
        ),
        *requirements.actors,
    ]
    if requirements.domain_workflows:
        requirements.domain_workflows[0].primary_actor = "Sso Admin"
    workflow_count = len(requirements.domain_workflows)

    found = detect_requirement_artifacts(requirements, BRIEF)
    repaired = remove_requirement_artifacts(requirements, found)

    assert "Sso Admin" not in {actor.name for actor in repaired.actors}
    # The workflow is real; only its actor attribution was wrong.
    assert len(repaired.domain_workflows) == workflow_count
    if workflow_count:
        assert repaired.domain_workflows[0].primary_actor == ""


def test_removal_is_a_copy_and_leaves_the_original_alone(client):
    workspace = client.post("/api/v1/workspaces", json=workspace_payload()).json()
    requirements = RequirementModel.model_validate(workspace["requirements"])
    requirements.actors = [
        Actor(id="ACT-000", name="USER", description="Platform user.", actor_type="human"),
        *requirements.actors,
    ]
    found = detect_requirement_artifacts(requirements, BRIEF)
    remove_requirement_artifacts(requirements, found)
    assert "USER" in {actor.name for actor in requirements.actors}


# ----------------------------------------------------------------- the action


@pytest.fixture
def damaged(client, db_session):
    """A workspace in the state a project created by an older version is in."""
    from app.models.workspace import Workspace

    workspace = client.post("/api/v1/workspaces", json=workspace_payload()).json()
    record = db_session.get(Workspace, workspace["id"])
    stored = dict(record.requirements_json)
    stored["functional_requirements"] = [
        "EV charging station booking platform for fast-growing metro cities in India.",
        *stored["functional_requirements"],
    ]
    stored["actors"] = [
        {
            "id": "ACT-000",
            "name": "USER",
            "description": "Platform user.",
            "actor_type": "human",
            "responsibilities": ["Uses the platform."],
            "permissions": [],
            "source_evidence": [],
        },
        {
            "id": "ACT-00X",
            "name": "Sso Admin",
            "description": "SSO administrator.",
            "actor_type": "human",
            "responsibilities": ["Manages single sign-on."],
            "permissions": [],
            "source_evidence": [],
        },
        *stored["actors"],
    ]
    # Replaced rather than mutated in place: mutating the nested dict leaves
    # object identity unchanged, so SQLAlchemy never marks the row dirty and
    # the commit is a no-op.
    record.requirements_json = stored
    db_session.commit()
    return workspace["id"]


def test_the_project_reports_its_own_artifacts(client, damaged):
    workspace = client.get(f"/api/v1/workspaces/{damaged}").json()
    issue = next(
        issue for issue in workspace["consistency_issues"]
        if issue["code"] == "requirement-extraction-artifact"
    )
    assert "USER" in issue["message"]
    assert "Sso Admin" in issue["message"]
    assert "project description" in issue["message"]


def test_preview_describes_the_repair_without_applying_it(client, damaged):
    response = client.post(
        f"/api/v1/workspaces/{damaged}/project-actions/preview",
        json={"action": {"action": "repair_requirement_model"}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["impact"]["requires_confirmation"] is True
    unchanged = client.get(f"/api/v1/workspaces/{damaged}").json()
    assert "USER" in {actor["name"] for actor in unchanged["requirements"]["actors"]}


def test_the_repair_removes_the_artifacts_and_rebuilds_downstream(client, damaged):
    response = client.post(
        f"/api/v1/workspaces/{damaged}/project-actions",
        json={"action": {"action": "repair_requirement_model"}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    workspace = body["workspace"]

    names = {actor["name"] for actor in workspace["requirements"]["actors"]}
    assert "USER" not in names and "Sso Admin" not in names
    assert "Driver" in names
    assert not any(
        "booking platform for fast-growing" in requirement
        for requirement in workspace["requirements"]["functional_requirements"]
    )
    assert not any(
        issue["code"] == "requirement-extraction-artifact"
        for issue in workspace["consistency_issues"]
    )
    # The diagrams are derived, so they must no longer reference the removed
    # actors either.
    model = workspace["diagrams"]["use_case"]["use_case_model"]
    assert "Sso Admin" not in {actor["name"] for actor in model["actors"]}
    declared = {actor["id"] for actor in model["actors"]}
    for use_case in model["use_cases"]:
        for actor_id in use_case["actor_ids"]:
            assert actor_id in declared
    assert body["impact"]["affected_artifacts"]


def test_the_repair_can_be_undone(client, damaged):
    client.post(
        f"/api/v1/workspaces/{damaged}/project-actions",
        json={"action": {"action": "repair_requirement_model"}},
    )
    response = client.post(
        f"/api/v1/workspaces/{damaged}/project-actions",
        json={"action": {"action": "undo"}},
    )
    assert response.status_code == 200, response.text
    restored = response.json()["workspace"]["requirements"]["actors"]
    assert "USER" in {actor["name"] for actor in restored}


def test_repairing_a_clean_project_changes_nothing(client):
    workspace = client.post("/api/v1/workspaces", json=workspace_payload()).json()
    before = workspace["requirements"]["functional_requirements"]
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/project-actions",
        json={"action": {"action": "repair_requirement_model"}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["workspace"]["requirements"]["functional_requirements"] == before
    assert body["impact"]["affected_artifacts"] == []
    assert "no extraction artifacts" in body["message"].casefold()
