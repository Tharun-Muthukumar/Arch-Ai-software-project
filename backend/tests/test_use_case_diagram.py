"""UML correctness and traceability for the use case diagram.

Every test here corresponds to a defect found by reading a generated use case
diagram for an EV charging project, not to a hypothetical.
"""

import uuid

import pytest

FRS = [
    "Station discovery for nearby charging stations.",
    "Slot reservations for an available charger.",
    "Secure payment for a completed charging session.",
    "Charging session tracking.",
    "Cancellation of an existing booking.",
    "Refund flows for a cancelled booking.",
    "Driver history of past bookings.",
    "Operator controls for charger availability.",
    "Admin analytics dashboard.",
    "Use email and password for user authentication.",
]
DESCRIPTION = (
    "EV charging station booking platform for fast-growing metro cities in India. "
    "Drivers discover nearby stations, reserve charging slots, pay securely, cancel "
    "bookings and request refunds. Operators control station and charger "
    "availability. Admins review analytics."
)


@pytest.fixture
def workspace(client):
    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": f"ChargeltReserve {uuid.uuid4().hex[:6]}",
            "description": DESCRIPTION,
            "business_context": (
                "Station discovery, slot reservations, secure payment, cancellation and "
                "refund flows with operator controls and admin analytics."
            ),
            "constraints": [],
        },
    )
    assert response.status_code == 201, response.text
    result = response.json()
    for value in FRS:
        edit = client.post(
            f"/api/v1/workspaces/{result['id']}/edits",
            json={
                "use_ai": False,
                "target_type": "functional_requirement",
                "operation": "add",
                "value": value,
            },
        )
        assert edit.status_code == 200, edit.text
        result = edit.json()["workspace"]
    return result


def test_a_structured_use_case_model_is_emitted(workspace):
    """Mermaid cannot draw a stick figure, so the client needs the structure."""
    model = workspace["diagrams"]["use_case"]["use_case_model"]
    assert model is not None
    assert model["system_name"]
    assert model["actors"], "a project with actors must expose them as actors"
    assert model["use_cases"]


def test_every_use_case_label_matches_the_requirement_it_claims(workspace):
    """The regression that mattered most: with 13 requirements the generator
    replaced the twelfth shown with the last in the model, so a node labelled
    FR-012 carried FR-013's text. A diagram that misstates identity is worse
    than one that omits."""
    requirements = workspace["requirements"]["functional_requirements"]
    model = workspace["diagrams"]["use_case"]["use_case_model"]
    for use_case in model["use_cases"]:
        index = int(use_case["requirement_id"].split("-")[1])
        assert 1 <= index <= len(requirements), use_case["requirement_id"]
        true_text = requirements[index - 1].casefold()
        # The label is a cleaned form of the requirement, so compare on the
        # first few significant words rather than demanding equality.
        head = " ".join(use_case["label"].casefold().split()[:3])
        assert head in true_text, (
            f"{use_case['requirement_id']} is labelled {use_case['label']!r} "
            f"but that requirement reads {requirements[index - 1]!r}"
        )


def test_omitted_requirements_are_counted_not_substituted(workspace):
    requirements = workspace["requirements"]["functional_requirements"]
    model = workspace["diagrams"]["use_case"]["use_case_model"]
    assert len(model["use_cases"]) + model["omitted_use_case_count"] == len(requirements)


def test_use_case_ids_are_unique(workspace):
    model = workspace["diagrams"]["use_case"]["use_case_model"]
    ids = [use_case["id"] for use_case in model["use_cases"]]
    assert len(ids) == len(set(ids))


def test_associations_only_reference_declared_actors(workspace):
    model = workspace["diagrams"]["use_case"]["use_case_model"]
    declared = {actor["id"] for actor in model["actors"]}
    for use_case in model["use_cases"]:
        unknown = set(use_case["actor_ids"]) - declared
        assert not unknown, f"{use_case['requirement_id']} references {sorted(unknown)}"


def test_a_requirement_that_names_an_actor_is_associated_with_that_actor(workspace):
    """"Admin analytics dashboard" went to no actor at all, because the score
    was dominated by whichever actor had the longest description."""
    model = workspace["diagrams"]["use_case"]["use_case_model"]
    by_id = {actor["id"]: actor["name"].casefold() for actor in model["actors"]}
    for use_case in model["use_cases"]:
        label = use_case["label"].casefold()
        for actor_id, name in by_id.items():
            if name in label.split():
                assert actor_id in use_case["actor_ids"], (
                    f"{use_case['requirement_id']} names {name} but is not associated with it"
                )


