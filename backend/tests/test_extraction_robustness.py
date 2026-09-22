"""Extraction on brief shapes the rest of the suite never exercises.

Every case here is a defect found by feeding the analyser sixteen deliberately
awkward briefs and checking invariants, rather than by checking one happy-path
project. The invariants are the ones that matter downstream: no artifact may
print an extractor placeholder as if it were a fact, no diagram may reference
something the model does not contain, and a brief with real structure in it
must not be discarded.
"""

import pytest

from app.services.domain_inference import (
    _has_plural_subject,
    _is_product_title,
    _split_where_clauses,
    extract_capabilities,
)


def create(client, title, description, **extra):
    payload = {"title": title, "description": description, "constraints": []}
    payload.update(extra)
    response = client.post("/api/v1/workspaces", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# ------------------------------------------------- the where-clause lead-in


def test_a_brief_that_opens_with_a_noun_phrase_still_splits():
    """The lead-in used to require an imperative opener, so only
    "Build a X where ..." split. A brief that names the product as a noun
    phrase instead was left whole, which made the entire brief FR-001 and cost
    every actor named in it."""
    clauses = _split_where_clauses(
        "A tool where users submit forms and reviewers approve them."
    )
    assert clauses == ["users submit forms", "reviewers approve them."]


def test_and_splits_two_clauses_but_never_one_object():
    """With no commas, "and" is the only separator — but it far more often
    joins the parts of one object. Both sides must be clauses with their own
    plural subject."""
    assert _split_where_clauses(
        "An EV charging platform where drivers reserve slots and operators manage chargers."
    ) == ["drivers reserve slots", "operators manage chargers."]
    # "station and charger availability" is one noun phrase, not two clauses.
    assert _split_where_clauses("The system where station and charger availability is shown.") is None


@pytest.mark.parametrize(
    "segment,expected",
    [
        ("users submit forms", True),
        ("reviewers approve them for a small office team", True),
        ("charger availability", False),
        ("station", False),
        ("proof of delivery", False),
        ("the operator dashboard", False),
    ],
)
def test_plural_subject_detection(segment, expected):
    assert _has_plural_subject(segment) is expected


def test_an_imperative_brief_is_not_mistaken_for_a_title():
    """Widening the title rule immediately exposed this: the imperative guard
    only checked the capability verb list, which has no "build", so
    "Build a cold-chain slot coordination tool with depot discovery, ..." was
    discarded as a title and its whole capability list went with it."""
    assert not _is_product_title(
        "Build a cold-chain slot coordination tool with depot discovery, "
        "live bay availability, slot booking, and cancellation requests."
    )
    assert not _is_product_title("Provide a self-service portal.")
    assert not _is_product_title("Integrate with the partner platform.")
    # A real title still is one, whatever its length.
    assert _is_product_title(
        "EV charging station booking platform for fast-growing metro cities in India."
    )


def test_a_repeated_title_sentence_is_skipped_everywhere():
    """The title was skipped by position, so a brief that repeats it smuggled
    it back in as sentence two."""
    capabilities = extract_capabilities(
        "Fleet telemetry platform. Fleet telemetry platform.",
        None,
        {"fleet", "telemetry"},
        set(),
    )
    assert not any("fleet telemetry platform" in item.casefold() for item in capabilities)


# ------------------------------------------- the conservative-fallback gate


def test_one_entity_with_actors_is_not_discarded(client):
    """The gate was `entities < 2 OR capabilities < 1`, as an OR, so a single
    entity threw away everything else the extractor had found.

    "A tool where users submit forms and reviewers approve them." yields one
    entity (form) but two clean capabilities and two actors — and all of it was
    replaced by the conservative fallback, whose entire output is the brief
    verbatim as FR-001 with no actors at all. That is strictly worse than the
    model it replaced.
    """
    workspace = create(
        client,
        "Approval tool",
        "A tool where users submit forms and reviewers approve them for a small office team.",
    )
    requirements = workspace["requirements"]
    assert len(requirements["functional_requirements"]) >= 2
    assert "Reviewer" in {actor["name"] for actor in requirements["actors"]}
    # The brief itself must not be one of the requirements.
    brief = "a tool where users submit forms and reviewers approve them for a small office team"
    assert not any(
        " ".join(item.casefold().split()).rstrip(".") == brief
        for item in requirements["functional_requirements"]
    )


def test_a_brief_naming_no_business_object_does_not_crash(client):
    """`entity_ids` can be empty now that the gate allows it, and the domain
    label derivation indexed `entity_ids[0]` unconditionally — so the request
    raised IndexError and returned a 500."""
    workspace = create(
        client,
        "Availability update",
        "Operators review equipment service records.",
    )
    assert workspace["requirements"]["domain"]


# ------------------------------------------- placeholders must never surface


UNCLASSIFIED = ("unknown domain", "needs clarification", "not yet identified", "tbd")


def test_an_unclassified_domain_is_never_printed_in_a_diagram(client):
    """`RequirementModel.domain` has to keep the literal "Unknown domain" —
    the signal layer and the clarification engine both branch on it — but the
    diagrams were printing it as the system's name: the use case boundary read
    "Unknown domain", the sequence diagram named a participant "Unknown domain
    Core", and the component diagram created a box called
    UNKNOWN_DOMAIN_CORE."""
    workspace = create(
        client,
        "Probe",
        "A tool where users submit forms and reviewers approve them for a small office team.",
    )
    for name, artifact in workspace["diagrams"].items():
        text = (artifact["mermaid"] or "").casefold()
        for placeholder in UNCLASSIFIED:
            assert placeholder not in text, f"{name} prints {placeholder!r}"


def test_no_actor_is_named_after_a_placeholder(client):
    workspace = create(
        client,
        "Probe",
        "Nightly batch reconciliation of ledger entries against bank statements with alerting.",
    )
    for actor in workspace["requirements"]["actors"]:
        assert actor["name"].casefold() not in UNCLASSIFIED


# --------------------------------------------------- cross-artifact integrity


AWKWARD_BRIEFS = {
    "semicolons": (
        "Build a clinic scheduler; patients book appointments; nurses triage "
        "arrivals; doctors record consultations; billing staff issue invoices."
    ),
    "unicode": (
        "Build a café ordering platform where baristas prepare drinks, cashiers "
        "take payments, and managers review daily takings."
    ),
    "numbers": (
        "Build a metering platform where meters report readings every 15 minutes, "
        "operators review 10,000 anomalies per day, and auditors export datasets."
    ),
    "mixed-case": (
        "BUILD A TICKETING SYSTEM WHERE AGENTS RESOLVE TICKETS AND MANAGERS "
        "REVIEW SLA BREACHES."
    ),
    "question": "Can we build a system where teachers assign homework and parents view progress?",
    "acronyms": (
        "Build an IAM console where SSO admins configure OIDC clients, RBAC "
        "owners assign scopes, and MFA operators reset factors."
    ),
}


@pytest.mark.parametrize("key", sorted(AWKWARD_BRIEFS))
def test_awkward_briefs_produce_an_internally_consistent_project(client, key):
    workspace = create(client, f"Probe {key}", AWKWARD_BRIEFS[key])
    requirements = workspace["requirements"]

    assert requirements["functional_requirements"], "nothing was extracted"
    for requirement in requirements["functional_requirements"]:
        assert len(requirement.split()) >= 2, f"fragment: {requirement!r}"

    ids = [actor["id"] for actor in requirements["actors"]]
    assert len(ids) == len(set(ids)), f"duplicate actor ids: {ids}"

    tables = {entity["name"] for entity in workspace["database_design"]["entities"]}
    for relation in workspace["database_design"]["relationships"]:
        assert relation["source"] in tables, relation
        assert relation["target"] in tables, relation

    model = workspace["diagrams"]["use_case"]["use_case_model"]
    declared = {actor["id"] for actor in model["actors"]}
    count = len(requirements["functional_requirements"])
    for use_case in model["use_cases"]:
        index = int(use_case["requirement_id"].split("-")[1]) - 1
        assert 0 <= index < count, use_case["requirement_id"]
        for actor_id in use_case["actor_ids"]:
            assert actor_id in declared, use_case


def test_an_acronym_never_becomes_part_of_an_actor_name(client):
    """SSO, RBAC and MFA are ways of proving who someone is, not job titles.
    The wizard's auth answer was being read as a modifier on whatever role noun
    followed, producing actors named "Sso Admin" and "Rbac Admin"."""
    workspace = create(client, "IAM console", AWKWARD_BRIEFS["acronyms"])
    names = {actor["name"].casefold() for actor in workspace["requirements"]["actors"]}
    acronyms = {"sso", "rbac", "mfa", "oidc", "oauth", "oauth2", "saml", "iam"}
    for name in names:
        assert not (set(name.split()) & acronyms), f"{name!r} carries an access mechanism"
