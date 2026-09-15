import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from app.services.ai.client import OllamaStructuredClient


def create_workspace(client):
    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": f"Clinic {uuid.uuid4().hex[:8]}",
            "description": (
                "Hospital appointment platform. The platform integrates with Twilio "
                "for reminders."
            ),
            "business_context": "Replace the paper appointment book used by three clinics.",
            "constraints": [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def apply_edit(client, workspace_id, **edit):
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/edits",
        json={"use_ai": False, **edit},
    )
    assert response.status_code == 200, response.text
    return response.json()["workspace"]


SEED_REQUIREMENTS = [
    "Patients can book an appointment with a doctor.",
    "Patients can view their past appointment history.",
    "Receptionists can reschedule an appointment for a patient.",
    "Doctors can review a patient record before an appointment.",
    "Administrators can export a monthly clinic report.",
]


def seeded_workspace(client):
    """A workspace with a realistic model.

    With Ollama disabled the conservative analyser produces a single
    requirement, so the tests build the model up through the same validated
    edit pipeline a user would.
    """
    workspace = create_workspace(client)
    workspace_id = workspace["id"]
    for value in SEED_REQUIREMENTS:
        workspace = apply_edit(
            client,
            workspace_id,
            target_type="functional_requirement",
            operation="add",
            value=value,
        )
    workspace = apply_edit(
        client,
        workspace_id,
        target_type="actor",
        operation="add",
        value={"name": "Patient", "description": "Books and reviews appointments."},
    )
    workspace = apply_edit(
        client,
        workspace_id,
        target_type="non_functional_requirement",
        operation="add",
        value="Appointment history must stay accurate after a reschedule.",
    )
    return workspace


@contextmanager
def forbid_ollama():
    """Fail loudly if the guarded turn reaches the model.

    Every behaviour in this module is meant to be deterministic, so a
    regression that pushes one of these turns back to Ollama is a latency
    regression. The guard covers only the chat call — building and applying a
    workspace legitimately uses the model.
    """

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("this turn must not call Ollama")

    with patch.object(OllamaStructuredClient, "generate", fail_if_called):
        yield


def chat(client, workspace_id, message, **extra):
    with forbid_ollama():
        response = client.post(
            f"/api/v1/workspaces/{workspace_id}/architecture-chat",
            json={"message": message, "history": [], **extra},
        )
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------- questions


def test_listing_a_collection_is_deterministic(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "list the functional requirements")
    assert reply["type"] == "question"
    assert "5 functional requirements" in reply["answer"]
    assert "FR-001" in reply["answer"]
    assert reply["proposal"] is None


def test_counting_a_collection_uses_the_singular_when_there_is_one(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "how many actors are there")
    assert "1 actor." in reply["answer"]


def test_what_actors_do_we_have_is_answered_from_the_model(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "what actors do we have")
    assert "ACTOR-001" in reply["answer"]


def test_overview_reports_the_canonical_model(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "give me an overview of this project")
    assert reply["type"] == "question"
    assert "Canonical model:" in reply["answer"]
    assert "Recommended architecture:" in reply["answer"]


def test_explain_traces_a_requirement_through_the_causal_graph(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "why does FR-004 exist")
    assert reply["type"] == "question"
    assert "FR-004 states" in reply["answer"]
    assert reply["proposal"] is None


# ------------------------------------------------------------- suggestions


def test_missing_actors_are_suggested_with_evidence(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "suggest missing actors")
    answer = reply["answer"]
    # Receptionist, Doctor and Administrator all operate the system in the
    # seeded requirements but only Patient is recorded as an actor.
    assert "Receptionist" in answer
    assert "Doctor" in answer
    assert "Evidence: FR-" in answer
    assert reply["recommendations"]


def test_suggestions_are_not_repeated_for_actors_already_recorded(client):
    workspace = seeded_workspace(client)
    workspace = apply_edit(
        client,
        workspace["id"],
        target_type="actor",
        operation="add",
        value={"name": "Receptionist", "description": "Manages the clinic calendar."},
    )
    reply = chat(client, workspace["id"], "suggest missing actors")
    assert "Add the Receptionist actor" not in reply["answer"]
    assert "Doctor" in reply["answer"]


def test_quality_gaps_are_raised_as_questions_not_invented_targets(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "what quality requirements am I missing")
    assert reply["type"] == "question"
    assert reply["proposal"] is None
    # A question, never a fabricated number.
    assert "%" not in reply["answer"]


