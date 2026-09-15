"""The assistant as a design partner: reasoning, analysis, simulation, resilience.

``test_assistant_intel`` covers the model of record — listing, adding,
renaming, deleting. This module covers the questions a user actually asks of a
design partner, and the behaviour that has to hold when the model is slow,
absent or wrong.
"""

import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from app.services.ai.client import OllamaStructuredClient

SEED_REQUIREMENTS = [
    "Drivers can search for nearby charging stations.",
    "Drivers can reserve an available connector.",
    "Operators can update charger availability.",
    "Drivers can pay for a completed charging session.",
]


def create_workspace(client):
    response = client.post(
        "/api/v1/workspaces",
        json={
            "title": f"EV Charge {uuid.uuid4().hex[:8]}",
            "description": (
                "EV charging booking platform. Drivers find stations and reserve "
                "connectors. Operators manage charger availability."
            ),
            "business_context": "One traceable booking and charging workflow.",
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


def seeded_workspace(client):
    workspace = create_workspace(client)
    for value in SEED_REQUIREMENTS:
        workspace = apply_edit(
            client,
            workspace["id"],
            target_type="functional_requirement",
            operation="add",
            value=value,
        )
    workspace = apply_edit(
        client,
        workspace["id"],
        target_type="non_functional_requirement",
        operation="add",
        value="Charging session state must remain available during a node restart.",
    )
    return workspace


@contextmanager
def forbid_ollama():
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


# ------------------------------------------------------------------ taxonomy


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("list the functional requirements", "QUESTION"),
        ("how many actors are there", "QUESTION"),
        ("what is an NFR", "EXPLANATION"),
        ("why does FR-002 exist", "EXPLANATION"),
        ("suggest missing actors", "SUGGESTION"),
        ("find problems with my architecture", "ANALYSIS"),
        ("do these APIs cover all FRs", "ANALYSIS"),
        ("where is the single point of failure", "ANALYSIS"),
        ("what happens if traffic increases 10x", "SIMULATION"),
        ("delete FR-002", "ACTION"),
        ("change the name of actor Driver to Rider", "ACTION"),
    ],
)
def test_every_turn_is_classified(client, message, category):
    """The user asked for a taxonomy, and the UI needs it to render properly."""
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], message)
    assert reply["category"] == category, (message, reply["answer"][:120])
    assert reply["resolved_by"] == "deterministic"
    assert reply["elapsed_ms"] >= 0


def test_an_ambiguous_action_is_a_clarification_not_an_action(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "delete the charging requirement")
    assert reply["category"] == "CLARIFICATION"
    assert reply["proposal"] is None
    assert reply["evidence_ids"]


# --------------------------------------------------------------- explanation


def test_concepts_are_defined_and_grounded_in_this_project(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "what is an NFR")
    # A definition, then this project rather than a textbook.
    assert "quality" in reply["answer"].lower()
    assert "in this project" in reply["answer"].lower()


def test_causal_graph_explanation_reports_this_graph(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "explain the causal graph")
    assert "nodes" in reply["answer"]


def test_a_component_that_does_not_exist_is_reported_not_guessed(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "why is Redis here")
    assert "no component called 'Redis'" in reply["answer"]
    # It says what does exist, so the answer is usable.
    assert "Its components are:" in reply["answer"]


def test_a_real_component_is_explained_from_the_project(client):
    workspace = seeded_workspace(client)
    architectures = workspace["architectures"]
    recommended = next(
        item
        for item in architectures
        if item["id"] == workspace["recommendation"]["recommended_architecture_id"]
    )
    component = recommended["components"][0]["name"]
    reply = chat(client, workspace["id"], f"why is {component} here")
    assert component in reply["answer"]
    assert "responsibility" in reply["answer"]


# ------------------------------------------------------------------ analysis


def test_requirement_coverage_is_computed_from_endpoints_and_the_graph(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "do these APIs actually cover all FRs")
    assert reply["category"] == "ANALYSIS"
    assert "functional" in reply["answer"]
    assert "covered" in reply["answer"]


def test_uncovered_requirements_are_named(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "which requirements are not implemented")
    answer = reply["answer"]
    # Either everything is covered, or the uncovered ones are listed by id.
    assert "are covered" in answer or "FR-" in answer


