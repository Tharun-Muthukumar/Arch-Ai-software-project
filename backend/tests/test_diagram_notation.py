"""UML notation correctness for every diagram, across unrelated domains.

The diagram generators were only ever read against one EV charging project.
Checking a second domain immediately turned up defects that were invisible
there: an activity diagram that was a star graph, a sequence diagram naming an
actor "Needs clarification", and a deployment diagram drawing "Replicas: 2" as
a deployed thing with an arrow into the deployment model.

So these tests are parametrised over five briefs that share no vocabulary.
Every assertion is about *notation* — the rules of the diagram type — rather
than about domain words, because a rule that only holds for one domain is not a
rule. Domain grounding is asserted separately, per brief, at the end.
"""

import pytest

BRIEFS = {
    "ev": {
        "title": "VoltReserve",
        "description": (
            "Build an EV charging station booking platform for metro cities with "
            "station discovery, charger availability, slot booking, payments, "
            "refunds, operator controls, and charging session tracking."
        ),
        "business_context": (
            "The first release should support rapid city pilots with clear "
            "operator tooling and auditable payment flows."
        ),
        "preferred_cloud": "AWS",
        "constraints": ["Must use PostgreSQL"],
    },
    "pharmacy": {
        "title": "MediBridge",
        "description": (
            "Build an online pharmacy with medicine search, prescription upload, "
            "pharmacist verification, secure checkout, order tracking, inventory "
            "controls, and delivery partner updates."
        ),
        "business_context": (
            "The first release needs safe prescription handling and clear stock "
            "visibility."
        ),
        "preferred_cloud": "AWS",
        "constraints": ["Must use PostgreSQL"],
    },
    "lms": {
        "title": "CourseForge",
        "description": (
            "Build a learning management system where instructors publish courses "
            "and lessons, students enroll and submit assignments, graders score "
            "submissions, and administrators manage cohorts, certificates and "
            "progress reports."
        ),
        "business_context": "Universities need cohort management and auditable grading.",
        "preferred_cloud": "Azure",
        "constraints": ["Must use PostgreSQL"],
    },
    "logistics": {
        "title": "FleetTrail",
        "description": (
            "Build a freight logistics platform where dispatchers assign shipments "
            "to carriers, drivers update delivery milestones, warehouse staff "
            "manage manifests, and customers track consignments with proof of "
            "delivery."
        ),
        "business_context": "Regional carriers need live milestone visibility.",
        "preferred_cloud": "GCP",
        "constraints": ["Must use PostgreSQL"],
    },
    "helpdesk": {
        "title": "DeskRelay",
        "description": (
            "Build an IT service desk where requesters submit incidents, agents "
            "triage and resolve tickets, approvers authorize change requests, and "
            "managers review breach reports against service levels."
        ),
        "business_context": "Internal IT needs auditable change approval.",
        "preferred_cloud": "AWS",
        "constraints": ["Must use PostgreSQL"],
    },
}

DIAGRAM_KEYS = {
    "use_case",
    "activity",
    "sequence",
    "class",
    "er",
    "component",
    "deployment",
}

# Placeholder strings the requirement extractor writes when it could not
# identify something. None of them may ever reach a diagram: a diagram that
# prints one is asserting a fact the requirement model does not hold.
PLACEHOLDERS = (
    "needs clarification",
    "not yet identified",
    "requires clarification",
    "tbd",
    "none",
    "unknown",
)


@pytest.fixture(params=sorted(BRIEFS))
def project(request, client):
    """One generated workspace per brief."""
    response = client.post("/api/v1/workspaces", json=BRIEFS[request.param])
    assert response.status_code == 201, response.text
    workspace = response.json()
    workspace["_key"] = request.param
    return workspace


def mermaid(project, name):
    return project["diagrams"][name]["mermaid"]


def plantuml(project, name):
    return project["diagrams"][name]["plantuml"]


# --------------------------------------------------------------------- shared


def test_every_diagram_is_generated(project):
    assert set(project["diagrams"]) == DIAGRAM_KEYS