def test_no_grounded_gap_is_reported_honestly(client):
    workspace = create_workspace(client)
    reply = chat(client, workspace["id"], "suggest missing integrations")
    assert reply["type"] == "question"
    assert "grounded gap" in reply["answer"]


# ------------------------------------------------------------------ changes


def test_delete_by_description_resolves_to_one_requirement(client):
    workspace = seeded_workspace(client)
    reply = chat(
        client, workspace["id"], "remove the requirement about exporting the monthly report"
    )
    assert reply["type"] == "architecture_change"
    action = reply["proposal"]["project_actions"][0]
    assert action["action"] == "delete_requirement"
    assert action["target_id"] == "FR-005"
    assert reply["proposal"]["auto_apply_safe"] is False

    applied = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat/apply",
        json={"proposal": reply["proposal"]},
    )
    assert applied.status_code == 200, applied.text
    remaining = applied.json()["workspace"]["requirements"]["functional_requirements"]
    assert "Administrators can export a monthly clinic report." not in remaining


def test_ambiguous_delete_asks_instead_of_guessing(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "delete the appointment requirement")
    assert reply["type"] == "question"
    assert reply["proposal"] is None
    assert "matches more than one item" in reply["answer"]
    assert len(reply["recommendations"]) > 1


def test_unknown_reference_is_reported_not_invented(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "delete the billing reconciliation workflow")
    assert reply["type"] == "question"
    assert reply["proposal"] is None
    assert "nothing in the canonical model matches" in reply["answer"]


def test_reword_updates_the_requirement_through_a_project_action(client):
    workspace = seeded_workspace(client)
    reply = chat(
        client,
        workspace["id"],
        "change FR-002 to say patients can view and filter their appointment history",
    )
    assert reply["type"] == "architecture_change"
    action = reply["proposal"]["project_actions"][0]
    assert action["action"] == "update_requirement"
    assert action["target_id"] == "FR-002"
    assert action["requirement_type"] == "functional_requirement"
    assert "filter" in action["value"]

    applied = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat/apply",
        json={"proposal": reply["proposal"]},
    )
    assert applied.status_code == 200, applied.text
    functional = applied.json()["workspace"]["requirements"]["functional_requirements"]
    assert any("filter" in item for item in functional)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "we need doctors to be able to add clinical notes",
            "Doctors can add clinical notes",
        ),
        (
            "the system should send an SMS reminder before an appointment",
            "The system should send an SMS reminder before an appointment",
        ),
    ],
)
def test_requirements_stated_as_a_need_are_captured_verbatim(client, message, expected):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], message)
    assert reply["type"] == "architecture_change"
    assert reply["proposal"]["requirement_additions"] == [
        {"target_type": "functional_requirement", "text": expected}
    ]

    applied = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat/apply",
        json={"proposal": reply["proposal"]},
    )
    assert applied.status_code == 200, applied.text
    assert expected in applied.json()["workspace"]["requirements"]["functional_requirements"]


def test_duplicate_need_is_refused(client):
    workspace = seeded_workspace(client)
    reply = chat(
        client, workspace["id"], "we need patients to be able to book an appointment with a doctor"
    )
    assert reply["type"] == "question"
    assert "already covers that" in reply["answer"]


def test_connector_words_are_not_stored_as_requirement_text(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "add a non functional requirement for audit logging")
    assert reply["proposal"]["requirement_additions"] == [
        {"target_type": "non_functional_requirement", "text": "Audit logging"}
    ]


# ---------------------------------------------------------------- behaviour


def test_vague_change_still_asks_for_the_missing_numbers(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "Improve scalability")
    assert reply["type"] == "question"
    assert reply["proposal"] is None


def test_deterministic_turns_never_reach_the_model(client):
    workspace = seeded_workspace(client)
    for message in (
        "list the functional requirements",
        "how many NFRs are there",
        "what actors do we have",
        "give me an overview",
        "why does FR-001 exist",
        "suggest missing actors",
        "what am I missing",
        "delete FR-003",
        "remove the requirement about exporting the monthly report",
        "change FR-001 to say patients can book an appointment online",
        "we need nurses to be able to update vitals",
    ):
        reply = chat(client, workspace["id"], message)
        assert reply["answer"], message


# ------------------------------------------------------------------ renames


RENAME_PHRASINGS = [
    "change the name of actor Patient to Client",
    "rename actor Patient to Client",
    "rename the Patient actor to Client",
    "change Patient's name to Client",
    "rename Patient to Client",
    "call the Patient actor Client instead",
]