def test_single_point_of_failure_uses_recorded_dependencies(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "where is the single point of failure")
    assert reply["category"] == "ANALYSIS"
    assert "dependents" in reply["answer"] or "no component-to-component" in reply["answer"]


def test_critique_labels_each_finding_by_certainty(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "find problems with my architecture")
    answer = reply["answer"]
    assert reply["category"] == "ANALYSIS"
    # Every finding is labelled so an opinion cannot be mistaken for a fact.
    assert any(
        label in answer
        for label in ("[Confirmed issue]", "[Potential risk]", "[Needs verification]")
    ) or "no evidenced problems" in answer


def test_architecture_choice_is_justified_from_the_scorecards(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "why was this architecture recommended")
    assert "weighted score" in reply["answer"]


def test_unused_technology_question_is_answered_from_the_project(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "do we really need Kafka")
    # Kafka is not in this architecture, and saying so is the correct answer.
    assert "Kafka" in reply["answer"]
    assert reply["proposal"] is None


# ---------------------------------------------------------------- simulation


def test_traffic_simulation_runs_the_counterfactual_engine(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "what happens if traffic increases 10x")
    assert reply["category"] == "SIMULATION"
    assert "simulated" in reply["answer"]
    assert "suitability" in reply["answer"]
    # A simulation must never mutate the project.
    assert reply["proposal"] is None


def test_a_simulation_it_cannot_parse_says_what_it_supports(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "what happens if the weather is bad")
    assert reply["category"] == "SIMULATION"
    assert "could not read a simulable variable" in reply["answer"]
    assert "team size" in reply["answer"]


def test_simulation_does_not_change_the_workspace(client):
    workspace = seeded_workspace(client)
    before = client.get(f"/api/v1/workspaces/{workspace['id']}").json()["updated_at"]
    chat(client, workspace["id"], "what happens at 5 million users")
    after = client.get(f"/api/v1/workspaces/{workspace['id']}").json()["updated_at"]
    assert before == after


# ---------------------------------------------------------------- resilience


def test_the_model_is_retried_then_a_faster_model_is_tried(client, monkeypatch):
    """One controlled retry, then a cheaper model, then a grounded answer."""
    workspace = create_workspace(client)
    attempts: list[tuple[str, int]] = []

    def record_and_fail(_self, _stage, _input, **kwargs):
        attempts.append((kwargs.get("model"), kwargs.get("timeout_seconds")))
        return None

    monkeypatch.setattr(OllamaStructuredClient, "generate", record_and_fail)
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={"message": "Discuss the least obvious tension in this design.", "history": []},
    )
    assert response.status_code == 200, response.text
    assert len(attempts) == 3, attempts
    models = [model for model, _ in attempts]
    assert models[0] == models[1], "the first attempt is retried on the same model"
    assert models[2] != models[0], "the last attempt uses the faster fallback model"
    assert attempts[2][1] < attempts[0][1], "the fallback has a shorter deadline"

    body = response.json()
    assert body["resolved_by"] == "fallback"
    assert body["proposal"] is None
    assert body["recommendations"], "a dead end must still offer something usable"


def test_a_malformed_model_response_never_corrupts_the_project(client, monkeypatch):
    workspace = create_workspace(client)
    before = client.get(f"/api/v1/workspaces/{workspace['id']}").json()["updated_at"]

    monkeypatch.setattr(
        OllamaStructuredClient,
        "generate",
        lambda *_args, **_kwargs: {"unexpected": "shape"},
    )
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={"message": "Discuss the least obvious tension in this design.", "history": []},
    )
    assert response.status_code in {200, 503}, response.text
    after = client.get(f"/api/v1/workspaces/{workspace['id']}").json()["updated_at"]
    assert before == after


def test_a_stale_proposal_is_rejected_rather_than_applied(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "delete FR-002")
    proposal = reply["proposal"]

    # Someone else edits the workspace before the proposal is confirmed.
    apply_edit(
        client,
        workspace["id"],
        target_type="functional_requirement",
        operation="add",
        value="Operators can export a usage report.",
    )
    applied = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat/apply",
        json={"proposal": proposal},
    )
    assert applied.status_code == 409, applied.text


