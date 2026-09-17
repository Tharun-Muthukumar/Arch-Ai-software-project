"""What makes a generated prototype usable rather than merely present.

Each test here corresponds to a defect found by reading a real generated
prototype for an EV charging project, not to a hypothetical.
"""

import uuid

import pytest

SEED = [
    "Drivers can search for nearby charging stations.",
    "Drivers can reserve an available connector.",
    "Operators can update charger availability.",
    "Drivers can pay for a completed charging session.",
]

SYSTEM_COLUMNS = {"Id", "Created At", "Updated At", "Deleted At", "Version"}


@pytest.fixture
def prototype(client):
    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": f"ChargeltReserve {uuid.uuid4().hex[:6]}",
            "description": (
                "EV charging booking platform. Drivers find stations and reserve "
                "connectors. Operators manage charger availability."
            ),
            "business_context": "One traceable booking and charging workflow.",
            "constraints": [],
        },
    )
    assert response.status_code == 201, response.text
    workspace = response.json()
    for value in SEED:
        result = client.post(
            f"/api/v1/workspaces/{workspace['id']}/edits",
            json={
                "use_ai": False,
                "target_type": "functional_requirement",
                "operation": "add",
                "value": value,
            },
        )
        assert result.status_code == 200, result.text
        workspace = result.json()["workspace"]
    assert workspace["prototype"], "a seeded project must produce a prototype"
    return workspace["prototype"]


def test_every_screen_is_traceable_to_a_requirement(prototype):
    for screen in prototype["screens"]:
        assert screen["source_requirement_ids"], screen["name"]


def test_every_screen_is_traceable_to_an_actor(prototype):
    """The role filter in the UI is only real if screens carry actors."""
    for screen in prototype["screens"]:
        assert screen["actor_ids"], screen["name"]


def test_input_screens_never_ask_for_system_columns(prototype):
    """A form asking someone to type an Id or an Updated At is not a form."""
    for screen in prototype["screens"]:
        for component in screen["components"]:
            if component["component_type"] not in {"form", "search"}:
                continue
            offending = SYSTEM_COLUMNS & set(component["fields"])
            assert not offending, f"{screen['name']}: {sorted(offending)}"


def test_a_foreign_key_is_offered_as_the_thing_it_references(prototype):
    """`station_id` is chosen from a picker, so it reads as "Station"."""
    labels = {
        field
        for screen in prototype["screens"]
        for component in screen["components"]
        for field in component["fields"]
    }
    assert not any(label.endswith(" Id") for label in labels), sorted(labels)


def test_a_search_screen_has_something_to_filter_on(prototype):
    """Search used to be excluded from field derivation entirely."""
    search = [
        component
        for screen in prototype["screens"]
        for component in screen["components"]
        if component["component_type"] == "search"
    ]
    if not search:
        pytest.skip("this project produced no search screen")
    for component in search:
        assert component["fields"], "a search screen with no filters is a fake"


def test_action_labels_read_as_actions_not_as_requirements(prototype):
    """"Operators manage charger availability" is a requirement, not a button."""
    labels = [
        action["label"]
        for screen in prototype["screens"]
        for component in screen["components"]
        for action in component["actions"]
    ]
    assert labels
    for label in labels:
        first = label.split()[0].casefold()
        assert first not in {
            "operators", "drivers", "users", "customers", "admins", "staff",
        }, label
        # A bare topic is never a button label.
        assert label.casefold() != "ev charging booking platform", label


def test_prototype_roles_are_unique(prototype):
    actor_ids = [role["actor_id"] for role in prototype["roles"]]
    assert len(actor_ids) == len(set(actor_ids)), actor_ids


def test_screens_reference_only_declared_roles(prototype):
    declared = {role["actor_id"] for role in prototype["roles"]}
    for screen in prototype["screens"]:
        unknown = set(screen["actor_ids"]) - declared
        assert not unknown, f"{screen['name']} references {sorted(unknown)}"