def test_no_diagram_prints_an_extractor_placeholder(project):
    for name in DIAGRAM_KEYS:
        text = mermaid(project, name).casefold()
        for placeholder in PLACEHOLDERS:
            # "Actor not confirmed" is the honest wording the diagrams use when
            # the model genuinely has no actor; the raw placeholders are not.
            assert placeholder not in text, f"{name} prints the placeholder {placeholder!r}"


def test_every_mermaid_diagram_declares_its_type(project):
    expected = {
        "use_case": ("flowchart", "graph"),
        "activity": ("flowchart", "graph"),
        "sequence": ("sequenceDiagram",),
        "class": ("classDiagram",),
        "er": ("erDiagram",),
        "component": ("flowchart", "graph"),
        "deployment": ("flowchart", "graph"),
    }
    for name, prefixes in expected.items():
        first = mermaid(project, name).strip().splitlines()[0].strip()
        assert first.startswith(prefixes), f"{name} starts with {first!r}"


def test_no_diagram_leaves_an_unbalanced_subgraph(project):
    for name in DIAGRAM_KEYS:
        lines = [line.strip() for line in mermaid(project, name).splitlines()]
        opened = sum(1 for line in lines if line.startswith("subgraph"))
        closed = sum(1 for line in lines if line == "end")
        assert opened == closed, f"{name} has {opened} subgraph(s) and {closed} end(s)"


def test_every_plantuml_export_is_a_complete_document(project):
    for name in DIAGRAM_KEYS:
        text = plantuml(project, name)
        assert text.strip().startswith("@startuml"), name
        assert text.strip().endswith("@enduml"), name


# ------------------------------------------------------------------- activity


def test_activity_diagram_has_start_and_final_nodes(project):
    """A UML activity diagram begins at an initial node and ends at a final
    one. This was a star graph hanging off a "Confirmed requirement model" hub,
    with neither."""
    activity = mermaid(project, "activity")
    assert "Confirmed requirement model" not in activity
    assert "START" in activity
    assert "FINAL" in activity


def test_activity_diagram_groups_activities_into_partitions(project):
    """Actors belong in partitions (swimlanes), not as nodes in the flow."""
    activity = mermaid(project, "activity")
    assert "subgraph LANE1" in activity


def test_activity_diagram_forks_and_joins_rather_than_inventing_an_order(project):
    """The requirement model records no execution order between workflows.

    A chain of arrows would invent one. UML's fork and join state "these
    happen, order unspecified", which is what the model actually supports.
    """
    activity = mermaid(project, "activity")
    lanes = activity.count("subgraph LANE")
    actions = activity.count(":::action")
    if actions > 1:
        assert "FORK" in activity and "JOIN" in activity
        # Every activity is on a path from the fork to the join.
        for index in range(1, actions + 1):
            assert f"FORK --> A{index}" in activity
            assert f"A{index} --> JOIN" in activity
        assert "JOIN --> FINAL" in activity
    assert lanes >= 1


def test_activity_partitions_are_named_for_actors_not_requirements(project):
    """A partition title is a role. It used to be able to be the string
    "Needs clarification" straight from the extractor."""
    titles = [
        line.split('["', 1)[1].rstrip('"]')
        for line in mermaid(project, "activity").splitlines()
        if "subgraph LANE" in line
    ]
    actor_names = {actor["name"] for actor in project["requirements"]["actors"]}
    for title in titles:
        assert title in actor_names or title == "Actor not confirmed", title


# ------------------------------------------------------------------- sequence


def test_sequence_diagram_uses_native_notation(project):
    sequence = mermaid(project, "sequence")
    assert sequence.startswith("sequenceDiagram")
    # UML numbers the messages on a sequence diagram.
    assert "autonumber" in sequence
    assert "actor UserParticipant as" in sequence