def test_an_unrelated_message_ends_in_a_usable_answer(client, monkeypatch):
    """Nonsense legitimately reaches the model; what matters is where it lands."""
    workspace = seeded_workspace(client)
    monkeypatch.setattr(
        OllamaStructuredClient, "generate", lambda *_args, **_kwargs: None
    )
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={"message": "banana helicopter", "history": []},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["proposal"] is None
    assert body["recommendations"]
    assert "response budget" not in body["answer"]


# ------------------------------------------------------- selection awareness


def test_selection_resolves_this_for_a_requirement(client):
    workspace = seeded_workspace(client)
    reply = chat(
        client,
        workspace["id"],
        "Why is this here?",
        selection={"object_type": "requirement", "object_id": "FR-002"},
    )
    assert "FR-002" in reply["answer"]


def test_a_pronoun_is_never_resolved_as_a_component_name(client):
    """"Why is this here?" with no selection must not invent a component."""
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "Why is this here?")
    assert "no component called 'this'" not in reply["answer"]


# ------------------------------------------------------------- whole journey


def test_question_then_action_then_undo(client):
    """The full loop the user described: ask, act, then reverse it."""
    workspace = seeded_workspace(client)
    workspace_id = workspace["id"]

    asked = chat(client, workspace_id, "suggest missing actors")
    assert asked["category"] == "SUGGESTION"
    assert asked["proposal"] is None, "a suggestion must not silently change anything"

    acted = chat(client, workspace_id, "add an actor called Station Operator")
    assert acted["category"] == "ACTION"
    applied = client.post(
        f"/api/v1/workspaces/{workspace_id}/architecture-chat/apply",
        json={"proposal": acted["proposal"]},
    )
    assert applied.status_code == 200, applied.text
    names = {
        actor["name"]
        for actor in applied.json()["workspace"]["requirements"]["actors"]
    }
    assert "Station Operator" in names

    undone = chat(client, workspace_id, "undo")
    assert undone["proposal"] is not None
    reverted = client.post(
        f"/api/v1/workspaces/{workspace_id}/architecture-chat/apply",
        json={"proposal": undone["proposal"]},
    )
    assert reverted.status_code == 200, reverted.text
    reverted_names = {
        actor["name"]
        for actor in reverted.json()["workspace"]["requirements"]["actors"]
    }
    assert "Station Operator" not in reverted_names


# ------------------------------------------------- conversational phrasing


@pytest.mark.parametrize(
    "message",
    [
        "can you add a functional requirement help center",
        "could you add a functional requirement help center",
        "Please add a functional requirement help center",
        "hey can u add a functional requirement help center",
    ],
)
def test_polite_commands_are_not_pushed_onto_the_model(client, message):
    """The reported bug: a "can you …" wrapper defeated every command pattern.

    Each pattern anchors at the start of the message, so the turn was sent to
    the model as an architecture change and the user watched a spinner for the
    full retry ladder.
    """
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], message)
    assert reply["category"] == "ACTION", message
    assert reply["proposal"]["requirement_additions"] == [
        {"target_type": "functional_requirement", "text": "Help center"}
    ]


def test_politeness_does_not_swallow_a_stated_need(client):
    """"we need X" carries meaning and must survive the stripper."""
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "we need operators to be able to export a report")
    assert reply["proposal"]["requirement_additions"] == [
        {
            "target_type": "functional_requirement",
            "text": "Operators can export a report",
        }
    ]


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("could you please list the actors", "QUESTION"),
        ("can you suggest missing actors", "SUGGESTION"),
        ("would you find problems with my architecture", "ANALYSIS"),
        ("can you delete FR-002", "ACTION"),
    ],
)
def test_politeness_is_stripped_across_every_category(client, message, category):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], message)
    assert reply["category"] == category, (message, reply["answer"][:120])


def test_a_topic_shaped_requirement_is_added_but_flagged(client):
    """Adding "Help center" is honoured, and its weakness is named."""
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "can you add a functional requirement help center")
    assert "names a topic rather than a capability" in reply["answer"]
    # It still proposes the addition rather than refusing or inventing wording.
    assert reply["proposal"]["requirement_additions"][0]["text"] == "Help center"