# ------------------------------------------------------------- screen composition
# A screen with a single component is a control, not a page. A search box with
# no result list, or a booking form with nothing showing what is being booked
# and no sense of the lifecycle, is what made the prototype feel unfinished.


def test_every_requirement_screen_is_composed_of_more_than_one_component(prototype):
    for screen in prototype["screens"][1:]:  # the overview is a single hero
        assert len(screen["components"]) >= 2, (
            f"{screen['name']} has only {len(screen['components'])} component"
        )


def test_a_search_screen_shows_results_beside_its_filters(prototype):
    for screen in prototype["screens"]:
        types = [component["component_type"] for component in screen["components"]]
        if "search" not in types:
            continue
        assert "list" in types or "cards" in types or "table" in types, types


def test_the_booking_screen_has_a_form_a_summary_and_a_lifecycle(prototype):
    booking = next(
        (screen for screen in prototype["screens"] if screen["name"] == "Bookings"), None
    )
    if booking is None:
        pytest.skip("this project produced no booking screen")
    types = {component["component_type"] for component in booking["components"]}
    assert "form" in types, types
    assert "details" in types, types
    assert "timeline" in types, types


def test_the_primary_action_on_a_screen_is_actually_an_action(prototype):
    """FR-001 is a topic, so its label falls back to "Open". A topic must not
    outrank a real capability for the primary button."""
    for screen in prototype["screens"][1:]:
        actions = screen["components"][0]["actions"]
        if len(actions) < 2:
            continue
        assert actions[0]["label"] != "Open", (
            f"{screen['name']} leads with a fallback label while a real action exists"
        )


def test_a_lifecycle_strip_does_not_claim_domain_statuses(prototype):
    """`states` holds interface states (Loading/Empty/Error), never domain
    statuses, so the panel must not be titled as though it did."""
    for screen in prototype["screens"]:
        for component in screen["components"]:
            if component["component_type"] != "timeline":
                continue
            title = component["title"].casefold()
            for claim in ("reservation status", "order status", "session timeline"):
                assert claim not in title, component["title"]


def test_composed_components_carry_requirement_traceability(prototype):
    for screen in prototype["screens"][1:]:
        for component in screen["components"]:
            assert component["source_requirement_ids"], (
                f"{screen['name']} / {component['title']}"
            )


# ----------------------------------------------------- entity reference accuracy


def test_a_column_named_after_another_entity_becomes_a_foreign_key(client):
    """`charging.booking` was a VARCHAR holding a reference as free text."""
    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": f"RefCheck {uuid.uuid4().hex[:6]}",
            "description": (
                "EV charging booking platform. Drivers find stations and reserve "
                "connectors. Operators manage charger availability."
            ),
            "business_context": "One traceable booking and charging workflow.",
            "constraints": [],
        },
    )
    assert response.status_code == 201, response.text
    entities = {
        entity["name"]: entity
        for entity in response.json()["database_design"]["entities"]
    }
    for name, entity in entities.items():
        others = set(entities) - {name}
        singulars = {other.rstrip("s") for other in others} | others
        for field in entity["fields"]:
            if field["name"].endswith("_id") or field["name"] == "id":
                continue
            assert field["name"] not in singulars, (
                f"{name}.{field['name']} names another entity but is "
                f"{field['data_type']}, not a foreign key"
            )


def test_no_entity_pair_references_itself_in_both_directions(client):
    """Two inference paths each producing a foreign key for the same pair draws
    a cycle in the ER and class diagrams."""
    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": f"CycleCheck {uuid.uuid4().hex[:6]}",
            "description": (
                "EV charging booking platform. Drivers find stations and reserve "
                "connectors. Operators manage charger availability."
            ),
            "business_context": "One traceable booking and charging workflow.",
            "constraints": [],
        },
    )
    assert response.status_code == 201, response.text
    pairs = set()
    for relation in response.json()["database_design"]["relationships"]:
        forward = (relation["source"], relation["target"])
        assert tuple(reversed(forward)) not in pairs, forward
        pairs.add(forward)