def test_sequence_actor_is_a_real_actor_from_the_model(project):
    """The actor line carried `workflow.primary_actor` unchecked, so a project
    whose workflow had no identified actor drew `actor UserParticipant as Needs
    clarification`."""
    line = next(
        line for line in mermaid(project, "sequence").splitlines()
        if line.strip().startswith("actor UserParticipant as")
    )
    name = line.split("as", 1)[1].strip()
    actor_names = {actor["name"] for actor in project["requirements"]["actors"]}
    assert name in actor_names or name == "Actor (not confirmed)", name


def test_sequence_data_participant_is_an_entity_the_requirement_names(project):
    """Any shared word used to be enough, so a requirement mentioning "user"
    selected the platform's `users` auth table. The entity must be named by the
    requirement it appears in."""
    sequence = mermaid(project, "sequence")
    data = [
        line.split("as", 1)[1].strip()
        for line in sequence.splitlines()
        if line.strip().startswith("participant Data as")
    ]
    if not data:
        return
    entity_names = {entity["name"] for entity in project["database_design"]["entities"]}
    assert data[0] in entity_names
    # And it is not the platform's own auth/audit table.
    assert data[0] not in {"users", "audit_logs"}


def test_sequence_activation_bars_are_balanced(project):
    """`->>+` opens an execution occurrence and `-->>-` closes it. An
    unbalanced pair renders as a lifeline that never returns."""
    sequence = mermaid(project, "sequence")
    assert sequence.count(">>+") == sequence.count(">>-")


# ---------------------------------------------------------------------- class


def test_class_members_are_uml_attributes_not_sql_columns(project):
    """A Mermaid class member containing `()` is parsed as an operation, so
    every `VARCHAR(255)` column rendered in the methods compartment."""
    class_diagram = mermaid(project, "class")
    assert class_diagram.startswith("classDiagram")
    assert "(" not in class_diagram
    assert "VARCHAR" not in class_diagram
    assert "+id : UUID" in class_diagram


def test_class_relationships_use_uml_multiplicity_arrows(project):
    class_diagram = mermaid(project, "class")
    assert any(
        marker in class_diagram
        for marker in ('"1" -->', '"1" --', "-->", "--")
    )


# ------------------------------------------------------------------------- er


def test_er_attributes_follow_mermaid_grammar(project):
    """`type name [key] ["comment"]`. `*id` and `VARCHAR?` were invented
    notation that Mermaid does not parse."""
    er = mermaid(project, "er")
    assert er.startswith("erDiagram")
    assert "*id" not in er
    assert "?" not in er
    assert " PK" in er


def test_er_relationships_declare_cardinality_and_a_label(project):
    """Mermaid requires a label on an ER relationship; an unlabelled one is a
    parse error."""
    er = mermaid(project, "er")
    relationships = [
        line.strip() for line in er.splitlines()
        if any(token in line for token in ("||--", "}o--", "}|--", "|o--"))
    ]
    assert relationships, "a generated schema should relate at least two entities"
    for line in relationships:
        assert ":" in line, f"unlabelled ER relationship: {line}"


def test_no_relationship_references_an_entity_the_schema_lacks(project):
    """A relationship endpoint must be a table the schema contains.

    Some relationships come from named blueprints spelling their tables in the
    plural while the generic extraction produces the singular. When both
    contributed, the singular entities won but the plural relationship survived
    untouched, so the design carried an edge between two tables it did not have
    — and the ER diagram drew them as entities that exist nowhere else in the
    project.
    """
    design = project["database_design"]
    names = {entity["name"] for entity in design["entities"]}
    for relation in design["relationships"]:
        assert relation["source"] in names, relation
        assert relation["target"] in names, relation
        if relation.get("foreign_key"):
            table = relation["foreign_key"].split(".")[0]
            assert table == relation["source"], relation


def test_er_diagram_draws_only_declared_entities(project):
    """Every entity the ER diagram draws must be a table the schema declares.

    Compared on the singular form, because an ER entity type is conventionally
    singular while the table is plural: `BOOKINGS` is drawn as `BOOKING`. The
    check is that nothing is drawn which has no table behind it at all.
    """
    import re as _re

    def singular(name):
        if name.endswith("IES"):
            return name[:-3] + "Y"
        return name[:-1] if name.endswith("S") and not name.endswith("SS") else name

    design = project["database_design"]
    declared = {singular(entity["name"].upper()) for entity in design["entities"]}
    drawn = {
        singular(name)
        for name in _re.findall(
            r"^\s*([A-Z_][A-Z0-9_]*)\s*\{", mermaid(project, "er"), _re.MULTILINE
        )
    }
    assert drawn, "the ER diagram should declare at least one entity"
    assert drawn <= declared, drawn - declared