def test_a_well_formed_requirement_is_not_flagged(client):
    workspace = seeded_workspace(client)
    reply = chat(
        client,
        workspace["id"],
        "add a functional requirement: Drivers can rate a charging session",
    )
    assert "names a topic" not in reply["answer"]


# ------------------------------------------------------------------ budget


def test_a_turn_cannot_outlast_its_total_budget(client, monkeypatch):
    """Retries must not make the worst case longer than one slow attempt.

    Scaled down: the budget and deadlines are shrunk to fractions of a second
    and the fake model always burns its whole deadline, so the assertion is on
    real elapsed time rather than on the numbers the code asked for.
    """
    import time as _time

    from app.services.architecture_assistant import ArchitectureAssistantService

    service = ArchitectureAssistantService()
    settings = service.ai_client.settings
    monkeypatch.setattr(settings, "assistant_total_budget_seconds", 1, raising=False)
    monkeypatch.setattr(settings, "assistant_change_timeout_seconds", 1, raising=False)
    monkeypatch.setattr(settings, "assistant_fallback_timeout_seconds", 1, raising=False)
    monkeypatch.setattr(service, "_MIN_ATTEMPT_SECONDS", 0.2, raising=False)

    def burn_the_deadline(_self, _stage, _input, **kwargs):
        _time.sleep(float(kwargs.get("timeout_seconds") or 0))
        return None

    monkeypatch.setattr(OllamaStructuredClient, "generate", burn_the_deadline)

    began = _time.perf_counter()
    result = service._generate_resilient(
        "architecture-chat",
        {"project_id": "x"},
        response_schema=None,
        num_predict=16,
        num_ctx=512,
        timeout_seconds=settings.assistant_change_timeout_seconds,
        budget_seconds=settings.assistant_total_budget_seconds,
    )
    elapsed = _time.perf_counter() - began

    assert result is None
    # Three attempts at a one-second deadline each would be three seconds; the
    # budget is what stops that.
    assert elapsed <= settings.assistant_total_budget_seconds + 0.6, elapsed


def test_a_timeout_does_not_retry_the_same_model(client, monkeypatch):
    """A model that ran out its clock will do so again; go to the cheap one."""
    import time as _time

    from app.services.architecture_assistant import ArchitectureAssistantService

    service = ArchitectureAssistantService()
    settings = service.ai_client.settings
    monkeypatch.setattr(settings, "assistant_total_budget_seconds", 2, raising=False)
    monkeypatch.setattr(service, "_MIN_ATTEMPT_SECONDS", 0.2, raising=False)
    used: list[str] = []

    def burn_the_deadline(_self, _stage, _input, **kwargs):
        used.append(kwargs.get("model"))
        _time.sleep(float(kwargs.get("timeout_seconds") or 0))
        return None

    monkeypatch.setattr(OllamaStructuredClient, "generate", burn_the_deadline)
    service._generate_resilient(
        "architecture-chat",
        {"project_id": "x"},
        response_schema=None,
        num_predict=16,
        num_ctx=512,
        timeout_seconds=1,
        budget_seconds=2,
    )
    assert used[0] == settings.ollama_assistant_model
    assert len(used) == 2, used
    assert used[1] == settings.assistant_fallback_model


def test_a_fast_failure_does_retry_the_same_model(client, monkeypatch):
    """Malformed output or a dropped connection is worth one more try."""
    from app.services.architecture_assistant import ArchitectureAssistantService

    service = ArchitectureAssistantService()
    settings = service.ai_client.settings
    used: list[str] = []

    def fail_immediately(_self, _stage, _input, **kwargs):
        used.append(kwargs.get("model"))
        return None

    monkeypatch.setattr(OllamaStructuredClient, "generate", fail_immediately)
    service._generate_resilient(
        "architecture-chat",
        {"project_id": "x"},
        response_schema=None,
        num_predict=16,
        num_ctx=512,
        timeout_seconds=5,
        budget_seconds=20,
    )
    assert used[:2] == [settings.ollama_assistant_model, settings.ollama_assistant_model]
    assert used[-1] == settings.assistant_fallback_model