def test_driver_owns_the_driver_facing_use_cases(workspace):
    """Payment, reservation and discovery are the Driver's. They were attached
    to an Admin, and then to nobody, before the scoring was fixed."""
    model = workspace["diagrams"]["use_case"]["use_case_model"]
    driver = next(
        (actor for actor in model["actors"] if actor["name"].casefold() == "driver"), None
    )
    if driver is None:
        pytest.skip("this project extracted no Driver actor")
    owned = {
        use_case["requirement_id"]
        for use_case in model["use_cases"]
        if driver["id"] in use_case["actor_ids"]
    }
    labels = {
        use_case["requirement_id"]: use_case["label"].casefold()
        for use_case in model["use_cases"]
    }
    for requirement_id, label in labels.items():
        if any(word in label for word in ("payment", "reservation", "discovery")):
            assert requirement_id in owned, f"{requirement_id} ({label}) is not the Driver's"


def test_plantuml_uses_native_use_case_notation(workspace):
    """PlantUML does support use case diagrams, so the export should use them:
    `actor` is the stick figure, `usecase` the ellipse, `rectangle` the
    boundary."""
    plantuml = workspace["diagrams"]["use_case"]["plantuml"]
    assert "@startuml" in plantuml and "@enduml" in plantuml
    assert "actor " in plantuml
    assert "usecase " in plantuml
    assert "rectangle " in plantuml


def test_the_mermaid_fallback_still_parses_as_a_flowchart(workspace):
    mermaid = workspace["diagrams"]["use_case"]["mermaid"]
    assert mermaid.startswith("flowchart")
    assert "subgraph" in mermaid, "the system boundary should at least be a subgraph"
    # The brief is not an actor and must not be drawn as one.
    assert "Confirmed project brief" not in mermaid


def test_other_diagram_kinds_do_not_carry_a_use_case_model(workspace):
    for key, artifact in workspace["diagrams"].items():
        if key == "use_case":
            continue
        assert artifact.get("use_case_model") is None, key


# ------------------------------------------------- upgrading an older project
# Diagrams are persisted per workspace. A project created before the use case
# diagram gained UML notation keeps serving its stored artifact, so the user
# sees no change after an upgrade unless the project is recreated.


def test_a_stored_pre_upgrade_use_case_diagram_is_repaired_on_read(client, db_session):
    """Simulates exactly what an existing project holds on disk."""
    from app.models.workspace import Workspace

    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": f"Legacy {uuid.uuid4().hex[:6]}",
            "description": DESCRIPTION,
            "business_context": "Legacy stored diagram check.",
            "constraints": [],
        },
    )
    assert response.status_code == 201, response.text
    workspace_id = response.json()["id"]

    # Overwrite the stored use case diagram with the pre-upgrade shape: a
    # flowchart, the brief drawn as a node, and no structured model.
    row = db_session.query(Workspace).filter(Workspace.id == workspace_id).one()
    stored = dict(row.diagrams_json)
    stored["use_case"] = {
        "title": "Use Case Diagram",
        "description": "Legacy artifact.",
        "mermaid": 'flowchart LR\n    Source["Confirmed project brief"]\n    Source --> FR1',
        "plantuml": "@startuml\n@enduml",
    }
    row.diagrams_json = stored
    db_session.commit()

    reread = client.get(f"/api/v1/workspaces/{workspace_id}")
    assert reread.status_code == 200, reread.text
    use_case = reread.json()["diagrams"]["use_case"]
    assert use_case["use_case_model"] is not None, (
        "a stored diagram with no structured model must be regenerated on read"
    )
    assert "Confirmed project brief" not in use_case["mermaid"]
    assert use_case["use_case_model"]["actors"]


def test_a_current_use_case_diagram_is_not_regenerated_on_read(client, db_session):
    """The repair must not fire for projects that are already current, or
    every read would rebuild a diagram for no reason."""
    from app.models.workspace import Workspace

    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": f"Current {uuid.uuid4().hex[:6]}",
            "description": DESCRIPTION,
            "business_context": "Current stored diagram check.",
            "constraints": [],
        },
    )
    assert response.status_code == 201, response.text
    workspace_id = response.json()["id"]

    row = db_session.query(Workspace).filter(Workspace.id == workspace_id).one()
    stored = dict(row.diagrams_json)
    assert stored["use_case"].get("use_case_model") is not None
    # Mark the stored copy so a regeneration would be detectable. The nested
    # dict has to be replaced rather than mutated: mutating it in place leaves
    # the JSON column's object identity unchanged, so SQLAlchemy never marks
    # the row dirty and the write is silently lost.
    current = dict(stored["use_case"])
    current["description"] = "SENTINEL stored description"
    stored["use_case"] = current
    row.diagrams_json = stored
    db_session.commit()

    reread = client.get(f"/api/v1/workspaces/{workspace_id}")
    assert reread.status_code == 200, reread.text
    assert reread.json()["diagrams"]["use_case"]["description"] == "SENTINEL stored description"
