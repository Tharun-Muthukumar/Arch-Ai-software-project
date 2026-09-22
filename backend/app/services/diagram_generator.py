import re
from textwrap import wrap
from typing import Callable, TypeVar

from app.schemas.domain import (
    Actor,
    UseCaseActorNode,
    UseCaseModel,
    UseCaseNode,
    ArchitectureComponent,
    ArchitectureOption,
    DatabaseDesign,
    DatabaseEntity,
    DatabaseRelationship,
    DeploymentPlan,
    DiagramArtifact,
    RecommendationResult,
    RequirementModel,
)
from app.services.domain_inference import (
    _ACCESS_MECHANISM_TERMS,
    _normalize_role,
    extract_actors,
    tokenize,
)


T = TypeVar("T")


# ---------------------------------------------------------------- diagram types
# SQL column types are not UML types. A class diagram that prints VARCHAR(255)
# is both wrong as UML *and* broken as Mermaid: a member containing parentheses
# is parsed as an operation, so every varchar attribute was rendering in the
# methods compartment with the nullability marker as a bogus return type.
_SQL_TO_UML: list[tuple[str, str]] = [
    ("UUID", "UUID"),
    ("VARCHAR", "String"),
    ("CHARACTER VARYING", "String"),
    ("TEXT", "String"),
    ("CITEXT", "String"),
    ("TIMESTAMPTZ", "DateTime"),
    ("TIMESTAMP", "DateTime"),
    ("DATETIME", "DateTime"),
    ("DATE", "Date"),
    ("TIME", "Time"),
    ("INTERVAL", "Duration"),
    ("BIGSERIAL", "Integer"),
    ("SERIAL", "Integer"),
    ("BIGINT", "Integer"),
    ("SMALLINT", "Integer"),
    ("INTEGER", "Integer"),
    ("INT", "Integer"),
    ("NUMERIC", "Decimal"),
    ("DECIMAL", "Decimal"),
    ("DOUBLE", "Float"),
    ("REAL", "Float"),
    ("FLOAT", "Float"),
    ("BOOLEAN", "Boolean"),
    ("BOOL", "Boolean"),
    ("JSONB", "Json"),
    ("JSON", "Json"),
    ("BYTEA", "Binary"),
    ("ENUM", "Enum"),
    ("ARRAY", "List"),
    ("INET", "String"),
    ("MONEY", "Decimal"),
]


ER_FIELD_LIMIT = 10
CLASS_FIELD_LIMIT = 10


def uml_type(data_type: str) -> str:
    """Map a SQL column type to a UML-appropriate one, parenthesis-free."""
    upper = str(data_type or "").upper()
    for needle, uml in _SQL_TO_UML:
        if needle in upper:
            return uml
    # Unknown type: keep it, but strip anything Mermaid would mis-parse.
    cleaned = re.sub(r"\(.*?\)", "", str(data_type or "")).strip()
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", cleaned).strip("_")
    return cleaned or "String"


# Verb phrases worth lifting out of a recorded relationship description, in
# the order they should win. Deliberately generic: these are relational verbs,
# not domain vocabulary.
_RELATIONSHIP_VERBS = (
    "belongs to", "owned by", "made by", "placed by", "uploaded by",
    "delivered to", "assigned to", "linked to", "associated with",
    "fulfills", "contains", "tracks", "sends to", "references", "uses",
    "has many", "has one",
)