def test_risk_analysis_is_bounded_and_always_returns_findings(client, monkeypatch):
    """Risk analysis used to inherit the global 180s timeout and hang."""
    from app.core.config import get_settings

    requested: list[int] = []

    def record(_self, _stage, _input, **kwargs):
        requested.append(int(kwargs.get("timeout_seconds") or 0))
        return None

    monkeypatch.setattr(OllamaStructuredClient, "generate", record)
    workspace = seeded_workspace(client)
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/risk-analysis",
        json={"include_ai": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # Deterministic findings stand on their own when the model says nothing.
    assert body["risks"], "risk analysis must return the structured findings regardless"
    assert body["overview"]
    budget = get_settings().assistant_risk_budget_seconds
    assert requested, "the AI supplement should have been attempted"
    assert all(deadline <= budget for deadline in requested), requested
    assert max(requested) <= get_settings().assistant_risk_timeout_seconds


def test_risk_analysis_without_ai_never_calls_the_model(client):
    workspace = seeded_workspace(client)
    with forbid_ollama():
        response = client.post(
            f"/api/v1/workspaces/{workspace['id']}/risk-analysis",
            json={"include_ai": False},
        )
    assert response.status_code == 200, response.text
    assert response.json()["risks"]


# ------------------------------------------------------------- full briefing


@pytest.mark.parametrize(
    "message",
    [
        "explain all the fr and etc.. evrything",
        "explain everything",
        "explain evrything",
        "walk me through the project",
        "summarize the whole project",
        "tell me everything about this project",
    ],
)
def test_explain_everything_returns_a_full_briefing(client, message):
    """The reported bug: broad, typo'd requests dead-ended on the model.

    "evrything" is how it was actually typed, so the marker is spelling
    tolerant rather than relying on the user getting it right.
    """
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], message)
    answer = reply["answer"]
    for section in (
        "PROJECT",
        "FUNCTIONAL REQUIREMENTS",
        "NON-FUNCTIONAL REQUIREMENTS",
        "ACTORS",
        "ARCHITECTURE",
        "API",
        "DATABASE",
        "DEPLOYMENT",
        "TRACEABILITY",
        "UNKNOWNS AND OPEN ITEMS",
    ):
        assert section in answer, (message, section)
    # The requirements are read out by identifier, not summarised away.
    assert "FR-001" in answer
    assert reply["proposal"] is None


def test_a_briefing_can_be_scoped_to_the_named_collections(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "explain the api and the database")
    answer = reply["answer"]
    assert "API" in answer
    assert "DATABASE" in answer
    # Sections the user did not ask about are left out.
    assert "FUNCTIONAL REQUIREMENTS" not in answer


def test_one_named_collection_is_still_a_list_not_a_briefing(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "list the actors")
    assert "PROJECT" not in reply["answer"]
    assert reply["category"] == "QUESTION"


# --------------------------------------------------------- retrieval fallback


def test_an_unmatched_question_is_answered_from_the_project(client, monkeypatch):
    """Nothing should dead-end: search the project and report what was found."""
    workspace = seeded_workspace(client)
    monkeypatch.setattr(
        OllamaStructuredClient, "generate", lambda *_args, **_kwargs: None
    )
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={"message": "how does reserving a connector work", "history": []},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["resolved_by"] == "fallback"
    assert "RELATED ITEMS IN" in body["answer"]
    # Real recorded items, cited so the user can follow up on one.
    assert "FR-" in body["answer"] or "component:" in body["answer"]
    assert body["proposal"] is None


def test_a_question_with_nothing_related_says_so_and_offers_commands(client, monkeypatch):
    workspace = seeded_workspace(client)
    monkeypatch.setattr(
        OllamaStructuredClient, "generate", lambda *_args, **_kwargs: None
    )
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={"message": "asdkjh qweqwe zxcvbn", "history": []},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # It names the terms it searched for, so "no result" is a real finding
    # about this project rather than a shrug about the wording.
    assert "nothing recorded in" in body["answer"]
    assert "'asdkjh'" in body["answer"]
    # It still reports what the project does hold, and what to type next.
    assert "functional requirement" in body["answer"]
    assert len(body["recommendations"]) >= 4


def test_the_fallback_never_claims_a_change_was_made(client, monkeypatch):
    workspace = seeded_workspace(client)
    before = client.get(f"/api/v1/workspaces/{workspace['id']}").json()["updated_at"]
    monkeypatch.setattr(
        OllamaStructuredClient, "generate", lambda *_args, **_kwargs: None
    )
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={"message": "tell me about payments", "history": []},
    )
    assert "no change was applied" in response.json()["answer"]
    after = client.get(f"/api/v1/workspaces/{workspace['id']}").json()["updated_at"]
    assert before == after