@pytest.mark.parametrize("message", RENAME_PHRASINGS)
def test_every_natural_rename_phrasing_is_deterministic(client, message):
    """The reported bug: only two of these six phrasings used to be understood.

    "change the name of actor driver to user" fell through to the model and
    came back as a timeout notice with no change prepared.
    """
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], message)
    assert reply["type"] == "architecture_change", message
    action = reply["proposal"]["project_actions"][0]
    assert action["action"] == "update_actor"
    assert action["target_id"] == "ACTOR-001"
    assert action["value"]["name"] == "Client"


def test_rename_preserves_every_other_recorded_fact(client):
    workspace = create_workspace(client)
    workspace = apply_edit(
        client,
        workspace["id"],
        target_type="actor",
        operation="add",
        value={
            "name": "Driver",
            "description": "Accepts and completes rides.",
            "responsibilities": ["Accept ride requests", "Complete trips"],
            "permissions": ["ride:accept"],
        },
    )
    reply = chat(client, workspace["id"], "change the name of actor Driver to Captain")
    value = reply["proposal"]["project_actions"][0]["value"]
    assert value["name"] == "Captain"
    assert value["description"] == "Accepts and completes rides."
    assert value["responsibilities"] == ["Accept ride requests", "Complete trips"]
    assert value["permissions"] == ["ride:accept"]
    # The rename records why it happened rather than dropping traceability.
    assert any(
        item["source_id"] == "AI-USER-RENAME" for item in value["source_evidence"]
    )

    applied = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat/apply",
        json={"proposal": reply["proposal"]},
    )
    assert applied.status_code == 200, applied.text
    actors = applied.json()["workspace"]["requirements"]["actors"]
    renamed = next(actor for actor in actors if actor["name"] == "Captain")
    assert renamed["responsibilities"] == ["Accept ride requests", "Complete trips"]


def test_a_lowercase_new_name_is_title_cased(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "change the name of actor patient to user")
    assert reply["proposal"]["project_actions"][0]["value"]["name"] == "User"


def test_deliberate_casing_in_a_new_name_is_kept(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "rename actor Patient to iOS Client")
    assert reply["proposal"]["project_actions"][0]["value"]["name"] == "iOS Client"


def test_renaming_a_domain_entity_works_too(client):
    workspace = seeded_workspace(client)
    workspace = apply_edit(
        client,
        workspace["id"],
        target_type="domain_entity",
        operation="add",
        value={"name": "Visit", "description": "One clinic attendance.", "attributes": ["id"]},
    )
    reply = chat(client, workspace["id"], "change the name of entity Visit to Encounter")
    action = reply["proposal"]["project_actions"][0]
    assert action["action"] == "update_entity"
    assert action["value"]["name"] == "Encounter"
    assert action["value"]["attributes"] == ["id"]


def test_renaming_to_an_existing_name_is_refused(client):
    workspace = seeded_workspace(client)
    workspace = apply_edit(
        client,
        workspace["id"],
        target_type="actor",
        operation="add",
        value={"name": "Receptionist", "description": "Manages the calendar."},
    )
    reply = chat(client, workspace["id"], "rename actor Patient to Receptionist")
    assert reply["type"] == "question"
    assert reply["proposal"] is None
    assert "already exists" in reply["answer"]


def test_renaming_to_the_same_name_changes_nothing(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "rename actor Patient to Patient")
    assert reply["type"] == "question"
    assert reply["proposal"] is None
    assert "already named" in reply["answer"]


def test_renaming_something_that_does_not_exist_says_so(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "rename actor Courier to Runner")
    assert reply["type"] == "question"
    assert reply["proposal"] is None
    # The message names only the collection the user named.
    assert "no actor named 'Courier'" in reply["answer"]
    # It reports what does exist, under the right label.
    assert "Actors: Patient." in reply["answer"]


def test_renaming_without_naming_a_collection_searches_both(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "rename Courier to Runner")
    assert reply["type"] == "question"
    assert reply["proposal"] is None
    assert "no actor or domain entity named 'Courier'" in reply["answer"]


def test_fallback_explains_itself_and_offers_usable_commands(client, monkeypatch):
    """Even the give-up path must be useful rather than internal jargon."""
    workspace = seeded_workspace(client)
    monkeypatch.setattr(
        OllamaStructuredClient, "generate", lambda *_args, **_kwargs: None
    )
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={"message": "Discuss the least obvious tension in this design.", "history": []},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "no change was applied" in body["answer"]
    assert "response budget" not in body["answer"]
    assert body["recommendations"]
    assert any("rename" in item or "change the name" in item for item in body["recommendations"])