def clean_label_text(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()


def extract_relationship_verb(description: str) -> str | None:
    """The first relational verb phrase the description actually contains."""
    for verb in _RELATIONSHIP_VERBS:
        if verb in description:
            return verb
    return None


def er_type(data_type: str) -> str:
    """The SQL type as an ER diagram should show it: real, but tokenised.

    Mermaid's ER attribute type accepts no parentheses and no punctuation, so
    VARCHAR(255) becomes VARCHAR. The precision is not lost information worth
    breaking the parser for; it lives in the database design view.
    """
    cleaned = re.sub(r"\(.*?\)", "", str(data_type or "")).strip()
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", cleaned).strip("_")
    return (cleaned or "TEXT").upper()


class DiagramGenerator:
    def generate(
        self,
        requirements: RequirementModel,
        architectures: list[ArchitectureOption],
        recommendation: RecommendationResult,
        database_design: DatabaseDesign,
        deployment_plan: DeploymentPlan,
    ) -> dict[str, DiagramArtifact]:
        architecture_lookup = {item.id: item for item in architectures}
        recommended = architecture_lookup[recommendation.recommended_architecture_id]

        return {
            "use_case": self._use_case(requirements),
            "activity": self._activity(requirements),
            "sequence": self._sequence(requirements, recommended, database_design),
            "class": self._class_diagram(database_design),
            "er": self._er_diagram(database_design),
            "component": self._component(recommended),
            "deployment": self._deployment(deployment_plan),
        }

    def use_case_only(self, requirements: RequirementModel) -> DiagramArtifact:
        """Build just the use case diagram.

        Used to repair a workspace whose stored diagrams predate the current
        notation, without regenerating every other artifact.
        """
        return self._use_case(requirements)

    def _use_case(self, requirements: RequirementModel) -> DiagramArtifact:
        # 329 lines of unreachable code used to follow this return: a complete
        # hand-written use case diagram gated on
        # `requirements.domain == "EV Charging Booking Platform"`, dead since
        # the dynamic builder was introduced. It also hardcoded one industry,
        # which the project's own rules exclude. Removed rather than left to
        # mislead the next reader.
        return self._dynamic_use_case(requirements)

    def _activity(self, requirements: RequirementModel) -> DiagramArtifact:
        return self._dynamic_activity(requirements)

        if requirements.domain == "EV Charging Booking Platform":
            mermaid = "\n".join(
                [
                    "flowchart TD",
                    '    Start([Driver opens platform]) --> Search["Search stations and filter connectors"]',
                    '    Search --> Details["Review station details and live availability"]',
                    '    Details --> Slot{"Slot available?"}',
                    '    Slot -- Yes --> Reserve["Reserve slot and confirm booking"]',
                    '    Slot -- No --> Search',
                    '    Reserve --> Pay["Authorize payment"]',
                    '    Pay --> Session["Start and monitor charging session"]',
                    '    Session --> Stop["Stop charging and capture usage"]',
                    '    Stop --> Summary["Send receipt, history, and analytics updates"]',
                    '    Summary --> End([Journey completed])',
                ]
            )
            plantuml = "\n".join(
                [
                    "@startuml",
                    "start",
                    ":Search stations;",
                    ":Review details and availability;",
                    "if (Slot available?) then (yes)",
                    "  :Reserve slot;",
                    "  :Authorize payment;",
                    "  :Start charging session;",
                    "  :Stop charging and finalize usage;",
                    "  :Send receipt and history update;",
                    "else (no)",
                    "  :Try another station or slot;",
                    "endif",
                    "stop",
                    "@enduml",
                ]
            )
            return DiagramArtifact(
                title="Activity Diagram",
                description="Shows the EV booking journey from station discovery through payment and charging completion.",
                mermaid=mermaid,
                plantuml=plantuml,
            )

        if requirements.domain == "Online Pharmacy":
            mermaid = "\n".join(
                [
                    "flowchart TD",
                    '    Start([Customer opens pharmacy]) --> Search["Search catalog and select medicines"]',
                    '    Search --> RxRequired{"Prescription required?"}',
                    '    RxRequired -- Yes --> Upload["Upload prescription"]',
                    '    Upload --> Review["Pharmacist verifies prescription"]',
                    '    Review --> Approved{"Prescription approved?"}',
                    '    Approved -- No --> Rework["Request correction or remove Rx items"]',
                    '    Rework --> Search',
                    '    Approved -- Yes --> Checkout["Confirm cart, address, and order"]',
                    '    RxRequired -- No --> Checkout',
                    '    Checkout --> Pay["Authorize payment"]',
                    '    Pay --> Reserve["Reserve inventory and create order"]',
                    '    Reserve --> Dispatch["Pick, pack, and dispatch shipment"]',
                    '    Dispatch --> Track["Send tracking updates and delivery status"]',
                    '    Track --> End([Order completed])',
                ]
            )
            plantuml = "\n".join(
                [
                    "@startuml",
                    "start",
                    ":Search catalog and select medicines;",
                    "if (Prescription required?) then (yes)",
                    "  :Upload prescription;",
                    "  :Pharmacist verifies prescription;",
                    "  if (Prescription approved?) then (yes)",
                    "    :Confirm order;",
                    "  else (no)",
                    "    :Request correction or remove Rx items;",
                    "    :Return to product selection;",
                    "  endif",
                    "else (no)",
                    "  :Confirm order;",
                    "endif",
                    ":Authorize payment;",
                    ":Reserve inventory and create order;",
                    ":Pick, pack, and dispatch shipment;",
                    ":Send tracking updates and delivery status;",
                    "stop",
                    "@enduml",
                ]
            )
            return DiagramArtifact(
                title="Activity Diagram",
                description="Shows the pharmacy order flow from product selection through prescription verification, payment, inventory reservation, and delivery updates.",
                mermaid=mermaid,
                plantuml=plantuml,
            )

        mermaid = "\n".join(
            [
                "flowchart TD",
                '    Brief([Brief submitted]) --> Analyze["Requirement analyzer extracts actors, constraints, and scale"]',
                '    Analyze --> Clarify{"Clarifications needed?"}',
                '    Clarify -- Yes --> Questions["Collect targeted follow-up answers"]',
                '    Questions --> Options["Generate architecture options"]',
                '    Clarify -- No --> Options["Generate architecture options"]',
                '    Options --> Compare["Score alternatives and recommend a direction"]',
                '    Compare --> Artifacts["Render diagrams, schema, APIs, and exports"]',
                '    Artifacts --> Finish([Workspace ready])',
            ]
        )
        plantuml = "\n".join(
            [
                "@startuml",
                "start",
                ":Collect project brief;",
                ":Extract requirements;",
                "if (Clarifications needed?) then (yes)",
                "  :Collect follow-up answers;",
                "endif",
                ":Generate architecture alternatives;",
                ":Compare, recommend, and render artifacts;",
                "stop",
                "@enduml",
            ]
        )
        return DiagramArtifact(
            title="Activity Diagram",
            description="Shows how the platform transforms a brief into a structured architecture workspace.",
            mermaid=mermaid,
            plantuml=plantuml,
        )

    def _sequence(
        self,
        requirements: RequirementModel,
        architecture: ArchitectureOption,
        database_design: DatabaseDesign,
    ) -> DiagramArtifact:
        return self._dynamic_sequence(requirements, architecture, database_design)

        if requirements.domain == "EV Charging Booking Platform":
            mermaid = "\n".join(
                [
                    "sequenceDiagram",
                    "    participant Driver",
                    "    participant Web as Web App",
                    "    participant API as Booking API",
                    "    participant Availability as Availability Service",
                    "    participant Payments as Payment Gateway",
                    "    participant Sessions as Session Service",
                    "    participant DB as PostgreSQL",
                    "    Driver->>Web: Search stations and pick a slot",
                    "    Web->>API: Request availability snapshot",
                    "    API->>Availability: Fetch live station and charger status",
                    "    Availability-->>API: Return open slots",
                    "    Driver->>Web: Confirm reservation",
                    "    Web->>Payments: Authorize payment",
                    "    Payments-->>Web: Payment approved",
                    "    Web->>API: Create booking",
                    "    API->>DB: Persist booking and payment state",
                    "    Driver->>Web: Start session",
                    "    Web->>Sessions: Start charging session",
                    "    Sessions->>DB: Save session telemetry",
                    "    Sessions-->>Web: Live session status",
                ]
            )
            plantuml = "\n".join(
                [
                    "@startuml",
                    "actor Driver",
                    "participant \"Web App\" as Web",
                    "participant \"Booking API\" as API",
                    "participant \"Availability Service\" as Availability",
                    "participant \"Payment Gateway\" as Payments",
                    "participant \"Session Service\" as Sessions",
                    "database PostgreSQL",
                    "Driver -> Web : Search stations and pick a slot",
                    "Web -> API : Request availability snapshot",
                    "API -> Availability : Fetch live station and charger status",
                    "Availability --> API : Open slots",
                    "Driver -> Web : Confirm reservation",
                    "Web -> Payments : Authorize payment",
                    "Payments --> Web : Payment approved",
                    "Web -> API : Create booking",
                    "API -> PostgreSQL : Persist booking and payment state",
                    "Driver -> Web : Start session",
                    "Web -> Sessions : Start charging session",
                    "Sessions -> PostgreSQL : Save session telemetry",
                    "Sessions --> Web : Live session status",
                    "@enduml",
                ]
            )
            return DiagramArtifact(
                title="Sequence Diagram",
                description="Illustrates the EV reservation flow across availability, payment, booking, and live session services.",
                mermaid=mermaid,
                plantuml=plantuml,
            )

        if requirements.domain == "Online Pharmacy":
            mermaid = "\n".join(
                [
                    "sequenceDiagram",
                    "    participant Customer",
                    "    participant Web as Web App",
                    "    participant Catalog as Catalog Service",
                    "    participant Prescription as Prescription Service",
                    "    participant Pharmacist as Pharmacist Console",
                    "    participant Orders as Order Service",
                    "    participant Payments as Payment Gateway",
                    "    participant Inventory as Inventory Service",
                    "    participant Delivery as Delivery Service",
                    "    participant DB as PostgreSQL",
                    "    Customer->>Web: Search medicine catalog",
                    "    Web->>Catalog: Query products and stock summary",
                    "    Catalog->>DB: Read catalog and inventory state",
                    "    Catalog-->>Web: Matching medicines",
                    "    Customer->>Web: Upload prescription for Rx items",
                    "    Web->>Prescription: Create prescription review",
                    "    Prescription->>DB: Persist prescription metadata",
                    "    Prescription-->>Pharmacist: Review request",
                    "    Pharmacist-->>Prescription: Approve prescription",
                    "    Customer->>Web: Confirm order",
                    "    Web->>Payments: Authorize payment",
                    "    Payments-->>Web: Payment approved",
                    "    Web->>Orders: Create order",
                    "    Orders->>Inventory: Reserve stock",
                    "    Inventory->>DB: Update inventory and order lines",
                    "    Orders->>Delivery: Create shipment and tracking",
                    "    Delivery->>DB: Persist shipment status",
                    "    Orders-->>Web: Confirmed order and tracking",
                    "    Web-->>Customer: Show order status",
                ]
            )
            plantuml = "\n".join(
                [
                    "@startuml",
                    "actor Customer",
                    "participant \"Web App\" as Web",
                    "participant \"Catalog Service\" as Catalog",
                    "participant \"Prescription Service\" as Prescription",
                    "participant \"Pharmacist Console\" as Pharmacist",
                    "participant \"Order Service\" as Orders",
                    "participant \"Payment Gateway\" as Payments",
                    "participant \"Inventory Service\" as Inventory",
                    "participant \"Delivery Service\" as Delivery",
                    "database PostgreSQL",
                    "Customer -> Web : Search medicine catalog",
                    "Web -> Catalog : Query products and stock summary",
                    "Catalog -> PostgreSQL : Read catalog and inventory state",
                    "Catalog --> Web : Matching medicines",
                    "Customer -> Web : Upload prescription for Rx items",
                    "Web -> Prescription : Create prescription review",
                    "Prescription -> PostgreSQL : Persist prescription metadata",
                    "Prescription --> Pharmacist : Review request",
                    "Pharmacist --> Prescription : Approve prescription",
                    "Customer -> Web : Confirm order",
                    "Web -> Payments : Authorize payment",
                    "Payments --> Web : Payment approved",
                    "Web -> Orders : Create order",
                    "Orders -> Inventory : Reserve stock",
                    "Inventory -> PostgreSQL : Update inventory and order lines",
                    "Orders -> Delivery : Create shipment and tracking",
                    "Delivery -> PostgreSQL : Persist shipment status",
                    "Orders --> Web : Confirmed order and tracking",
                    "Web --> Customer : Show order status",
                    "@enduml",
                ]
            )
            return DiagramArtifact(
                title="Sequence Diagram",
                description="Illustrates the pharmacy flow across catalog lookup, prescription approval, payment, inventory reservation, and shipment tracking.",
                mermaid=mermaid,
                plantuml=plantuml,
            )

        mermaid = "\n".join(
            [
                "sequenceDiagram",
                "    participant User",
                "    participant UI as Frontend",
                "    participant API as FastAPI",
                "    participant Engine as Decision Engine",
                "    participant DB as PostgreSQL",
                "    User->>UI: Submit project brief",
                "    UI->>API: POST /workspaces",
                "    API->>Engine: Run analysis pipeline",
                "    Engine->>DB: Persist generated artifacts",
                "    API-->>UI: Return workspace snapshot",
                "    UI-->>User: Present diagrams, comparison, and docs",
            ]
        )
        plantuml = "\n".join(
            [
                "@startuml",
                "actor User",
                "participant Frontend",
                "participant FastAPI",
                "participant Engine",
                "database PostgreSQL",
                "User -> Frontend : Submit project brief",
                "Frontend -> FastAPI : POST /workspaces",
                "FastAPI -> Engine : Run analysis pipeline",
                "Engine -> PostgreSQL : Save workspace",
                "FastAPI --> Frontend : Workspace response",
                "Frontend --> User : Present generated outputs",
                "@enduml",
            ]
        )
        return DiagramArtifact(
            title="Sequence Diagram",
            description="Illustrates the request-response flow from brief submission to rendered workspace output.",
            mermaid=mermaid,
            plantuml=plantuml,
        )

    # Strings the requirement extractor writes when it could not identify an
    # actor. Drawing one as an actor name states something the model does not
    # know; the diagrams say so explicitly instead.
    _UNKNOWN_ACTOR_LABELS = {
        "needs clarification",
        "actor not yet identified",
        "unknown",
        "tbd",
        "n/a",
    }

    # How many use cases fit on one readable diagram. Anything beyond this is
    # reported as an omission, never substituted for a requirement that is
    # shown: a node labelled FR-012 must carry FR-012.
    USE_CASE_LIMIT = 12

    def _dynamic_use_case(self, requirements: RequirementModel) -> DiagramArtifact:
        all_functional = requirements.functional_requirements
        shown = all_functional[: self.USE_CASE_LIMIT]
        omitted = max(0, len(all_functional) - len(shown))
        actor_profiles = self._use_case_actor_profiles(requirements)[:6]

        actor_nodes = [
            UseCaseActorNode(
                id=actor.id or f"ACT-{index:03d}",
                name=self._diagram_text(actor.name),
                actor_type=actor.actor_type or "human",
            )
            for index, (actor, _) in enumerate(actor_profiles, start=1)
        ]

        use_case_nodes: list[UseCaseNode] = []
        for index, requirement in enumerate(shown, start=1):
            requirement_id = f"FR-{index:03d}"
            actor_indexes = self._actors_for_use_case(
                requirements, requirement, actor_profiles
            )
            use_case_nodes.append(
                UseCaseNode(
                    id=f"UC-{index:03d}",
                    label=self._diagram_text(
                        self._clean_use_case_label(requirement) or requirement
                    ),
                    requirement_id=requirement_id,
                    actor_ids=[
                        actor_nodes[actor_index].id
                        for actor_index in actor_indexes
                        if actor_index < len(actor_nodes)
                    ],
                )
            )

        used_actor_ids = {
            actor_id
            for use_case in use_case_nodes
            for actor_id in use_case.actor_ids
        }
        actor_nodes = [actor for actor in actor_nodes if actor.id in used_actor_ids]

        system_name = self._system_label(requirements.domain)
        model = UseCaseModel(
            system_name=system_name,
            actors=actor_nodes,
            use_cases=use_case_nodes,
            omitted_use_case_count=omitted,
        )

        mermaid = self._use_case_mermaid(model)
        plantuml = self._use_case_plantuml(model)
        unassigned = sum(1 for node in use_case_nodes if not node.actor_ids)
        description_parts = [
            f"UML use case view of {system_name}: "
            f"{len(actor_nodes)} actor(s) and {len(use_case_nodes)} use case(s)."
        ]
        if unassigned:
            description_parts.append(
                f"{unassigned} use case(s) have no confirmed actor and are drawn inside the "
                "boundary without an association rather than attached to an invented actor."
            )
        if omitted:
            description_parts.append(
                f"{omitted} further requirement(s) are not drawn to keep the diagram readable."
            )
        return DiagramArtifact(
            title="Use Case Diagram",
            description=" ".join(description_parts),
            mermaid=mermaid,
            plantuml=plantuml,
            use_case_model=model,
        )

    def _use_case_mermaid(self, model: UseCaseModel) -> str:
        """A readable fallback, honestly labelled.

        Mermaid has no use case diagram and cannot draw a stick figure, so this
        stays a flowchart. It is the fallback; `use_case_model` is what the
        client draws as correct UML.
        """
        lines = [
            "flowchart LR",
            "    classDef actor fill:#102c31,stroke:#35b7c8,color:#f4f6f8;",
            "    classDef usecase fill:#33230e,stroke:#f5a524,color:#f4f6f8;",
            "    classDef unassigned fill:#20262d,stroke:#66717c,color:#f4f6f8,stroke-dasharray: 4 3;",
        ]
        alias = {actor.id: f"A{index}" for index, actor in enumerate(model.actors, start=1)}
        for actor in model.actors:
            lines.append(f'    {alias[actor.id]}["{actor.name}"]:::actor')
        lines.append(f'    subgraph SYS["{model.system_name}"]')
        for index, use_case in enumerate(model.use_cases, start=1):
            label = self._diagram_text(self._wrap_label(use_case.label, 24, html=True))
            style = "usecase" if use_case.actor_ids else "unassigned"
            lines.append(
                f'        U{index}(["{use_case.requirement_id}<br/>{label}"]):::{style}'
            )
        lines.append("    end")
        for index, use_case in enumerate(model.use_cases, start=1):
            for actor_id in use_case.actor_ids:
                if actor_id in alias:
                    lines.append(f"    {alias[actor_id]} --- U{index}")
        if model.omitted_use_case_count:
            lines.append(
                f'    MORE["+{model.omitted_use_case_count} further requirement(s) '
                f'not drawn"]:::unassigned'
            )
        return "\n".join(lines)

    def _use_case_plantuml(self, model: UseCaseModel) -> str:
        """Native UML use case notation, which PlantUML does support.

        `actor` renders the stick figure, `usecase` the ellipse and `rectangle`
        the system boundary. Associations are plain lines placed after the
        boundary, which is where PlantUML expects them.
        """
        lines = ["@startuml", "left to right direction", "skinparam packageStyle rectangle"]
        alias = {actor.id: f"A{index}" for index, actor in enumerate(model.actors, start=1)}
        for actor in model.actors:
            keyword = "actor" if actor.actor_type in {"human", "organizational"} else "actor/"
            lines.append(f'{keyword} "{actor.name}" as {alias[actor.id]}')
        lines.append(f'rectangle "{model.system_name}" {{')
        for index, use_case in enumerate(model.use_cases, start=1):
            label = self._diagram_text(self._wrap_label(use_case.label, 28))
            lines.append(f'  usecase "{use_case.requirement_id}\\n{label}" as U{index}')
        lines.append("}")
        for index, use_case in enumerate(model.use_cases, start=1):
            for actor_id in use_case.actor_ids:
                if actor_id in alias:
                    lines.append(f"{alias[actor_id]} -- U{index}")
        if model.omitted_use_case_count:
            lines.append(
                f'note as N1\n  {model.omitted_use_case_count} further requirement(s) '
                f'are not drawn.\nend note'
            )
        lines.append("@enduml")
        return "\n".join(lines)

    def _dynamic_activity(self, requirements: RequirementModel) -> DiagramArtifact:
        """A UML activity diagram: start, fork, partitions, join, final node.

        This was a star graph — every activity hanging off one
        "Confirmed requirement model" hub — which is not activity notation at
        all. The hub existed for an honest reason: the requirement model
        records no execution order, and a chain of arrows would have invented
        one.

        UML already has the notation for exactly that situation. A **fork**
        bar splits control into concurrent flows and a **join** bar merges
        them, which states "these happen, order unspecified" in the language
        of the diagram instead of by omitting the flow. Activities are grouped
        into **partitions** (swimlanes) by their actor, which is where UML puts
        the actor rather than drawing it as a node in the flow.
        """
        workflows = requirements.domain_workflows[:6]
        if workflows:
            activities = [
                (workflow.primary_actor, workflow.description) for workflow in workflows
            ]
        else:
            activities = [
                ("", item) for item in requirements.functional_requirements[:6]
            ]

        mermaid_lines = [
            "flowchart TB",
            # Fork and join are drawn as the thin solid bars UML uses, not as
            # labelled boxes.
            "    classDef bar fill:#f4f6f8,stroke:#f4f6f8,color:#f4f6f8,height:6px;",
            "    classDef terminal fill:#f4f6f8,stroke:#f4f6f8,color:#0c0f12;",
            # UML's final node is a ring around a filled dot, so it must not
            # look identical to the solid initial node. Mermaid's double circle
            # is the closest shape available; filling it dark and stroking it
            # light makes the ring visible, which a solid fill hid.
            "    classDef final fill:#0c0f12,stroke:#f4f6f8,stroke-width:2.5px,color:#0c0f12;",
            "    classDef action fill:#33230e,stroke:#f5a524,color:#f4f6f8;",
            '    START(("&nbsp;")):::terminal',
        ]
        plantuml_lines = ["@startuml", "start"]

        if not activities:
            mermaid_lines.extend(
                [
                    '    A1["Workflow details are not confirmed"]:::action',
                    '    FINAL((("&nbsp;"))):::final',
                    "    START --> A1 --> FINAL",
                ]
            )
            plantuml_lines.extend([":Workflow details are not confirmed;", "stop", "@enduml"])
            return DiagramArtifact(
                title="Activity Diagram",
                description=(
                    "No confirmed domain workflow is recorded, so no activity flow can be "
                    "drawn from the requirement model."
                ),
                mermaid="\n".join(mermaid_lines),
                plantuml="\n".join(plantuml_lines),
            )

        concurrent = len(activities) > 1
        if concurrent:
            mermaid_lines.append('    FORK[" "]:::bar')
            mermaid_lines.append("    START --> FORK")

        # Group by actor so each partition is one swimlane, preserving the
        # order the workflows were recorded in.
        partitions: dict[str, list[tuple[int, str]]] = {}
        for index, (actor, activity) in enumerate(activities, start=1):
            label = self._diagram_text(actor).strip()
            # "Needs clarification" is a placeholder the extractor writes when
            # it could not identify the actor. Printing it as a swimlane title
            # states a fact the model does not hold.
            if not label or label.casefold() in self._UNKNOWN_ACTOR_LABELS:
                # The workflow's own actor is only set when the requirement
                # text names it. An enumerated requirement ("Support station
                # discovery.") names no one, so fall back to the same stem
                # matcher the use case diagram uses rather than declaring the
                # actor unknown when the requirement model can identify it.
                matched = self._actor_for_requirement(requirements, activity)
                label = (
                    self._diagram_text(requirements.actors[matched].name)
                    if matched is not None
                    else "Actor not confirmed"
                )
            partitions.setdefault(label, []).append((index, activity))

        for partition_index, (actor_label, items) in enumerate(partitions.items(), start=1):
            mermaid_lines.append(
                f'    subgraph LANE{partition_index}["{actor_label}"]'
            )
            mermaid_lines.append("        direction TB")
            for index, activity in items:
                activity_label = self._diagram_text(
                    self._wrap_label(activity, 32, html=True)
                )
                mermaid_lines.append(f'        A{index}["{activity_label}"]:::action')
            mermaid_lines.append("    end")

        # The requirement model records the workflows but not their relative
        # execution order. Keep the PlantUML export faithful to the Mermaid
        # view by expressing each workflow as a branch between a fork and join
        # instead of silently inventing a sequential flow.
        for index, (actor, activity) in enumerate(activities):
            actor_label = self._diagram_text(actor).strip()
            if not actor_label or actor_label.casefold() in self._UNKNOWN_ACTOR_LABELS:
                matched = self._actor_for_requirement(requirements, activity)
                actor_label = (
                    self._diagram_text(requirements.actors[matched].name)
                    if matched is not None
                    else "Actor not confirmed"
                )
            if concurrent:
                plantuml_lines.append("fork" if index == 0 else "fork again")
            plantuml_lines.append(f'partition "{actor_label}" {{')
            plantuml_lines.append(
                f'  :{self._diagram_text(self._wrap_label(activity, 42))};'
            )
            plantuml_lines.append("}")
        if concurrent:
            plantuml_lines.append("end fork")

        mermaid_lines.append('    JOIN[" "]:::bar' if concurrent else "")
        mermaid_lines.append('    FINAL((("&nbsp;"))):::final')
        for index, _ in enumerate(activities, start=1):
            if concurrent:
                mermaid_lines.append(f"    FORK --> A{index}")
                mermaid_lines.append(f"    A{index} --> JOIN")
            else:
                mermaid_lines.append(f"    START --> A{index}")
                mermaid_lines.append(f"    A{index} --> FINAL")
        if concurrent:
            mermaid_lines.append("    JOIN --> FINAL")
        mermaid_lines = [line for line in mermaid_lines if line != ""]

        plantuml_lines.extend(["stop", "@enduml"])
        return DiagramArtifact(
            title="Activity Diagram",
            description=(
                f"{len(activities)} confirmed workflow(s), grouped into partitions by actor. "
                + (
                    "A fork and join express that they are known to happen without an "
                    "execution order being recorded; no sequence is inferred."
                    if concurrent
                    else "A single workflow is recorded, so the flow is sequential."
                )
            ),
            mermaid="\n".join(mermaid_lines),
            plantuml="\n".join(plantuml_lines),
        )

    def _dynamic_sequence(
        self,
        requirements: RequirementModel,
        architecture: ArchitectureOption,
        database_design: DatabaseDesign,
    ) -> DiagramArtifact:
        workflow = requirements.domain_workflows[0] if requirements.domain_workflows else None
        requirement = (
            workflow.description
            if workflow
            else requirements.functional_requirements[0]
            if requirements.functional_requirements
            else "Workflow details require clarification"
        )
        actor = self._confirmed_actor_name(
            workflow.primary_actor if workflow else "", requirements
        )
        component = self._best_text_match(
            requirement,
            architecture.components,
            lambda item: " ".join(
                [item.name, item.responsibility, *item.interactions]
            ),
        )
        entity = self._entity_for_requirement(requirement, database_design)
        actor_text = actor
        system_text = self._diagram_text(component.name if component else architecture.name)
        # "Support station discovery." is how the requirement reads; as a
        # message on a lifeline it should read as the request being made.
        request_text = self._diagram_text(
            re.sub(
                r"^(?:support|expose|provide|enable|allow)\s+",
                "",
                requirement.strip(),
                flags=re.IGNORECASE,
            ).rstrip(".")
        )
        request_text = f"{request_text[:1].upper()}{request_text[1:]}" if request_text else "Workflow request"

        mermaid_lines = [
            "sequenceDiagram",
            # UML numbers messages on a sequence diagram and shows execution
            # occurrences as activation bars on the lifeline; both were missing.
            "    autonumber",
            f"    actor UserParticipant as {actor_text}",
            "    participant Interface as System interface",
            f"    participant System as {system_text}",
        ]
        plantuml_lines = [
            "@startuml",
            f'actor "{actor_text}" as Actor',
            'boundary "System interface" as Interface',
            f'participant "{system_text}" as System',
        ]
        if entity:
            entity_text = self._diagram_text(entity.name)
            mermaid_lines.append(f"    participant Data as {entity_text}")
            plantuml_lines.append(f'database "{entity_text}" as Data')
        mermaid_lines.extend(
            [
                f"    UserParticipant->>+Interface: {request_text}",
                "    Interface->>+System: Submit validated workflow request",
            ]
        )
        plantuml_lines.extend(
            [
                f"Actor -> Interface : {request_text}",
                "Interface -> System : Submit validated workflow request",
            ]
        )
        if entity:
            mermaid_lines.extend(
                [
                    f"    System->>+Data: Read or update {entity_text} as required",
                    "    Data-->>-System: Persisted workflow state",
                ]
            )
            plantuml_lines.extend(
                [
                    f"System -> Data : Read or update {entity_text} as required",
                    "Data --> System : Persisted workflow state",
                ]
            )
        mermaid_lines.extend(
            [
                "    System-->>-Interface: Workflow result or validation error",
                "    Interface-->>-UserParticipant: Present confirmed result",
            ]
        )
        plantuml_lines.extend(
            [
                "System --> Interface : Workflow result or validation error",
                "Interface --> Actor : Present confirmed result",
                "@enduml",
            ]
        )
        return DiagramArtifact(
            title="Sequence Diagram",
            description=(
                f"Traces one confirmed {self._system_label(requirements.domain)} workflow "
                "through the closest matching "
                "architecture component"
                + (f" and the {self._diagram_text(entity.name)} entity." if entity else
                   ", with no data entity drawn because none matches the workflow closely enough.")
                + " Unconfirmed integrations are not added."
            ),
            mermaid="\n".join(mermaid_lines),
            plantuml="\n".join(plantuml_lines),
        )

    def _entity_for_requirement(
        self, requirement: str, database_design: DatabaseDesign
    ) -> DatabaseEntity | None:
        """The entity the requirement actually names, or None.

        Text overlap alone is the wrong test here. Any shared word was enough,
        so a requirement mentioning "user" selected the platform's `users` auth
        table over the domain's own entities and the sequence diagram named a
        store the workflow never touches. Raising the bar to two shared words
        traded that for the opposite failure: "Instructors publish courses and
        lessons." shares exactly one word with the `courses` entity, so most
        projects drew no data participant at all.

        The requirement must name the entity — its name stem has to appear in
        the requirement — and among those, the one sharing most vocabulary
        wins. That rejects the incidental match and keeps the real one.
        """
        requirement_stems = self._stems(requirement)
        if not requirement_stems:
            return None
        best: DatabaseEntity | None = None
        best_score = -1.0
        for candidate in database_design.entities:
            name_stems = self._stems(candidate.name)
            if not name_stems or not (name_stems <= requirement_stems):
                continue
            vocabulary = name_stems | self._stems(candidate.description) | {
                self._stem(token)
                for field in candidate.fields
                for token in self._tokens(field.name)
            }
            score = len(requirement_stems & vocabulary) / len(requirement_stems)
            if score > best_score:
                best_score = score
                best = candidate
        return best

    def _class_diagram(self, database_design: DatabaseDesign) -> DiagramArtifact:
        selected_entities = self._diagram_entities(database_design)
        selected_names = {entity.name for entity in selected_entities}

        mermaid_lines = ["classDiagram"]
        plantuml_lines = ["@startuml", "hide empty members"]

        for entity in selected_entities:
            alias = self._entity_alias(entity.name)
            mermaid_lines.append(f"class {alias} {{")
            plantuml_lines.append(f"class {alias} {{")
            for field in entity.fields[:CLASS_FIELD_LIMIT]:
                # `+name : Type` — UML member syntax with visibility. The type
                # is a UML type, not a SQL one, so it carries no parentheses:
                # a member containing `()` is rendered by Mermaid in the
                # methods compartment, which is what put every VARCHAR column
                # among this class's operations.
                declared = uml_type(field.data_type)
                # UML expresses optionality as multiplicity, not as a `?` glued
                # to the type name.
                multiplicity = " [0..1]" if field.nullable else ""
                mermaid_lines.append(f"  +{field.name} : {declared}{multiplicity}")
                plantuml_lines.append(f"  +{field.name} : {declared}{multiplicity}")
            mermaid_lines.append("}")
            plantuml_lines.append("}")

        for relation in database_design.relationships:
            if relation.source not in selected_names or relation.target not in selected_names:
                continue
            parent = self._entity_alias(relation.target)
            child = self._entity_alias(relation.source)
            parent_cardinality, child_cardinality = self._class_cardinality(
                relation.relationship
            )
            label = self._relationship_label(relation)
            mermaid_lines.append(
                f'{parent} "{parent_cardinality}" --> "{child_cardinality}" {child} : {label}'
            )
            plantuml_lines.append(
                f'{parent} "{parent_cardinality}" --> "{child_cardinality}" {child} : {label}'
            )

        plantuml_lines.append("@enduml")
        return DiagramArtifact(
            title="Class Diagram",
            description="Highlights the core platform entities, key fields, and relationship multiplicities.",
            mermaid="\n".join(mermaid_lines),
            plantuml="\n".join(plantuml_lines),
        )

    def _er_diagram(self, database_design: DatabaseDesign) -> DiagramArtifact:
        selected_entities = self._diagram_entities(database_design)
        selected_names = {entity.name for entity in selected_entities}
        diagram_names = {
            entity.name: self._entity_diagram_name(entity.name) for entity in selected_entities
        }

        # Which columns are foreign keys, taken from the recorded relationships
        # rather than guessed from a naming convention. `foreign_key` is stored
        # as "table.column".
        foreign_keys: set[tuple[str, str]] = set()
        for relation in database_design.relationships:
            if not relation.foreign_key or "." not in relation.foreign_key:
                continue
            table, _, column = relation.foreign_key.partition(".")
            foreign_keys.add((table.strip(), column.strip()))

        entity_blocks: list[str] = []
        hidden_fields = 0
        for entity in selected_entities:
            entity_blocks.append(f"    {diagram_names[entity.name]} {{")
            shown = entity.fields[:ER_FIELD_LIMIT]
            hidden_fields += max(0, len(entity.fields) - len(shown))
            for field in shown:
                # Mermaid ER attributes are `type name [key] ["comment"]`. The
                # key slot is what makes an ER diagram readable, so primary and
                # foreign keys go there instead of being faked into the name
                # with a `*` prefix, and nullability goes in the comment slot
                # instead of being appended to the type — `VARCHAR?` is not a
                # type Mermaid understands.
                keys: list[str] = []
                if field.name == "id":
                    keys.append("PK")
                if (entity.name, field.name) in foreign_keys:
                    keys.append("FK")
                elif field.name.endswith("_id") and field.name != "id":
                    # A conventional reference column with no recorded
                    # relationship. Marked so the gap is visible rather than
                    # silently looking like an ordinary column.
                    keys.append("FK")
                key_slot = f" {','.join(keys)}" if keys else ""
                comment = ' "nullable"' if field.nullable else ""
                entity_blocks.append(
                    f"        {er_type(field.data_type)} {field.name}{key_slot}{comment}"
                )
            entity_blocks.append("    }")

        relations = []
        for relation in database_design.relationships:
            if relation.source not in selected_names or relation.target not in selected_names:
                continue
            parent_left, child_right = self._er_cardinality(relation.relationship)
            label = self._relationship_label(relation)
            relations.append(
                f'    {diagram_names[relation.target]} {parent_left}--{child_right} {diagram_names[relation.source]} : "{label}"'
            )

        plantuml_lines = ["@startuml", "!theme plain", "hide circle"]
        for entity in selected_entities:
            plantuml_lines.append(f"entity {diagram_names[entity.name]} {{")
            for field in entity.fields[:6]:
                field_type = f"{field.data_type}{'?' if field.nullable else ''}"
                prefix = "*" if field.name == "id" else ""
                plantuml_lines.append(f"  {prefix}{field.name} : {field_type}")
            plantuml_lines.append("}")
        for relation in database_design.relationships:
            if relation.source not in selected_names or relation.target not in selected_names:
                continue
            parent_left, child_right = self._er_cardinality(relation.relationship)
            plantuml_lines.append(
                f"{diagram_names[relation.target]} {parent_left}--{child_right} {diagram_names[relation.source]} : {self._relationship_label(relation)}"
            )
        plantuml_lines.append("@enduml")

        return DiagramArtifact(
            title="ER Diagram",
            description="Displays a clearer relational view with primary keys, optional fields, and explicit relationship cardinalities.",
            mermaid="\n".join(["erDiagram", *entity_blocks, *relations]),
            plantuml="\n".join(plantuml_lines),
        )

    def _component(self, architecture: ArchitectureOption) -> DiagramArtifact:
        grouped_components = {
            "Experience Layer": [],
            "Application Services": [],
            "Data & State": [],
            "Async & Operations": [],
        }

        for component in architecture.components:
            tier = self._component_tier(component.name)
            grouped_components[tier].append(component)

        mermaid_lines = ["flowchart LR"]
        for group_name, components in grouped_components.items():
            if not components:
                continue
            group_id = self._to_identifier(group_name).upper()
            mermaid_lines.append(f'    subgraph {group_id}["{group_name}"]')
            mermaid_lines.append("        direction TB")
            for component in components:
                component_id = self._component_id(component.name)
                label = self._wrap_label(
                    f"{component.name}\n{', '.join(component.technologies[:2])}", 18, html=True
                )
                mermaid_lines.append(f'        {component_id}["{label}"]')
            mermaid_lines.append("    end")

        connections = self._component_connections(architecture)
        for left, right, reason in connections:
            mermaid_lines.append(
                f'    {self._component_id(left.name)} -->|"{self._diagram_text(reason)}"| {self._component_id(right.name)}'
            )

        plantuml_lines = ["@startuml", "skinparam componentStyle rectangle"]
        if not architecture.components:
            mermaid_lines.append('    Empty["No runtime components are confirmed"]')
            plantuml_lines.append('note "No runtime components are confirmed" as Empty')
        for group_name, components in grouped_components.items():
            if not components:
                continue
            plantuml_lines.append(f'package "{group_name}" {{')
            for component in components:
                plantuml_lines.append(
                    f'component "{component.name}\\n{", ".join(component.technologies[:2])}" as {self._component_id(component.name)}'
                )
            plantuml_lines.append("}")
        for left, right, reason in connections:
            plantuml_lines.append(
                f"{self._component_id(left.name)} --> {self._component_id(right.name)} : {self._diagram_text(reason)}"
            )
        plantuml_lines.append("@enduml")

        return DiagramArtifact(
            title="Component Diagram",
            description="Groups the recommended runtime building blocks into clearer architectural tiers.",
            mermaid="\n".join(mermaid_lines),
            plantuml="\n".join(plantuml_lines),
        )

    def _deployment(self, deployment_plan: DeploymentPlan) -> DiagramArtifact:
        # Dynamic deployment only: the diagram renders the deployment plan's
        # own services/stack so no generator-app template can leak in.
        return self._dynamic_deployment(deployment_plan)

    def _dynamic_deployment(self, plan: DeploymentPlan) -> DiagramArtifact:
        """A UML deployment diagram: nodes containing artifacts.

        Previously this drew edges in two directions for no reason
        (`Plan --> Runtime{i}` but `Platform{i} --> Plan`), and drew the region
        list and replica count as graph nodes with arrows into the plan — so
        "Replicas: 2" appeared to be a deployed thing that talks to the
        deployment model.

        UML deployment notation has the right places for all of this. A
        **node** is a unit that executes things; **artifacts** are what is
        deployed onto it; region and replica are **properties of the node**, so
        they belong in its label. The target stack is the platform the node
        runs on, joined by a single **communication path** (a plain line, not
        an arrow — direction is not known and none is implied).
        """
        runtime_items = self._unique(
            [*plan.docker_services, *plan.kubernetes_modules]
        )[:10]
        platform_items = self._unique(plan.target_stack)[:6]

        # Region and replica count are node properties, rendered into the node
        # label the way UML tags a node, not as separate boxes.
        properties: list[str] = []
        if plan.replicas is not None:
            properties.append(f"replicas = {plan.replicas}")
        if plan.regions:
            properties.append(f"regions = {self._diagram_text(', '.join(plan.regions))}")
        node_label = f"«node» {self._diagram_text(plan.deployment_model)}"
        if properties:
            # UML writes a node's properties as tagged values in braces beside
            # its name. On one line, because Mermaid reserves the height of a
            # single-line subgraph title: a `<br/>` in the title rendered the
            # second line on top of the artifacts inside the node.
            node_label += " {" + ", ".join(properties) + "}"

        mermaid_lines = [
            "flowchart TB",
            "    classDef node fill:#14181d,stroke:#f5a524,color:#f4f6f8;",
            "    classDef artifact fill:#20262d,stroke:#303840,color:#f4f6f8;",
            "    classDef platform fill:#14181d,stroke:#35b7c8,color:#f4f6f8;",
            f'    subgraph DEPLOY["{node_label}"]',
            "        direction TB",
        ]
        plantuml_lines = [
            "@startuml",
            f'node "{self._diagram_text(plan.deployment_model)}" as Plan {{',
        ]
        if properties:
            plantuml_lines.append("  ' " + "; ".join(properties))
        if runtime_items:
            for index, item in enumerate(runtime_items, start=1):
                label = self._diagram_text(self._wrap_label(item, 28, html=True))
                mermaid_lines.append(f'        Runtime{index}["«artifact» {label}"]:::artifact')
                plantuml_lines.append(
                    f'  artifact "{self._diagram_text(item)}" as Runtime{index}'
                )
        else:
            mermaid_lines.append(
                '        Runtime0["No deployable artifact is confirmed"]:::artifact'
            )
        mermaid_lines.append("    end")
        plantuml_lines.append("}")

        if platform_items:
            mermaid_lines.append('    subgraph PLATFORM["«execution environment» Target stack"]')
            mermaid_lines.append("        direction TB")
            plantuml_lines.append('node "Target stack" as Platform {')
            for index, item in enumerate(platform_items, start=1):
                label = self._diagram_text(self._wrap_label(item, 24, html=True))
                mermaid_lines.append(f'        Platform{index}["{label}"]:::platform')
                plantuml_lines.append(
                    f'  component "{self._diagram_text(item)}" as Platform{index}'
                )
            mermaid_lines.append("    end")
            plantuml_lines.append("}")
            # A communication path: an undirected line. The earlier arrows
            # asserted a call direction the deployment plan does not record.
            mermaid_lines.append("    DEPLOY --- PLATFORM")
            plantuml_lines.append("Plan -- Platform")

        plantuml_lines.append("@enduml")

        described = [f"{len(runtime_items)} deployable artifact(s)"]
        if platform_items:
            described.append(f"a target stack of {len(platform_items)} element(s)")
        if properties:
            described.append("confirmed region and replica settings as node properties")
        return DiagramArtifact(
            title="Deployment Diagram",
            description=(
                f"The {self._diagram_text(plan.deployment_model)} node with "
                + ", ".join(described)
                + ". Nothing not present in the deployment plan is added."
            ),
            mermaid="\n".join(mermaid_lines),
            plantuml="\n".join(plantuml_lines),
        )

    def _component_connections(
        self, architecture: ArchitectureOption
    ) -> list[tuple[ArchitectureComponent, ArchitectureComponent, str]]:
        connections: list[tuple[ArchitectureComponent, ArchitectureComponent, str]] = []
        seen: set[tuple[str, str]] = set()
        by_name = {component.name.casefold(): component for component in architecture.components}
        for component in architecture.components:
            for dependency_name in component.dependencies:
                target = by_name.get(dependency_name.casefold())
                if target is None or target.name == component.name:
                    continue
                key = (component.name.casefold(), target.name.casefold())
                if key not in seen:
                    seen.add(key)
                    connections.append((component, target, "runtime dependency"))
        for component in architecture.components:
            if component.dependencies:
                continue
            for interaction in component.interactions:
                target = next(
                    (
                        candidate
                        for candidate in architecture.components
                        if candidate.name != component.name
                        and candidate.name.casefold() in interaction.casefold()
                    ),
                    None,
                )
                if target is None:
                    continue
                key = (component.name.casefold(), target.name.casefold())
                if key in seen:
                    continue
                seen.add(key)
                connections.append((component, target, interaction))
        return connections

    def _use_case_actor_profiles(
        self, requirements: RequirementModel
    ) -> list[tuple[Actor, set[str]]]:
        """Return clean, traceable actor profiles for a use-case diagram.

        Authentication mechanisms such as SSO are not actors. They are removed
        from role labels and merged into an existing canonical role. Explicit
        user renames retain the old role as an alias, allowing requirements
        that still use the previous wording to remain connected.
        """
        grouped: dict[str, tuple[Actor, set[str], bool]] = {}
        order: list[str] = []
        for source in requirements.actors:
            raw_name = " ".join(str(source.name or "").split())
            if not raw_name:
                continue
            tokens = set(tokenize(raw_name))
            has_access_prefix = bool(tokens & _ACCESS_MECHANISM_TERMS)
            canonical = _normalize_role(raw_name)
            user_edited = any(
                evidence.status == "user-edited"
                for evidence in source.source_evidence
            )
            if not canonical and not user_edited:
                continue
            display_name = canonical or raw_name
            if display_name.isupper() or display_name.islower():
                display_name = " ".join(
                    word.capitalize() for word in display_name.split()
                )
            key = display_name.casefold()
            aliases = self._actor_aliases(source) | {raw_name, display_name}
            candidate = source.model_copy(deep=True)
            candidate.name = display_name

            if key not in grouped:
                grouped[key] = (candidate, aliases, has_access_prefix)
                order.append(key)
                continue

            current, current_aliases, current_has_access = grouped[key]
            preferred = (
                candidate if current_has_access and not has_access_prefix else current
            )
            other = current if preferred is candidate else candidate
            preferred.responsibilities = list(dict.fromkeys([
                *preferred.responsibilities,
                *other.responsibilities,
            ]))
            preferred.permissions = list(dict.fromkeys([
                *preferred.permissions,
                *other.permissions,
            ]))
            preferred.source_evidence = [
                *preferred.source_evidence,
                *[
                    evidence
                    for evidence in other.source_evidence
                    if evidence not in preferred.source_evidence
                ],
            ]
            grouped[key] = (
                preferred,
                current_aliases | aliases,
                current_has_access and has_access_prefix,
            )

        return [(grouped[key][0], grouped[key][1]) for key in order]

    def _actors_for_use_case(
        self,
        requirements: RequirementModel,
        requirement: str,
        profiles: list[tuple[Actor, set[str]]],
    ) -> list[int]:
        """Find every confirmed participant in one actor goal."""
        matched: list[int] = []

        def add(index: int) -> None:
            if index not in matched:
                matched.append(index)

        for workflow in requirements.domain_workflows:
            if self._text_overlap(workflow.description, requirement) < 0.65:
                continue
            owner = workflow.primary_actor.strip()
            if not owner or owner.casefold() in self._UNKNOWN_ACTOR_LABELS:
                continue
            for index, (_, aliases) in enumerate(profiles):
                if any(alias.casefold() == owner.casefold() for alias in aliases):
                    add(index)

        for index, (_, aliases) in enumerate(profiles):
            if any(self._names_actor(requirement, alias) for alias in aliases):
                add(index)
        if matched:
            return matched

        requirement_tokens = self._stems(requirement)
        best_index: int | None = None
        best_score = 0.0
        for index, (actor, aliases) in enumerate(profiles):
            vocabulary: set[str] = set()
            for alias in aliases:
                vocabulary |= self._stems(alias)
            vocabulary |= self._stems(" ".join(actor.responsibilities))
            score = self._containment(requirement_tokens, vocabulary)
            weak = self._containment(
                requirement_tokens, self._stems(actor.description)
            )
            score = max(score, weak * 0.5)
            if score > best_score:
                best_score = score
                best_index = index
        if best_index is not None and best_score >= 0.2:
            return [best_index]

        heading = re.sub(
            r"^(?:support|enable|allow|provide)\s+",
            "",
            requirement.strip(),
            flags=re.IGNORECASE,
        )
        if extract_actors(heading):
            return []

        operational_heads = {
            "admin", "administrator", "operator", "manager", "staff",
            "analyst", "auditor", "officer", "supervisor",
        }
        primary = [
            index
            for index, (actor, _) in enumerate(profiles)
            if actor.actor_type == "human"
            and not (set(tokenize(actor.name)) & operational_heads)
        ]
        return primary if len(primary) == 1 else []

    def _actor_aliases(self, actor: Actor) -> set[str]:
        aliases = {" ".join(str(actor.name or "").split())}
        for evidence in actor.source_evidence:
            text = " ".join(
                str(evidence.excerpt or evidence.source or "").split()
            )
            match = re.search(
                r"\bfrom\s+(.+?)\s+to\s+(.+?)(?:[.!?]|$)",
                text,
                flags=re.IGNORECASE,
            )
            if not match:
                match = re.search(
                    r"\b(?:rename|renamed)\s+(?:the\s+)?actor\s+(.+?)\s+to\s+(.+?)(?:[.!?]|$)",
                    text,
                    flags=re.IGNORECASE,
                )
            if not match:
                continue
            old_name, new_name = (part.strip(" '\"") for part in match.groups())
            if new_name.casefold() == actor.name.casefold() and old_name:
                aliases.add(old_name)
        return {alias for alias in aliases if alias}

    def _actor_for_requirement(
        self, requirements: RequirementModel, requirement: str
    ) -> int | None:
        for workflow in requirements.domain_workflows:
            if self._text_overlap(workflow.description, requirement) >= 0.65:
                for index, actor in enumerate(requirements.actors):
                    if actor.name.casefold() == workflow.primary_actor.casefold():
                        return index
        requirement_tokens = self._stems(requirement)
        best_index = None
        best_score = 0.0
        for index, actor in enumerate(requirements.actors):
            # The actor's own name is the strongest signal and is checked
            # first: a requirement that says "Operator controls ..." belongs to
            # the Operator, whatever the descriptions say.
            if any(
                self._names_actor(requirement, alias)
                for alias in self._actor_aliases(actor)
            ):
                return index

            # Name and responsibilities are statements about what this actor
            # does. The free-text description is prose and is deliberately
            # weighted down: including it at full weight is what let an actor
            # with a longer description outscore every other actor and collect
            # the payment, cancellation and refund use cases.
            vocabulary = self._stems(actor.name) | self._stems(
                " ".join(actor.responsibilities)
            )
            score = self._containment(requirement_tokens, vocabulary)
            weak = self._containment(requirement_tokens, self._stems(actor.description))
            score = max(score, weak * 0.5)
            if score > best_score:
                best_score = score
                best_index = index
        return best_index if best_score >= 0.2 else None

    @staticmethod
    def _containment(requirement_stems: set[str], actor_vocabulary: set[str]) -> float:
        """How much of the requirement the actor's vocabulary accounts for.

        Containment, not symmetric overlap: a short requirement matched against
        a fuller vocabulary should still score well, and dividing by the union
        instead dropped genuine associations (slot reservations, secure
        payment) below the threshold. The length bias containment used to carry
        is removed by scoring against name and responsibilities rather than
        against prose.

        A single shared stem is not evidence — "charging" appears in most
        requirements of a charging project — so two are required.
        """
        if not requirement_stems or not actor_vocabulary:
            return 0.0
        shared = requirement_stems & actor_vocabulary
        if len(shared) < 2:
            return 0.0
        return len(shared) / len(requirement_stems)

    def _names_actor(self, requirement: str, actor_name: str) -> bool:
        """Whether the requirement text actually names this actor.

        Matched on word boundaries over stems, so "Operator controls" finds
        "Operator" and "Admin analytics" finds "Admin", while "administration"
        does not accidentally satisfy a differently named actor.
        """
        name_stems = self._stems(actor_name)
        if not name_stems:
            return False
        return name_stems <= self._stems(requirement)

    def _stems(self, value: str) -> set[str]:
        """Tokens reduced to a crude stem so plurals and verb forms agree.

        "Slot reservations" has to match an actor who "reserves slots"; without
        stemming, `reservations`/`reserves` and `slot`/`slots` are four
        different tokens and the association is missed, which sent the slot
        reservation, cancellation and refund use cases to no actor at all.
        """
        stems: set[str] = set()
        for token in self._tokens(value):
            stems.add(self._stem(token))
        return stems

    # Longest first, so "reservations" loses "ations" rather than "s". Derived
    # from the word pairs that were actually failing to match, not from a
    # general-purpose stemmer: the goal is that two spellings of one idea agree,
    # which matters more than producing a real English root.
    _SUFFIXES = (
        "abilities", "ability", "ations", "ation", "ements", "ement",
        "ments", "ment", "ingly", "ings", "ing", "edly", "ables", "able",
        "ibles", "ible", "ers", "er", "ors", "or", "ies", "ied", "ives",
        "ive", "ances", "ance", "ences", "ence", "ities", "ity", "ally",
        "ly", "ed", "ions", "ion", "ses", "es", "s", "y",
    )

    # English nominalizations that no suffix rule recovers: the noun and the
    # verb do not share a spelling ("submission"/"submit",
    # "verification"/"verify"). This is language, not domain vocabulary — it
    # adds no facts about any project — and without it a requirement written
    # as a noun never matches an actor described with the verb.
    _IRREGULAR_STEMS = {
        "submission": "submit", "submissions": "submit",
        "permission": "permit", "permissions": "permit",
        "transmission": "transmit", "transmissions": "transmit",
        "verification": "verify", "verifications": "verify",
        "notification": "notify", "notifications": "notify",
        "classification": "classify", "classifications": "classify",
        "modification": "modify", "modifications": "modify",
        "specification": "specify", "specifications": "specify",
        "identification": "identify",
        "description": "describe", "descriptions": "describe",
        "subscription": "subscribe", "subscriptions": "subscribe",
        "prescription": "prescribe", "prescriptions": "prescribe",
        "decision": "decide", "decisions": "decide",
        "production": "produce", "consumption": "consume",
        "reception": "receive", "conception": "conceive",
        "analysis": "analyze", "analyses": "analyze", "analytics": "analyze",
        "delivery": "deliver", "deliveries": "deliver",
        "inventory": "inventory", "inventories": "inventory",
    }

    @classmethod
    def _stem(cls, token: str) -> str:
        """A crude stem, consistent across the spellings of one idea.

        The previous version stripped "ing" and "ation" and nothing else, so
        the same idea produced different stems and the association was missed:
        "charging" became `charg` but "charger" stayed `charger`; "payment"
        never met "pay"; "discovery" never met "discover"; and "cancellation",
        "cancelled" and "cancel" produced three different stems. That is what
        left the slot reservation, secure payment, session tracking and
        cancellation use cases attached to no actor at all.

        Each normalization below is bounded at four characters so the stems stay
        distinctive. Over-stemming is worse than under-stemming here: a short
        stem collides with unrelated words and invents an association, and an
        invented association is a wrong diagram rather than an incomplete one.
        """
        token = cls._IRREGULAR_STEMS.get(token, token)
        # Two passes, because a word can carry two suffixes: "discovery" needs
        # to lose "y" and then "er" to reach the stem "discover" reduces to,
        # and one pass left them as `discover` and `discov`.
        for _ in range(2):
            for suffix in cls._SUFFIXES:
                if len(token) > len(suffix) + 2 and token.endswith(suffix):
                    token = token[: -len(suffix)]
                    break
            else:
                break
        # "cancellation" -> "cancell" -> "cancel", which is also what
        # "cancelled" and "cancel" reduce to.
        if len(token) > 4 and token[-1] == token[-2] and token[-1].isalpha():
            token = token[:-1]
        # "reserve" -> "reserv", matching "reservations"; "manage" -> "manag",
        # matching "management".
        if len(token) > 4 and token.endswith("e"):
            token = token[:-1]
        # "operator" -> "operat" -> "oper", matching "operations".
        if len(token) > 5 and token.endswith("at"):
            token = token[:-2]
        return token

    def _best_text_match(
        self,
        text: str,
        items: list[T],
        key: Callable[[T], str],
        minimum_shared: int = 1,
    ) -> T | None:
        """The item whose vocabulary best overlaps `text`, or None.

        `minimum_shared` guards against a match on one incidental word. With
        the default of 1, a requirement mentioning "user" matched the platform's
        `users` auth table and the sequence diagram drew it as this domain's
        data store. Callers that need a substantive match pass 2.
        """
        # Stems, not raw tokens: "Prescription upload." has to reach the
        # `prescriptions` entity, and "Slot booking." the `bookings` one.
        # Matching on raw tokens missed every plural and every noun/verb pair,
        # so most projects drew no data participant at all.
        text_tokens = self._stems(text)
        best = None
        best_score = 0.0
        for item in items:
            item_tokens = self._stems(key(item))
            shared = text_tokens & item_tokens
            if len(shared) < minimum_shared:
                continue
            score = len(shared) / max(len(text_tokens), 1)
            if score > best_score:
                best = item
                best_score = score
        return best if best_score > 0 else None

    def _confirmed_actor_name(self, candidate: str, requirements: RequirementModel) -> str:
        """A real actor name, never a placeholder the extractor wrote.

        `primary_actor` carries strings like "Needs clarification" when the
        analyser could not identify the actor. Drawing one as an actor name in a
        sequence diagram asserts an actor the requirement model does not have.
        """
        label = self._diagram_text(candidate).strip()
        if label and label.casefold() not in self._UNKNOWN_ACTOR_LABELS:
            return label
        for actor in requirements.actors:
            fallback = self._diagram_text(actor.name).strip()
            if fallback and fallback.casefold() not in self._UNKNOWN_ACTOR_LABELS:
                return fallback
        return "Actor (not confirmed)"

    def _text_overlap(self, left: str, right: str) -> float:
        left_tokens = self._tokens(left)
        right_tokens = self._tokens(right)
        return len(left_tokens & right_tokens) / max(min(len(left_tokens), len(right_tokens)), 1)

    def _tokens(self, value: str) -> set[str]:
        stop = {"and", "are", "can", "for", "from", "must", "should", "system", "the", "their", "this", "with"}
        return {
            token for token in re.findall(r"[a-z][a-z0-9_-]+", value.casefold())
            if token not in stop and len(token) > 2
        }

    # Labels the requirement analyser writes when it could not classify the
    # domain. `RequirementModel.domain` has to keep them — the signal layer and
    # the clarification engine both branch on them — but a diagram must not
    # print one as the system's name. The use case boundary read
    # `Unknown domain`, the sequence diagram named a participant
    # `Unknown domain Core`, and the component diagram created a component
    # called `UNKNOWN_DOMAIN_CORE`, all of which assert a domain called
    # "Unknown".
    _UNCLASSIFIED_DOMAIN_LABELS = {"unknown", "unknown domain", "", "n/a", "tbd"}

    def _system_label(self, domain: str) -> str:
        """A name for the system that is true even when the domain is unknown."""
        label = self._diagram_text(domain or "")
        if label.casefold() in self._UNCLASSIFIED_DOMAIN_LABELS:
            return "System"
        return label

    def _diagram_text(self, value: str) -> str:
        return " ".join(value.replace('"', "'").replace(";", ",").split())

    def _unique(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            key = value.casefold()
            if key not in seen:
                seen.add(key)
                result.append(value)
        return result

    def _clean_use_case_label(self, requirement: str) -> str:
        cleaned = requirement.strip().rstrip(".")
        cleaned = re.sub(
            r"^(the system (shall|must|should|will)|we (shall|must|should|will)|it (shall|must|should|will))\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^(support|allow|enable|provide|expose|deliver|keep|implement|handle|process|ensure|maintain|manage|offer|give|make)\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.split(r"\s+(with|using|via|through|including|that|which)\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)[0]
        cleaned = cleaned.replace(" and ", " & ").replace("/", " / ")
        if not cleaned:
            return ""
        return cleaned[0].upper() + cleaned[1:]

    def _derive_support_labels(self, primary_labels: list[str]) -> list[str]:
        supports: list[str] = []
        seen: set[str] = set()
        for label in primary_labels:
            lower = label.lower()
            candidates: list[str] = []
            if any(kw in lower for kw in ("search", "browse", "find", "catalog", "list")):
                candidates.append("View details")
            if any(kw in lower for kw in ("create", "add", "register", "sign up", "new")):
                candidates.append("Confirm entry")
            if any(kw in lower for kw in ("pay", "checkout", "purchase", "billing", "invoice")):
                candidates.append("Process payment")
            if any(kw in lower for kw in ("cancel", "refund", "withdraw")):
                candidates.append("Process refund")
            if any(kw in lower for kw in ("report", "analytics", "dashboard", "stats")):
                candidates.append("Export data")
            if any(kw in lower for kw in ("upload", "import", "attach")):
                candidates.append("Validate file")
            if any(kw in lower for kw in ("track", "monitor", "status")):
                candidates.append("View progress")
            for c in candidates:
                if c not in seen:
                    seen.add(c)
                    supports.append(c)
        return supports[:3]

    def _entity_alias(self, entity_name: str) -> str:
        singular = entity_name
        if singular.endswith("ies"):
            singular = singular[:-3] + "y"
        elif singular.endswith("s") and not singular.endswith("ss"):
            singular = singular[:-1]
        return "".join(part.capitalize() for part in singular.split("_"))

    def _entity_diagram_name(self, entity_name: str) -> str:
        singular = entity_name
        if singular.endswith("ies"):
            singular = singular[:-3] + "y"
        elif singular.endswith("s") and not singular.endswith("ss"):
            singular = singular[:-1]
        return "_".join(part.upper() for part in singular.split("_"))

    def _relationship_label(self, relation: DatabaseRelationship) -> str:
        """A label derived from the model, not from a list of known domains.

        This used to be forty hardcoded `source == "bookings" and target ==
        "users"` pairs covering booking, pharmacy and retail schemas, with
        everything else falling through to the word "references". That both
        breaks the project's own rule against special-casing industries and
        labels most real projects uninformatively.

        The foreign key column is the most useful thing that can be said and is
        always true: `chargers.station_id` reads as "via station_id", and the
        reader can trace it. Where the recorded description carries a real verb
        phrase, that is preferred, because a human wrote it.
        """
        if relation.relationship == "flows-to":
            return "flows to"

        # A verb phrase the model already recorded beats anything derived.
        description = clean_label_text(relation.description)
        verb = extract_relationship_verb(description)
        if verb:
            return verb

        # Otherwise name the column that implements the relationship.
        if relation.foreign_key and "." in relation.foreign_key:
            _, _, column = relation.foreign_key.partition(".")
            column = column.strip()
            if column:
                return f"via {column}"

        target_clean = relation.target.replace("_", " ").rstrip("s")
        return f"relates to {target_clean}"

    def _class_cardinality(self, relationship: str) -> tuple[str, str]:
        if relationship == "one-to-one":
            return ("1", "0..1")
        if relationship == "one-to-many":
            return ("0..*", "1")
        return ("1", "0..*")

    def _er_cardinality(self, relationship: str) -> tuple[str, str]:
        if relationship == "one-to-one":
            return ("||", "||")
        if relationship == "one-to-many":
            return ("o{", "||")
        return ("||", "o{")

    def _component_tier(self, component_name: str) -> str:
        lower_name = component_name.lower()
        if any(keyword in lower_name for keyword in ("client", "frontend", "web", "gateway")):
            return "Experience Layer"
        if any(keyword in lower_name for keyword in ("postgres", "database", "persistence", "redis")):
            return "Data & State"
        if any(keyword in lower_name for keyword in ("background", "workflow", "event", "queue")):
            return "Async & Operations"
        return "Application Services"

    def _component_id(self, component_name: str) -> str:
        return self._to_identifier(component_name).upper()

    def _diagram_entities(self, database_design: DatabaseDesign) -> list[DatabaseEntity]:
        # Prefer entities participating in real relationships, then preserve
        # source order. This keeps ownership edges visible for every domain
        # without a special-case entity list for selected industries.
        degree = {entity.name: 0 for entity in database_design.entities}
        for relationship in database_design.relationships:
            if relationship.source in degree and relationship.target in degree:
                degree[relationship.source] += 1
                degree[relationship.target] += 1
        ordered = sorted(
            enumerate(database_design.entities),
            key=lambda item: (-degree[item[1].name], item[0]),
        )
        return [entity for _, entity in ordered[:12]]

    def _to_identifier(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")

    def _wrap_label(self, value: str, width: int, html: bool = False) -> str:
        pieces = wrap(value, width=width) or [value]
        separator = "<br/>" if html else "\\n"
        return separator.join(pieces)