# ------------------------------------------------------- conversational turns
# The user asked for a chatbot, not a command parser. Hello, "what can you do"
# and "who uses this" are ordinary turns, and every one of them is answered
# from the project without reaching the model.


def test_a_greeting_is_answered_and_grounded_in_the_open_project(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "hi")
    assert reply["resolved_by"] == "deterministic"
    assert workspace["title"] in reply["answer"]
    assert "functional requirement" in reply["answer"]


@pytest.mark.parametrize("message", ["hello there", "hey", "good morning", "thanks", "thank you", "bye"])
def test_small_talk_never_reaches_the_model(client, message):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], message)
    assert reply["resolved_by"] == "deterministic"
    assert reply["answer"].strip()


def test_small_talk_does_not_swallow_a_command_that_starts_with_ok(client):
    """"ok delete FR-002" is an action, not an acknowledgement."""
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "ok delete FR-002")
    assert reply["category"] == "ACTION"
    assert reply["proposal"] is not None


def test_what_can_you_do_lists_real_commands_for_this_project(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "what can you do")
    answer = reply["answer"]
    assert reply["category"] == "EXPLANATION"
    assert workspace["title"] in answer
    # The commands it advertises are ones the deterministic layer actually runs.
    for command in ("explain everything", "add a functional requirement", "delete FR-"):
        assert command in answer


def test_help_me_add_is_still_an_action_not_a_capability_question(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "help me add a functional requirement: Drivers can rate a station")
    assert reply["category"] == "ACTION"
    assert reply["proposal"] is not None


def test_who_uses_this_is_answered_with_the_recorded_actors(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "who uses this system")
    assert reply["resolved_by"] == "deterministic"
    assert "ACTOR-001" in reply["answer"]
    assert reply["evidence_ids"]


def test_an_actor_name_is_not_printed_twice(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "who are the users")
    for line in reply["answer"].splitlines():
        if "ACTOR-" not in line:
            continue
        _, _, detail = line.partition("—")
        name = line.split()[1]
        assert not detail.strip().casefold().startswith(name.casefold())


def test_counts_are_pluralised_correctly(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "hi")
    assert "entitys" not in reply["answer"]


# ------------------------------------------------------- everyday vocabulary
# Users say "functions" and "features" for functional requirements. Meeting
# them there is the difference between an answer and a dead end.


@pytest.mark.parametrize(
    "message",
    [
        "explain all the functions",
        "explain all the features",
        "describe all the capabilities",
        "tell me all the functionality",
        "explain everything",
    ],
)
def test_breadth_questions_return_the_briefing_without_the_model(client, message):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], message)
    assert reply["resolved_by"] == "deterministic"
    assert "FUNCTIONAL REQUIREMENTS" in reply["answer"]
    assert "FR-001" in reply["answer"]


def test_a_quantified_list_request_is_still_a_list(client):
    """"list all the FRs" wants the list, not a fifteen-section briefing."""
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "list all the functional requirements")
    assert "PROJECT\n" not in reply["answer"]
    assert "FR-001" in reply["answer"]


def test_is_my_architecture_good_is_routed_to_the_critique(client):
    workspace = seeded_workspace(client)
    reply = chat(client, workspace["id"], "is my architecture good")
    assert reply["category"] == "ANALYSIS"
    assert any(
        label in reply["answer"]
        for label in ("[Confirmed issue]", "[Potential risk]", "[Needs verification]")
    ) or "no evidenced problems" in reply["answer"]


def test_an_absent_subject_is_reported_as_a_finding_not_a_shrug(client, monkeypatch):
    workspace = seeded_workspace(client)
    monkeypatch.setattr(
        OllamaStructuredClient, "generate", lambda *_args, **_kwargs: None
    )
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/architecture-chat",
        json={"message": "explain the login function", "history": []},
    )
    answer = response.json()["answer"]
    # "login" is the subject; "explain" and "function" are how it was asked.
    assert "'login'" in answer
    assert "'explain'" not in answer and "'function'" not in answer