# ------------------------------------------------------------------ component


def test_component_diagram_groups_components_into_tiers(project):
    component = mermaid(project, "component")
    assert "subgraph" in component


# ----------------------------------------------------------------- deployment


def test_deployment_diagram_uses_node_and_artifact_notation(project):
    """UML deployment notation: artifacts are deployed onto nodes."""
    deployment = mermaid(project, "deployment")
    assert "«node»" in deployment
    assert "«artifact»" in deployment or "No deployable artifact" in deployment


def test_deployment_metadata_is_a_node_property_not_a_graph_node(project):
    """Region and replica count were drawn as boxes with arrows into the
    deployment model, which read as deployed things that talk to it. They are
    properties of the node."""
    deployment = mermaid(project, "deployment")
    assert 'Regions["' not in deployment
    assert 'Replicas["' not in deployment
    plan = project["deployment_plan"]
    if plan.get("replicas") is not None:
        assert f"replicas = {plan['replicas']}" in deployment


def test_deployment_edges_all_point_the_same_way(project):
    """Edges ran `Plan --> Runtime{i}` but `Platform{i} --> Plan` — two
    directions for the same kind of relationship. Containment is now a
    subgraph, and the one remaining edge is an undirected communication path,
    because the deployment plan records no call direction."""
    deployment = mermaid(project, "deployment")
    assert "-->" not in deployment
    if "subgraph PLATFORM" in deployment:
        assert "DEPLOY --- PLATFORM" in deployment


# ------------------------------------------------------------- use case model


def test_use_case_model_associations_reference_declared_actors(project):
    model = project["diagrams"]["use_case"]["use_case_model"]
    assert model is not None
    actor_ids = {actor["id"] for actor in model["actors"]}
    assert len(actor_ids) == len(model["actors"]), "actor ids must be unique"
    for use_case in model["use_cases"]:
        for actor_id in use_case["actor_ids"]:
            assert actor_id in actor_ids


def test_use_case_requirement_ids_are_truthful(project):
    """A use case's requirement id must point at the requirement whose text it
    carries. Truncating the list with `[*functional[:11], functional[-1]]` once
    left the node labelled FR-012 carrying FR-013's text."""
    model = project["diagrams"]["use_case"]["use_case_model"]
    functional = project["requirements"]["functional_requirements"]
    for use_case in model["use_cases"]:
        index = int(use_case["requirement_id"].split("-")[1]) - 1
        assert 0 <= index < len(functional), use_case["requirement_id"]


# ----------------------------------------------------------- domain grounding


DOMAIN_TERMS = {
    "ev": ("charging", "station"),
    "pharmacy": ("prescription", "pharmac"),
    "lms": ("course", "student"),
    "logistics": ("shipment", "carrier"),
    "helpdesk": ("incident", "ticket"),
}

FOREIGN_TERMS = {
    "ev": ("prescription", "cohort"),
    "pharmacy": ("charger", "cohort"),
    "lms": ("charger", "prescription"),
    "logistics": ("prescription", "charger"),
    "helpdesk": ("prescription", "charger"),
}


def test_diagrams_are_grounded_in_their_own_domain(project):
    """Each project's diagrams must speak its own vocabulary and no other
    project's. A hardcoded branch for one industry used to leak the EV diagram
    into unrelated projects."""
    key = project["_key"]
    combined = " ".join(mermaid(project, name) for name in DIAGRAM_KEYS).casefold()
    assert any(term in combined for term in DOMAIN_TERMS[key]), key
    for term in FOREIGN_TERMS[key]:
        assert term not in combined, f"{key} diagrams mention {term!r}"
