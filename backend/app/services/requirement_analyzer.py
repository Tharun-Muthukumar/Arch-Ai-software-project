import logging
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

from app.schemas.domain import (
    Actor,
    DomainEntityHint,
    DomainWorkflowHint,
    RequirementModel,
    SourceEvidence,
)
from app.services.ai.client import OllamaStructuredClient
from app.services.domain_inference import (
    _normalize_role,
    capability_object_tokens,
    classify_domain,
    extract_actors,
    extract_capabilities,
    extract_entities,
    extract_integrations,
    normalize_constraint_statements,
    payment_evidence_level,
    singularize,
    split_sentences,
    to_display_name,
    tokenize,
)
from app.services.project_signals import clarification_category, hydrate_project_signals


@dataclass(frozen=True)
class DomainBlueprint:
    domain: str
    keywords: tuple[str, ...]
    actors: tuple[tuple[str, str], ...]
    features: tuple[str, ...]
    entities: tuple[str, ...]
    compliance: tuple[str, ...]


class UnknownDomainExtraction(BaseModel):
    domain: str = Field(min_length=3, max_length=100)
    summary: str = Field(min_length=10, max_length=500)
    # Minimums are intentionally loose: a thin but valid field (e.g. a single
    # workflow, zero NFRs) must not invalidate an otherwise grounded
    # extraction. Quality gates after parsing (functional >= 2, actor/entity
    # backfill, workflow rebuild) decide what survives, not schema arity.
    functional_requirements: list[str] = Field(min_length=1, max_length=10)
    non_functional_requirements: list[str] = Field(default_factory=list, max_length=6)
    actors: list[str] = Field(default_factory=list, max_length=6)
    domain_entities: list[str] = Field(default_factory=list, max_length=8)
    domain_workflows: list[str] = Field(default_factory=list, max_length=6)
    integrations: list[str] = Field(default_factory=list, max_length=8)
    data_characteristics: list[str] = Field(default_factory=list, max_length=8)
    explicit_constraints: list[str] = Field(default_factory=list, max_length=8)
    assumptions: list[str] = Field(default_factory=list, max_length=6)
    open_questions: list[str] = Field(default_factory=list, max_length=8)


class SemanticActorItem(BaseModel):
    name: str = Field(min_length=2, max_length=60, description="Concise role or system title")
    actor_type: Literal[
        "human", "organizational", "external-partner", "external-system", "device", "machine"
    ] = Field(default="human", description="Role category")
    responsibilities: list[str] = Field(default_factory=list, max_length=4, description="Key actions this actor performs")
    permissions: list[str] = Field(default_factory=list, max_length=4, description="Authorized actions or workflows")
    source_evidence: list[str] = Field(default_factory=list, max_length=4, description="Supporting evidence quotes or requirement IDs")


class SemanticActorExtraction(BaseModel):
    actors: list[SemanticActorItem] = Field(default_factory=list, max_length=8)


UNKNOWN_ANSWER_VALUES = {
    "n/a",
    "needs discussion",
    "no preference",
    "not applicable",
    "not specified",
    "not specified yet",
    "undecided",
    "unknown",
}

UNCERTAIN_TOPIC_MARKERS = (
    ("cloud hosting", ("cloud", "hosting", "provider"), ("cloud", "hosting", "provider")),
    (
        "workload scale",
        ("user count", "users", "traffic", "workload"),
        ("concurrency", "scale", "traffic", "user count", "user volume", "workload"),
    ),
    ("latency", ("latency", "response time"), ("latency", "response time")),
    (
        "availability",
        ("availability", "recovery", "sla", "uptime"),
        ("availability", "recovery", "sla", "uptime"),
    ),
    ("retention", ("retention",), ("retention", "retain", "retained")),
    ("team size", ("team", "team size"), ("staff", "team", "team size")),
    (
        "deployment regions",
        ("geography", "region", "regions"),
        ("data residency", "geography", "multi-region", "region", "regional"),
    ),
)


# Classification vocabulary is deliberately shared by the LLM-validation and
# deterministic paths.  Keeping it in one place prevents a sentence such as
# "the service must remain available" from becoming a constraint in one path
# and a functional requirement in the other.
QUALITY_REQUIREMENT_MARKERS = (
    "accessibility", "accuracy", "availability", "available", "uptime",
    "audit", "backup", "capacity", "confidential", "consistency",
    "data residency", "disaster recovery", "durability",
    "encrypt", "idempotent", "integrity", "latency", "maintainability",
    "observability", "offline", "performance", "privacy", "provenance",
    "real-time", "realtime", "recovery", "reliable", "resilien",
    "response time", "retention", "retain", "safe retry", "scalab",
    "security", "strongly consistent", "consistent", "throughput", "traceab", "usability",
    "high volume", "high volumes",
)

# These are architectural/solution boundaries rather than quality outcomes.
# They remain constraints even when their wording also contains a quality
# term (for example a mandated consistency or residency model).
SOLUTION_CONSTRAINT_MARKERS = (
    "must use", "shall use", "required to use", "must run", "must deploy",
    "must host", "only run", "only deploy", "only host", "cannot use",
    "must not use", "data residency", "in-country", "strongly consistent",
    "idempotent", "prevent duplicates", "regulation", "regulatory",
    "compliance", "compatible with", "team size", "hosting preference",
)


BLUEPRINTS = (
    DomainBlueprint(
        domain="EV Charging Booking Platform",
        keywords=("ev charging", "charging station", "charger", "charging slot", "slot reservation"),
        actors=(
            ("Driver", "Searches stations, reserves slots, pays securely, and manages charging sessions."),
            ("Station Operator", "Maintains stations, chargers, slot schedules, and availability states."),
            ("Platform Admin", "Reviews analytics, incidents, refunds, and operational performance."),
            ("Support Agent", "Resolves booking issues, refunds, and customer escalations."),
        ),
        features=(
            "Search nearby charging stations with connector, speed, and pricing filters.",
            "Check real-time charger availability and detailed station information.",
            "Reserve a charging slot and complete payment securely.",
            "Start, monitor, and stop charging sessions with live status feedback.",
            "Cancel bookings, request refunds, and review charging history.",
            "Enable station operators to manage stations, chargers, and slot availability.",
            "Provide admin dashboards for utilization, revenue, and incident tracking.",
        ),
        entities=("users", "stations", "chargers", "bookings", "charging_sessions", "payments"),
        compliance=("payment integrity", "station availability audit trail", "role-based access control"),
    ),
    DomainBlueprint(
        domain="Online Pharmacy",
        keywords=("pharmacy", "medicine", "drug", "prescription"),
        actors=(
            ("Customer", "Browses medicine catalog, uploads prescriptions, and tracks orders."),
            ("Pharmacist", "Validates prescriptions and manages inventory approvals."),
            ("Delivery Partner", "Handles order fulfillment and delivery confirmation."),
            ("Operations Admin", "Monitors stock, pricing, and platform activity."),
        ),
        features=(
            "Support catalog search with category and availability filtering.",
            "Allow prescription upload and pharmacist verification workflows.",
            "Enable secure checkout, payment, and order tracking.",
            "Manage stock levels, substitutions, and fulfillment SLAs.",
            "Trigger notifications for order status and prescription issues.",
        ),
        entities=(
            "users",
            "products",
            "inventory",
            "prescriptions",
            "orders",
            "order_items",
            "payments",
            "shipments",
        ),
        compliance=("PII protection", "prescription audit trail", "role-based access control"),
    ),
    DomainBlueprint(
        domain="E-Commerce Platform",
        keywords=("shop", "commerce", "store", "marketplace", "cart"),
        actors=(
            ("Buyer", "Searches products, places orders, and reviews order history."),
            ("Merchant", "Publishes catalog items and manages inventory levels."),
            ("Support Agent", "Handles refunds, disputes, and escalations."),
            ("Platform Admin", "Oversees pricing rules, users, and system health."),
        ),
        features=(
            "Support product catalog browsing, search, and rich filtering.",
            "Enable cart, checkout, payment, and returns management.",
            "Handle order lifecycle updates and customer notifications.",
            "Provide merchant-facing inventory and fulfillment tooling.",
            "Expose operational dashboards and audit logs for administrators.",
        ),
        entities=("users", "products", "inventory", "orders", "order_items", "payments", "shipments"),
        compliance=("PCI-aware payment integration", "audit logging", "data privacy controls"),
    ),
    DomainBlueprint(
        domain="Learning Platform",
        keywords=("course", "learning", "student", "education", "classroom"),
        actors=(
            ("Learner", "Consumes courses, submits work, and tracks progress."),
            ("Instructor", "Publishes lessons, assignments, and assessments."),
            ("Reviewer", "Grades submissions and moderates learner activity."),
            ("Program Admin", "Configures cohorts, analytics, and access policies."),
        ),
        features=(
            "Manage course catalogs, lessons, assignments, and assessments.",
            "Track enrollment, progress, submissions, and learner milestones.",
            "Send reminders, grading updates, and completion notifications.",
            "Provide instructor dashboards and analytics insights.",
            "Support role-based collaboration across cohorts and programs.",
        ),
        entities=("users", "courses", "enrollments", "lessons", "submissions", "notifications"),
        compliance=("access control", "content auditability", "retention policies"),
    ),
)


TECHNOLOGY_NAMES = (
    "aws",
    "azure",
    "cassandra",
    "docker",
    "dynamodb",
    "elasticsearch",
    "fastapi",
    "gcp",
    "kafka",
    "kubernetes",
    "mongodb",
    "mysql",
    "postgresql",
    "rabbitmq",
    "react",
    "redis",
    "terraform",
)

GENERIC_ACTOR_NAMES = {"application", "platform", "software", "system"}

SPECIAL_CHARACTERISTICS = {
    "realtime": (
        ("real-time", "realtime", "live", "immediate", "instant"),
        ("real-time", "realtime", "live", "immediate", "instant"),
    ),
    "offline": (
        ("offline", "disconnected", "without connectivity"),
        ("offline", "disconnected", "without connectivity"),
    ),
    "immutable": (
        ("immutable", "immutability", "append-only"),
        ("immutable", "immutability", "append-only"),
    ),
    "geospatial": (
        ("geospatial", "geographic", "location", "mapping"),
        ("geospatial", "geographic", "coordinates", "location", "map", "nearby"),
    ),
    "streaming": (
        ("event stream", "streaming", "telemetry"),
        ("as they arrive", "event stream", "streaming", "telemetry"),
    ),
    "external integration": (
        ("compatibility with", "external system", "integrate with", "integration with"),
        ("external", "import", "export", "integrat", "sync"),
    ),
    "multi-region": (
        ("multi-region", "multiple regions", "regional replication"),
        ("global", "multi-region", "multiple regions", "region", "regional"),
    ),
    "centralized synchronization": (
        ("central server", "centralized server", "central service"),
        ("central server", "centralized server", "central service"),
    ),
}

ACTION_FAMILIES = {
    "approval": ("approve", "approved", "approves", "approving", "approval"),
    "deletion": ("delete", "deleted", "deletes", "deleting", "deletion"),
    "export": ("export", "exported", "exporting"),
    "generation": ("generate", "generated", "generates", "generating", "generation"),
    "import": ("import", "imported", "importing"),
    "notification": ("notify", "notified", "notifies", "notification", "notifications"),
    "rejection": ("reject", "rejected", "rejecting", "rejection"),
    "synchronization": (
        "sync", "synchronize", "synchronized", "synchronizing", "synchronization"
    ),
    "upload": ("upload", "uploaded", "uploading"),
}


class RequirementAnalyzer:
    def __init__(self) -> None:
        self.ai_client = OllamaStructuredClient()

    def analyze(
        self,
        title: str,
        description: str,
        business_context: str | None = None,
        answers: dict[str, str] | None = None,
        constraints: list[str] | None = None,
        project_id: str | None = None,
    ) -> RequirementModel:
        answers = answers or {}
        constraints = constraints or []
        combined_text = " ".join(
            part for part in [title, description, business_context or ""] if part
        )
        blueprint = self._pick_blueprint(combined_text)
        if blueprint is None:
            model = self._analyze_unknown(
                title, description, business_context, answers, constraints, project_id
            )
        else:
            model = self._analyze_known(
                title,
                description,
                combined_text,
                business_context,
                answers,
                constraints,
                blueprint,
            )
        return hydrate_project_signals(model, answers)

    def _analyze_unknown(
        self,
        title: str,
        description: str,
        business_context: str | None,
        answers: dict[str, str],
        constraints: list[str],
        project_id: str | None = None,
    ) -> RequirementModel:
        effective_constraints = [*constraints, *self._constraints_from_answers(answers)]
        effective_constraints, fragment_merges = normalize_constraint_statements(
            effective_constraints
        )
        effective_constraints = self._dedupe_constraints(effective_constraints)
        raw_requirement = {
            "title": title,
            "description": description,
            "business_context": business_context,
            "user_constraints": effective_constraints,
            "clarification_answers": answers,
            "source_semantics": {
                "description": "product behavior and scope",
                "business_context": "background, goals, scale, and quality context; not product behavior unless it explicitly directs the software",
                "user_constraints": "confirmed hard boundaries",
                "clarification_answers": "confirmed typed facts",
            },
        }
        # Grounding separation: actors, entities, requirements, and constraints
        # must originate in the brief itself. Clarification answers are
        # structured constraints, not a source of business nouns — including
        # them in grounding once made `OAuth credentials` and `millions`
        # appear as domain entities. Answers still drive scale inference and
        # explicit constraint propagation below.
        context_requirements = self._business_context_requirement_text(business_context)
        functional_source = " ".join(
            part for part in (title, description, context_requirements) if part
        )
        actor_source = ". ".join([
            functional_source,
            *[
                value for key, value in answers.items()
                if self._answer_is_known(value)
                and clarification_category(key) == "domain"
            ],
        ])
        domain_source = " ".join(part for part in (title, description, context_requirements) if part)
        brief_source = " ".join(
            [title, description, business_context or "", *effective_constraints]
        )
        source_text = " ".join([brief_source, *answers.values()])
        generated = self.ai_client.generate(
            "unknown-domain-requirement-extraction",
            {"project_id": project_id, "raw_requirement": raw_requirement},
            response_schema=UnknownDomainExtraction.model_json_schema(),
            num_predict=850,
            num_ctx=4096,
            minimum_timeout_seconds=90,
        )
        if generated is None:
            return self._fallback_or_deterministic(
                title, description, business_context, answers, effective_constraints
            )

        try:
            extraction = UnknownDomainExtraction.model_validate(generated)
        except ValidationError as exc:
            return self._fallback_or_deterministic(
                title, description, business_context, answers, effective_constraints,
                prior_warnings=[
                    f"Ollama returned invalid structured requirements: {exc.errors()[0]['msg']}"
                ],
            )

        warnings: list[str] = []
        if fragment_merges:
            warnings.append(
                f"Merged {fragment_merges} constraint fragment(s) into complete statements."
            )
        functional = self._filter_grounded_items(
            extraction.functional_requirements, functional_source, warnings, "functional requirement"
        )
        if len(functional) < 2:
            return self._fallback_or_deterministic(
                title, description, business_context, answers, effective_constraints,
                prior_warnings=[
                    *warnings,
                    "Ollama output did not retain enough grounded functional detail.",
                ],
            )

        non_functional = self._filter_grounded_items(
            extraction.non_functional_requirements,
            brief_source,
            warnings,
            "non-functional requirement",
        )
        explicit_quality = self._filter_grounded_items(
            self._extract_explicit_quality_requirements(description, business_context),
            brief_source,
            warnings,
            "non-functional requirement",
        )
        non_functional = self._merge_explicit_items(non_functional, explicit_quality)
        _HARD_CONSTRAINT_MARKERS = (
            " must ", " must not ", " never ", " only ", " cannot ",
            " required ", " require ", " shall ", " at least ", " no more than ",
        )
        model_constraints = [
            item
            for item in self._filter_grounded_items(
                extraction.explicit_constraints, brief_source, warnings, "constraint"
            )
            if self._has_meaningful_overlap(item, brief_source)
            and "do not assume" not in item.casefold()
            and "don't assume" not in item.casefold()
            # Soft feature statements are not constraints: without a hard
            # obligation marker the model suggestion belongs in requirements
            # or open questions, never in constraints.
            and any(marker in f" {item.casefold()} " for marker in _HARD_CONSTRAINT_MARKERS)
        ]
        actors = self._extract_semantic_actors(
            title=title,
            description=description,
            business_context=business_context,
            functional_requirements=functional,
            integrations=extraction.integrations,
            answers=answers,
            project_id=project_id,
            seed_actors=extraction.actors,
        )
        entities = [
            DomainEntityHint(
                name=entity.strip(),
                description=f"{entity.strip()} identified from the user's brief.",
            )
            for entity in extraction.domain_entities
            if entity.strip()
            and self._label_is_safe(entity, domain_source)
            and self._tokens_fully_grounded(entity, domain_source)
        ]
        entities = self._dedupe_entities(entities)
        if len(entities) < 2:
            for identifier in extract_entities(domain_source, limit=14):
                display = to_display_name(identifier)
                if not display or not self._tokens_fully_grounded(display, domain_source):
                    continue
                if any(existing.name.casefold() == display.casefold() for existing in entities):
                    continue
                entities.append(DomainEntityHint(
                    name=display,
                    description=f"{display} identified from the project brief.",
                ))
                if len(entities) >= 8:
                    break
            entities = self._dedupe_entities(entities)
            if len(entities) >= 2:
                warnings.append("Ollama entities were thin; domain records backfilled from the brief.")
        workflows = self._build_workflow_hints(
            extraction.domain_workflows,
            functional,
            actors,
            entities,
            functional_source,
        )
        if not actors or len(entities) < 2 or len(workflows) < 2:
            return self._fallback_or_deterministic(
                title, description, business_context, answers, effective_constraints,
                prior_warnings=[
                    *warnings,
                    "Ollama output lacked grounded actors, entities, or workflows required by the pipeline.",
                ],
            )
        # Assumptions are a separate epistemic category.  A model suggestion is
        # not an assumption merely because it sounds plausible: retain it only
        # when the source itself explicitly labels the point as assumed.
        assumptions = [
            f"Assumption: {item.removeprefix('Assumption:').strip()}"
            for item in self._filter_grounded_items(
                extraction.assumptions,
                brief_source,
                warnings,
                "assumption",
                allow_inference=False,
            )
            if item.strip()
            and re.search(r"\bassum(?:e|ed|es|ing|ption)\b", brief_source, re.I)
        ]
        explicit_constraints = [
            *effective_constraints,
            *self._extract_explicit_constraints(description, business_context),
            *model_constraints,
        ]
        if (cloud := answers.get("preferred_cloud")) and self._answer_is_known(cloud):
            explicit_constraints.append(f"User-specified hosting preference: {cloud}.")
        if (team_raw := answers.get("team_size")) and self._answer_is_known(team_raw):
            team_number = self._parse_team_size(team_raw)
            if team_number > 0:
                explicit_constraints.append(f"User-specified team size: {team_number} engineers.")

        explicit_constraints = self._dedupe_constraints(explicit_constraints)

        summary = self._strip_unsupported_claims(extraction.summary, brief_source)
        if not summary:
            summary = f"{title}: {description}"

        source_integrations = self._extract_named_integrations(description, business_context)
        integration_candidates = source_integrations or [
            *extraction.integrations,
            *self._extract_integration_requirements(functional),
        ]
        integrations = self._drop_covered_integrations(
            self._dedupe(
                self._filter_grounded_items(
                    integration_candidates,
                    brief_source,
                    warnings,
                    "integration",
                )
            )
        )
        functional, explicit_constraints, integrations = self._preserve_uncovered_clauses(
            functional,
            explicit_constraints,
            integrations,
            description,
            business_context,
        )
        # Single workflow build from the FINAL validated functional list.
        # Earlier versions rebuilt workflows three times (twice from Ollama's
        # raw names, once empty), wasting the model's structure and letting
        # ungrounded workflow names leak into actors/entities.
        non_functional = self._ensure_non_functional_requirements(
            non_functional,
            actors,
            entities,
            [],
            brief_source,
        )
        functional = self._decompose_functional_requirements(functional)
        non_functional = self._decompose_non_functional_requirements(non_functional)
        functional, non_functional, explicit_constraints = self._reclassify_requirements(
            functional, non_functional, explicit_constraints
        )
        functional = self._split_multi_actor_requirements(functional, actors)
        workflows = self._build_workflow_hints(
            [], functional, actors, entities, functional_source
        )
        # Cross-field dedupe across ALL three textual categories: a statement
        # kept as a constraint must not also survive as FR/NFR and vice versa.
        functional = self._dedupe(functional)
        functional_keys = {self._requirement_key(item) for item in functional}
        constraint_keys = {self._requirement_key(item) for item in self._dedupe_constraints(explicit_constraints)}
        distinct_non_functional = [
            item
            for item in self._dedupe(non_functional)
            if self._requirement_key(item) not in functional_keys
            and self._requirement_key(item) not in constraint_keys
        ]
        if len(distinct_non_functional) != len(self._dedupe(non_functional)):
            warnings.append(
                "Removed requirement text duplicated across functional, non-functional, and constraint categories."
            )
        non_functional = distinct_non_functional
        explicit_constraints = [
            item for item in self._dedupe_constraints(explicit_constraints)
            if self._requirement_key(item) not in functional_keys
        ]

        domain = self._strip_unsupported_claims(extraction.domain, brief_source)
        if not domain:
            domain = "Unknown domain"
            warnings.append("Removed an ungrounded domain label.")

        # Open questions: drop topics the user already answered so clarified
        # workspaces stop re-asking scale/auth/sla/retention/cloud/team.
        _ANSWERED_TOPIC_MARKERS = {
            "auth": ("auth", "login", "sso", "password"),
            "scale": ("workload", "traffic", "concurrent", "scale"),
            "sla": ("availability", "sla", "uptime", "recovery", "failover"),
            "retention": ("retention", "retain", "archive"),
            "preferred_cloud": ("cloud", "hosting", "provider"),
            "team_size": ("team size", "engineers", "staffing"),
        }
        raw_questions = self._filter_grounded_items(
            extraction.open_questions,
            brief_source,
            warnings,
            "open question",
            allow_inference=True,
        )
        filtered_questions: list[str] = []
        for question in raw_questions:
            lower_q = question.casefold()
            answered = False
            for key, markers in _ANSWERED_TOPIC_MARKERS.items():
                if self._answer_is_known(str(answers.get(key, "") or "")) and answers.get(key):
                    if any(marker in lower_q for marker in markers):
                        answered = True
                        break
            if not answered:
                filtered_questions.append(question)

        # Post-classification guard: reclassification and cross-field dedupe
        # must never empty the functional list that passed the grounding gate
        # above. An empty FR set means the categories fought over the same
        # statements — fall back instead of emitting a requirement-less model.
        if not functional:
            return self._fallback_or_deterministic(
                title, description, business_context, answers, effective_constraints,
                prior_warnings=[
                    *warnings,
                    "Ollama requirements did not survive category separation; fell back to brief extraction.",
                ],
            )

        return RequirementModel(
            summary=summary,
            domain=domain,
            scale_profile=self._infer_scale_profile(source_text, answers, unknown_default=True),
            functional_requirements=functional,
            non_functional_requirements=non_functional,
            actors=actors,
            constraints=self._dedupe_constraints(explicit_constraints),
            assumptions=self._dedupe(assumptions),
            domain_entities=entities,
            domain_workflows=workflows,
            integrations=self._dedupe(integrations),
            data_characteristics=self._dedupe_characteristics(
                self._filter_grounded_items(
                    [
                        *extraction.data_characteristics,
                        *self._extract_explicit_data_characteristics(
                            description, business_context
                        ),
                    ],
                    brief_source,
                    warnings,
                    "data characteristic",
                    allow_inference=False,
                )
            ),
            open_questions=self._dedupe(
                [
                    *filtered_questions,
                    *self._extract_explicit_unknown_questions(
                        description, business_context
                    ),
                ]
            )[:8],
            analysis_source="ollama-pretrained",
            analysis_warnings=self._dedupe(warnings),
        )

    def _extract_semantic_actors(
        self,
        title: str,
        description: str,
        business_context: str | None,
        functional_requirements: list[str],
        integrations: list[str],
        answers: dict[str, str] | None = None,
        project_id: str | None = None,
        seed_actors: list[str] | list[dict] | None = None,
        call_ai: bool = True,
    ) -> list[Actor]:
        """Extract and deterministically validate genuine system actors using a focused Ollama semantic call.

        Passes compact context (brief, business context, functional requirements, integrations, and clarifications)
        to Ollama, then strictly validates the output to reject actions, workflow names, data concepts,
        technologies, generic nouns, requirement fragments, and full sentences.
        """
        answers = answers or {}
        context_requirements = self._business_context_requirement_text(business_context)
        product_source = ". ".join(
            part for part in [title, description, context_requirements] if part
        )
        actor_source = ". ".join([
            product_source,
            *[
                value for key, value in answers.items()
                if self._answer_is_known(value)
                and clarification_category(key) == "domain"
            ],
            *functional_requirements,
        ])
        combined_source = ". ".join(
            part for part in [title, description, business_context or ""] if part
        )

        candidates: list[SemanticActorItem] = []
        if seed_actors:
            for item in seed_actors:
                if isinstance(item, str) and item.strip():
                    candidates.append(SemanticActorItem(name=item.strip()))
                elif isinstance(item, dict):
                    try:
                        candidates.append(SemanticActorItem.model_validate(item))
                    except Exception:
                        pass

        if not candidates and call_ai and self.ai_client.settings.ollama_enabled:
            compact_context = {
                "project_id": project_id,
                "title": title,
                "description": description[:600],
                "business_context": (business_context or "")[:300],
                "functional_requirements": functional_requirements[:8],
                "integrations": integrations[:6],
                "clarifications": [f"{k}: {v}" for k, v in answers.items() if v and len(str(v).strip()) > 1][:4],
            }
            raw = self.ai_client.generate(
                "actor-semantic-generation",
                compact_context,
                response_schema=SemanticActorExtraction.model_json_schema(),
                num_predict=450,
                num_ctx=2048,
                minimum_timeout_seconds=30,
            )
            if raw and isinstance(raw, dict):
                raw_actors = raw.get("actors", [])
                if isinstance(raw_actors, list):
                    for item in raw_actors:
                        if isinstance(item, str) and item.strip():
                            candidates.append(SemanticActorItem(name=item.strip()))
                        elif isinstance(item, dict):
                            try:
                                candidates.append(SemanticActorItem.model_validate(item))
                            except Exception:
                                pass

        action_prefixes = frozenset(
            """
            coordinate manage create place deliver perform provide ensure track
            update process review submit handle execute monitor analyze resolve
            operate authenticate configure generate stream build order pay
            receive send view access browse search ingest capture record register
            schedule cancel refund maintain verify integrate connect extract
            support allow enable help assist dispatch fulfill ship
            """.split()
        )
        data_concept_words = frozenset(
            """
            data telemetry reading sensor-data metric metrics information
            log logs record records invoice invoices bill bills payment-record
            payload file files document documents shipment-item
            """.split()
        )
        tech_words = frozenset(
            """
            postgresql mysql sqlite kafka redis rabbitmq docker kubernetes
            aws gcp azure graphql rest api apis grpc http json xml html css
            """.split()
        )
        machine_role_heads = frozenset(
            """
            gateway gateways sensor sensors controller controllers kiosk kiosks
            terminal terminals device devices robot robots instrument instruments
            """.split()
        )

        validated_actors: list[Actor] = []
        seen_names: set[str] = set()

        for candidate in candidates:
            raw_name = candidate.name.strip()
            # 1. Reject sentences, clauses, or excessively long titles
            if len(raw_name.split()) > 4 or any(p in raw_name for p in {".", ";", "!", "?", ","}):
                continue
            lower_raw = raw_name.lower()
            if any(m in lower_raw.split() for m in {"use", "uses", "from", "that", "which", "who", "allows", "provides", "enables"}):
                continue

            # 2. Name normalization
            normalized = _normalize_role(raw_name)
            if not normalized:
                continue
            words = normalized.split()
            if len(words) > 4:
                continue

            first_w = words[0].lower()
            last_w = words[-1].lower()

            # 3. Action / verb rejection
            if first_w in action_prefixes or first_w.rstrip("s") in action_prefixes or first_w.endswith("ing"):
                continue

            # 4. Data concept rejection
            if last_w not in machine_role_heads and (first_w in data_concept_words or last_w in data_concept_words):
                continue
            if "data from" in lower_raw or "sensor data" in lower_raw:
                continue

            # 5. Generic noun rejection
            if normalized.casefold() in GENERIC_ACTOR_NAMES or normalized.casefold() in {
                "user", "users", "admin", "actor", "stakeholder", "person", "core"
            }:
                continue

            # 6. Tech name rejection
            if normalized.lower() in tech_words or normalized.lower() in {t.lower() for t in TECHNOLOGY_NAMES}:
                continue

            # 7. Full token grounding in actor_source
            if not self._tokens_fully_grounded(normalized, actor_source):
                continue

            # 8. Active participation or requirement grounding check
            if not (
                self._actor_is_active(normalized, actor_source)
                or self._actor_grounded_in_requirements(normalized, functional_requirements, actor_source)
                or self._external_party_is_integration_boundary(normalized, actor_source)
                or candidate.actor_type in {"device", "machine", "external-system", "external-partner"}
            ):
                continue

            key = normalized.casefold()
            if key in seen_names:
                continue
            seen_names.add(key)

            resp = [r.strip() for r in candidate.responsibilities if r.strip() and len(r.strip()) <= 120]
            if not resp:
                resp = [self._deterministic_actor_description(normalized, candidate.actor_type, functional_requirements, combined_source)]
            perms = [p.strip() for p in candidate.permissions if p.strip() and len(p.strip()) <= 100]

            source_ev = [
                SourceEvidence(
                    source_id=f"REQ-ACTOR-{len(validated_actors) + 1:03d}",
                    source=ev[:120],
                    status="confirmed",
                )
                for ev in candidate.source_evidence if ev.strip()
            ] or [
                SourceEvidence(
                    source_id=f"REQ-ACTOR-{len(validated_actors) + 1:03d}",
                    source="actor evidenced in requirements and brief",
                    status="confirmed",
                )
            ]

            validated_actors.append(
                Actor(
                    id=f"ACT-{len(validated_actors) + 1:03d}",
                    name=normalized,
                    description=resp[0],
                    actor_type=candidate.actor_type,
                    responsibilities=resp,
                    permissions=perms,
                    source_evidence=source_ev,
                )
            )

        # Deterministic fallback if Ollama produced 0 valid actors
        if not validated_actors:
            for name, kind in extract_actors(actor_source)[:8]:
                normalized = _normalize_role(name)
                if not normalized or normalized.casefold() in GENERIC_ACTOR_NAMES:
                    continue
                words = normalized.split()
                if len(words) > 4:
                    continue
                first_w = words[0].lower()
                last_w = words[-1].lower()
                if any(m in normalized.lower().split() for m in {"use", "uses", "from", "that", "which", "who", "allows", "provides", "enables"}):
                    continue
                if first_w in action_prefixes or first_w.rstrip("s") in action_prefixes or first_w.endswith("ing"):
                    continue
                if last_w not in machine_role_heads and (first_w in data_concept_words or last_w in data_concept_words):
                    continue
                if normalized.casefold() in seen_names:
                    continue
                if not self._tokens_fully_grounded(normalized, actor_source):
                    continue
                if not (
                    self._actor_is_active(normalized, actor_source)
                    or self._actor_grounded_in_requirements(normalized, functional_requirements, actor_source)
                    or (kind == "external-partner" and self._external_party_is_integration_boundary(normalized, actor_source))
                ):
                    continue
                seen_names.add(normalized.casefold())

                resp = [self._deterministic_actor_description(normalized, kind, functional_requirements, combined_source)]
                validated_actors.append(
                    Actor(
                        id=f"ACT-{len(validated_actors) + 1:03d}",
                        name=normalized,
                        description=resp[0],
                        actor_type=kind if kind in {"human", "organizational", "external-partner", "external-system", "device", "event-source", "machine", "unknown"} else "human",
                        responsibilities=resp,
                        permissions=[],
                        source_evidence=[
                            SourceEvidence(
                                source_id=f"REQ-ACTOR-{len(validated_actors) + 1:03d}",
                                source="actor evidenced in requirements",
                                status="confirmed",
                            )
                        ],
                    )
                )
                if len(validated_actors) >= 4:
                    break

        return self._dedupe_actors(validated_actors)

    def _fallback_or_deterministic(
        self,
        title: str,
        description: str,
        business_context: str | None,
        answers: dict[str, str],
        constraints: list[str],
        prior_warnings: list[str] | None = None,
    ) -> RequirementModel:
        """Deterministic domain extraction, else the honest empty fallback.

        When Ollama is unavailable (or its output is unusable), domain terms
        are extracted directly from the brief with generic language rules, so
        ANY business domain propagates downstream. Extraction is marked as
        medium-confidence inference; inputs with no extractable structure
        keep the conservative fallback with explicit open questions.
        """
        deterministic = self._analyze_deterministic(
            title, description, business_context, answers, constraints,
            prior_warnings=prior_warnings,
        )
        if deterministic is not None:
            return deterministic
        fallback = self._conservative_fallback(title, description, constraints)
        if prior_warnings:
            fallback.analysis_warnings.extend(prior_warnings)
        return fallback

    def _analyze_deterministic(
        self,
        title: str,
        description: str,
        business_context: str | None,
        answers: dict[str, str],
        constraints: list[str],
        prior_warnings: list[str] | None = None,
    ) -> RequirementModel | None:
        source_text = " ".join(
            part
            for part in [
                title, description, business_context or "",
                *constraints, *answers.values(),
            ]
            if part
        )
        # Answers and business narrative are not sources of product actors or
        # domain records.  Business context still participates in domain,
        # scale, quality, integration, and constraint analysis below; only
        # context clauses that explicitly direct the software enter the
        # product-scope extractor.
        # Including them here made `OAuth credentials` and `millions` appear
        # as domain entities.  Domain concepts must originate in the brief.
        # Parts are joined as sentences so role/entity patterns cannot span a
        # text boundary and fuse phantom phrases (e.g. title "Drone Fleet
        # Maintenance" + "Operators schedule..." becoming "Fleet Maintenance
        # Operator").
        context_requirements = self._business_context_requirement_text(business_context)
        product_source = ". ".join(
            part for part in [title, description, context_requirements] if part
        )
        actor_source = ". ".join([
            product_source,
            *[
                value for key, value in answers.items()
                if self._answer_is_known(value)
                and clarification_category(key) == "domain"
            ],
        ])
        domain_source = product_source
        actor_terms = extract_actors(actor_source)
        # Round one uses a wide token pool (top 16) so capability grounding
        # never depends on the final top-N entity cut.
        pool_ids = extract_entities(domain_source, limit=16)
        entity_tokens = {
            token
            for identifier in pool_ids
            for token in tokenize(identifier)
        }
        actor_tokens = {
            token
            for name, _ in actor_terms
            for token in tokenize(name)
        }
        capabilities = extract_capabilities(
            description, context_requirements, entity_tokens, actor_tokens
        )
        # Second pass: boost entities grounded as actor vocabulary or
        # capability objects so partner/party concepts survive the final cut.
        actor_boosts = {
            token: 1.5
            for name, _ in actor_terms
            for token in tokenize(name)
            if len(token) > 3
        }
        capability_boosts = {
            token: 1.0 for token in capability_object_tokens(capabilities)
        }
        entity_ids = extract_entities(
            domain_source + " " + " ".join(capabilities),
            limit=14,
            extra_weights={**capability_boosts, **actor_boosts},
        )
        entity_tokens = {
            token
            for identifier in entity_ids
            for token in tokenize(identifier)
        }
        grounded_actors = [
            (name, kind)
            for name, kind in actor_terms
            if (
                self._actor_is_active(name, actor_source)
                or self._actor_grounded_in_requirements(
                    name, capabilities, actor_source
                )
                or (
                    kind == "external-partner"
                    and self._external_party_is_integration_boundary(name, actor_source)
                )
            )
        ]
        # A terse domain brief may name workflows and entities without naming
        # their human owners.  Preserve its domain model and record the actor
        # boundary as needing clarification instead of collapsing the entire
        # project to the generic fallback.
        if len(entity_ids) < 2 or len(capabilities) < 1:
            return None

        warnings: list[str] = list(prior_warnings or [])
        family, confidence, evidence = classify_domain(title, source_text)
        if family:
            domain = f"{family} Platform"
            warnings.append(
                f"Domain inferred as '{domain}' from brief vocabulary "
                f"({', '.join(evidence[:6])}); confirm during review."
            )
        else:
            title_domain = re.sub(
                r"\b(?:platform|system|application|software|global|large-scale|enterprise)\b",
                " ",
                title,
                flags=re.I,
            )
            title_domain = " ".join(title_domain.split()).strip(" -")
            domain = (
                f"{title_domain} Platform"
                if len(tokenize(title_domain)) >= 2
                else f"{to_display_name(entity_ids[0])} Management Platform"
            )
            confidence = 0.35
            warnings.append(
                "No dominant domain vocabulary detected; domain label derived "
                f"from the most frequent business concept ('{entity_ids[0]}'). "
                "Confirm during review."
            )

        deterministic_integrations = extract_integrations(description, business_context, " ".join(constraints))
        actors = self._extract_semantic_actors(
            title=title,
            description=description,
            business_context=business_context,
            functional_requirements=capabilities,
            integrations=deterministic_integrations,
            answers=answers,
            project_id=None,
            call_ai=False,
        )
        # Do not promote a passive mention into an actor merely to fill the
        # section.  A missing operator becomes a clarification question; an
        # invented operator contaminates use cases, permissions, and Conway
        # ownership downstream.
        entities = [
            DomainEntityHint(
                name=to_display_name(identifier),
                description=f"{to_display_name(identifier)} identified from the project brief.",
            )
            for identifier in entity_ids[:14]
        ]
        workflows = self._build_workflow_hints(
            [],
            [item for item in capabilities[:10] if len(item.split()) <= 14] or capabilities[:10],
            actors,
            entities,
            product_source,
        )
        if len(workflows) < 1:
            return None

        functional = self._dedupe(capabilities[:10])
        non_functional = self._merge_explicit_items(
            [],
            self._extract_explicit_quality_requirements(description, business_context),
        )
        non_functional = self._ensure_non_functional_requirements(
            non_functional, actors, entities, workflows
        )

        user_constraints, merges = normalize_constraint_statements(
            [*constraints, *self._constraints_from_answers(answers)]
        )
        if merges:
            warnings.append(
                f"Merged {merges} constraint fragment(s) into complete statements."
            )
        explicit_constraints = [
            *user_constraints,
            *self._extract_explicit_constraints(description, business_context),
        ]
        if (cloud := answers.get("preferred_cloud")) and self._answer_is_known(cloud):
            explicit_constraints.append(f"User-specified hosting preference: {cloud}.")
        if (team_raw := answers.get("team_size")) and self._answer_is_known(team_raw):
            team_number = self._parse_team_size(team_raw)
            if team_number > 0:
                explicit_constraints.append(f"User-specified team size: {team_number} engineers.")
        explicit_constraints = self._dedupe_constraints(explicit_constraints)

        integrations = self._dedupe(
            extract_integrations(
                description, business_context, " ".join(constraints)
            )
            + self._extract_integration_requirements(functional)
        )
        integrations = self._drop_covered_integrations(integrations)
        # The deterministic path uses additive coverage only: extracted items
        # are already clean, so uncovered source clauses are appended when
        # grounded and never rewrite existing requirements.
        functional = self._append_uncovered_capabilities(
            functional, description, context_requirements, entity_tokens, actor_tokens
        )
        functional = self._decompose_functional_requirements(functional)
        non_functional = self._decompose_non_functional_requirements(non_functional)
        functional, non_functional, explicit_constraints = self._reclassify_requirements(
            functional, non_functional, explicit_constraints
        )
        functional = self._split_multi_actor_requirements(functional, actors)
        workflows = self._build_workflow_hints(
            [], functional, actors, entities, product_source
        )

        summary_source = description.strip().split(".")[0].strip()
        summary = summary_source[:500] if summary_source else f"{title}: {capabilities[0]}"
        open_questions = self._deterministic_open_questions(
            source_text, answers, actors, integrations
        )
        return RequirementModel(
            summary=summary,
            domain=domain,
            scale_profile=self._infer_scale_profile(source_text, answers, unknown_default=True),
            functional_requirements=functional,
            non_functional_requirements=non_functional,
            actors=actors,
            constraints=self._dedupe_constraints(explicit_constraints),
            assumptions=[],
            domain_entities=entities,
            domain_workflows=workflows,
            integrations=self._dedupe(integrations),
            data_characteristics=self._dedupe_characteristics(
                self._extract_explicit_data_characteristics(description, business_context)
            ),
            open_questions=open_questions,
            analysis_source="deterministic-extraction",
            analysis_warnings=self._dedupe([
                *warnings,
                "Role responsibilities, entity attributes, and workflow boundaries "
                "were inferred from the brief and remain reviewable; they are not "
                f"user-confirmed assumptions (extraction confidence {confidence:.0%}).",
            ]),
        )

    def _drop_covered_integrations(self, integrations: list[str]) -> list[str]:
        """Drop bare integration phrases already covered by a structured entry."""
        from app.services.domain_inference import singularize

        def _key_tokens(text: str) -> set[str]:
            return {
                singularize(token)
                for token in re.findall(r"[a-z][a-z0-9_-]+", text.lower())
                if len(token) > 3
            } - {"with", "and", "ownership", "external", "sync", "unspecified"}

        structured = [item for item in integrations if "Ownership:" in item]
        covered: set[str] = set()
        for item in structured:
            covered |= _key_tokens(item)
        result = list(structured)
        for item in integrations:
            if "Ownership:" in item:
                continue
            tokens = _key_tokens(item)
            if tokens and not tokens <= covered:
                result.append(item)
        return self._dedupe(result)

    def _append_uncovered_capabilities(
        self,
        functional: list[str],
        description: str,
        business_context: str | None,
        entity_tokens: set[str],
        actor_tokens: set[str],
    ) -> list[str]:
        """Append grounded source clauses missing from the extracted set.

        Unlike the Ollama-path preservation pass, this never replaces an
        existing requirement: deterministic items are already normalized.
        """
        from app.services.domain_inference import (
            _CAPABILITY_NOUNS,
            _CAPABILITY_VERBS,
            _looks_like_capability,
            _normalize_capability,
            _split_enumeration,
        )

        represented = " ".join(functional)
        extended = list(functional)
        for sentence in split_sentences(
            " ".join(part for part in (description, business_context or "") if part)
        ):
            candidates = _split_enumeration(sentence)
            if len(candidates) <= 1:
                candidates = [sentence]
            for candidate in candidates:
                cleaned = _normalize_capability(candidate)
                if not cleaned or cleaned in extended:
                    continue
                if self._clause_coverage(cleaned, represented) >= 0.85:
                    continue
                if _looks_like_capability(cleaned, entity_tokens, actor_tokens):
                    extended.append(cleaned)
                    represented += f" {cleaned}"
        return self._dedupe(extended)

    def _reclassify_requirements(
        self,
        functional: list[str],
        non_functional: list[str],
        constraints: list[str],
    ) -> tuple[list[str], list[str], list[str]]:
        """Keep behavior, quality, and hard limits mutually intelligible.

        Extraction models often phrase a bundle of quality attributes as
        ``Support security, residency, auditability...``.  The leading verb
        used to make that bundle look functional.  Classification here is
        semantic: domain actions stay functional, measurable qualities become
        NFRs, and explicit obligations remain constraints.
        """
        domain_action_markers = (
            "approve", "assess", "book", "calculate", "capture", "create",
            "dispatch", "fulfill", "issue", "manage", "notify", "pay",
            "reconcile", "register", "report", "review", "schedule",
            "settle", "submit", "track", "transfer", "update", "view",
        )

        def _quality_hits(value: str) -> int:
            lower = value.casefold()
            hits = sum(marker in lower for marker in QUALITY_REQUIREMENT_MARKERS)
            if re.search(r"\b\d+(?:\.\d+)?\s*(?:%|ms|milliseconds?|seconds?)\b", lower):
                hits += 1
            if re.search(
                r"\b\d[\d,.]*\s*(?:k|m|million|thousand)?\+?\s*"
                r"(?:concurrent\s+)?(?:users?|requests?|transactions?|events?|messages?)"
                r"(?:\s*(?:/|per)\s*(?:second|minute|hour|day))?\b",
                lower,
            ):
                hits += 1
            return hits

        def _solution_constraint(value: str) -> bool:
            lower = f" {value.casefold()} "
            hard = any(marker in lower for marker in (
                " must ", " must not ", " cannot ", " never ", " only ",
                " required ", " require ", " requires ", " shall ",
                " user-specified ", " confirmed clarification ",
            ))
            return hard and any(
                marker in lower for marker in SOLUTION_CONSTRAINT_MARKERS
            )

        def _domain_actions(value: str) -> int:
            lower = value.casefold()
            return sum(
                re.search(rf"\b{re.escape(marker)}\w*\b", lower) is not None
                for marker in domain_action_markers
            )

        kept_functional: list[str] = []
        moved_nfr: list[str] = []
        moved_constraints: list[str] = []

        # Re-evaluate model categories instead of trusting the output label.
        # A modal verb ("must") does not make a quality target a constraint.
        # Conversely, mandated technologies, locality, consistency semantics,
        # and regulatory boundaries remain constraints.
        for item in constraints:
            if _quality_hits(item) and not _solution_constraint(item):
                moved_nfr.append(item)
            else:
                moved_constraints.append(item)
        for item in non_functional:
            if _solution_constraint(item):
                moved_constraints.append(item)
            elif _quality_hits(item):
                moved_nfr.append(item)
            elif _domain_actions(item):
                kept_functional.append(item)
            else:
                moved_nfr.append(item)

        for item in functional:
            quality_hits = _quality_hits(item)
            domain_actions = _domain_actions(item)
            numeric_quality = bool(re.search(
                r"\b\d+(?:\.\d+)?\s*(?:%|ms|milliseconds?|seconds?)\b",
                item.casefold(),
            ))
            if quality_hits and _solution_constraint(item):
                moved_constraints.append(item)
            elif quality_hits and (
                numeric_quality
                or quality_hits >= 2
                or domain_actions == 0
                or bool(re.match(
                    r"^(?:(?:the\s+)?(?:platform|system|application|service)\s+"
                    r"(?:must|should|shall|will|needs?\s+to)\s+)?"
                    r"(?:support|supporting|provide|providing|maintain|maintaining)\b",
                    item,
                    re.I,
                ))
            ):
                moved_nfr.append(item)
            else:
                kept_functional.append(item)

        constraint_keys = {self._requirement_key(item) for item in moved_constraints}
        # A capability statement duplicated across categories stays functional:
        # drop the NFR copy, never the validated functional requirement.
        functional_keys = {self._requirement_key(item) for item in kept_functional}
        moved_nfr = [
            item for item in moved_nfr
            if self._requirement_key(item) not in constraint_keys
            and self._requirement_key(item) not in functional_keys
        ]
        nfr_keys = {self._requirement_key(item) for item in moved_nfr}
        kept_functional = [
            item for item in kept_functional
            if self._requirement_key(item) not in constraint_keys
            and self._requirement_key(item) not in nfr_keys
        ]
        normalized_constraints = self._dedupe_constraints(moved_constraints)
        return (
            self._dedupe_semantic_requirements(kept_functional),
            self._dedupe_semantic_requirements(moved_nfr),
            normalized_constraints,
        )

    def _decompose_functional_requirements(self, values: list[str]) -> list[str]:
        """Turn bundled scope prose into independently testable behavior.

        The implementation uses sentence grammar (actor + modal + actions, or
        action + object list), not domain vocabulary. Integration statements
        are excluded because their typed contracts are generated separately.
        """
        action_words = {
            "accept", "add", "approve", "assign", "book", "browse", "cancel",
            "capture", "check", "configure", "coordinate", "create", "delete",
            "dispatch", "export", "fulfill", "generate", "import", "issue",
            "make", "manage", "monitor", "notify", "plan", "process", "provide",
            "receive", "record", "register", "report", "request", "review",
            "schedule", "search", "send", "settle", "submit", "support", "track",
            "transfer", "update", "upload", "use", "verify", "view",
        }

        def normalized(value: str) -> str:
            cleaned = " ".join(value.split()).strip(" .")
            return cleaned[:1].upper() + cleaned[1:] + "." if cleaned else ""

        def split_list(value: str, *, action_list: bool = False) -> list[str]:
            conjunction = (
                r"\s+and\s+(?=(?:" + "|".join(sorted(action_words)) + r")\b)"
                if action_list else r"\s+and\s+"
            )
            parts = [
                re.sub(r"^(?:and|or)\s+", "", part.strip(), flags=re.I)
                for part in re.split(r",\s*|" + conjunction, value, flags=re.I)
                if part.strip()
            ]
            return parts if len(parts) >= 2 else []

        result: list[str] = []
        for original in values:
            value = " ".join(original.split()).strip(" .")
            if not value:
                continue
            if re.search(r"\bintegrat(?:e|es|ed|ing|ion)\s+with\b", value, re.I):
                continue

            # Split mixed behavior/quality clauses before classification, for
            # example "process requests while maintaining 99.99% uptime".
            while_parts = re.split(r"\s+while\s+", value, maxsplit=1, flags=re.I)
            if len(while_parts) == 2:
                value = while_parts[0]
                trailing_words = while_parts[1].split()
                if trailing_words:
                    trailing_words[0] = self._base_verb(trailing_words[0])
                result.append(normalized(f"The system must {' '.join(trailing_words)}"))

            modal = re.match(
                r"^(?P<subject>.{1,80}?)\s+(?:can|may|must|should|will|shall|"
                r"should\s+be\s+able\s+to|must\s+be\s+able\s+to)\s+(?P<body>.+)$",
                value,
                flags=re.I,
            )
            if modal:
                subject = modal.group("subject").strip()
                body = re.sub(r"^be\s+able\s+to\s+", "", modal.group("body"), flags=re.I)
                parts = split_list(body, action_list=True)
                if len(parts) >= 2 and sum(
                    bool(tokenize(part)) and self._base_verb(tokenize(part)[0]) in action_words
                    for part in parts
                ) >= 2:
                    for part in parts:
                        words = part.split()
                        if words:
                            words[0] = self._base_verb(words[0])
                            result.append(normalized(f"{subject} {' '.join(words)}"))
                    continue

            # A verb followed by a real comma list is a scope bundle. Repeat
            # the verb so each generated requirement has one behavior/object.
            verb_match = re.search(
                r"\b(manage|manages|support|supports|coordinate|coordinates|"
                r"track|tracks|process|processes|provide|provides|maintain|maintains)\s+(.+)$",
                value,
                flags=re.I,
            )
            if verb_match:
                parts = split_list(verb_match.group(2))
                if len(parts) >= 3:
                    verb = self._base_verb(verb_match.group(1))
                    prefix = value[:verb_match.start()].strip()
                    # Product framing is not a business actor. A short real
                    # subject ("Customers manage ...") is retained.
                    subject = ""
                    if (
                        prefix
                        and not re.search(r"\b(?:platform|system|application|software|that)\b", prefix, re.I)
                        and len(tokenize(prefix)) <= 4
                    ):
                        subject = prefix
                    for part in parts:
                        candidate = f"{subject} {verb} {part}".strip()
                        if verb == "coordinate" and not re.search(
                            r"\b(?:operation|workflow|schedule|activity|process|handoff|response)\w*\b",
                            part,
                            re.I,
                        ):
                            continue
                        if re.search(r"\bexternal\b.{0,30}\bsystems?\b", candidate, re.I):
                            continue
                        result.append(normalized(candidate))
                    continue
            result.append(normalized(value))
        return self._dedupe_semantic_requirements(result)[:20]

    def _dedupe_semantic_requirements(self, values: list[str]) -> list[str]:
        """Collapse paraphrased duplicates while retaining distinct targets."""
        result: list[str] = []
        signatures: list[set[str]] = []
        for value in self._dedupe(values):
            signature = self._constraint_signature(value)
            duplicate = False
            for prior in signatures:
                if not signature or not prior:
                    continue
                shared = len(signature & prior)
                containment = shared / min(len(signature), len(prior))
                union = shared / len(signature | prior)
                if signature == prior or (
                    min(len(signature), len(prior)) >= 4
                    and containment >= 0.9
                    and union >= 0.72
                ):
                    duplicate = True
                    break
            if not duplicate:
                result.append(value)
                signatures.append(signature)
        return result

    def _decompose_non_functional_requirements(self, values: list[str]) -> list[str]:
        """Split independent quality clauses without fragmenting shared targets."""
        result: list[str] = []
        for value in values:
            cleaned = " ".join(value.split()).strip(" .")
            if not cleaned:
                continue
            subject_match = re.match(
                r"^((?:the\s+)?(?:platform|system|application|service))\s+"
                r"(must|should|shall|will|needs?\s+to)\s+",
                cleaned,
                flags=re.I,
            )
            prefix = (
                f"{subject_match.group(1)} {subject_match.group(2)} "
                if subject_match else "The system must "
            )
            parts = re.split(r"\s+while\s+", cleaned, flags=re.I)
            for index, part in enumerate(parts):
                part = part.strip()
                if index > 0:
                    first = part.split()[0] if part.split() else ""
                    part = prefix + self._base_verb(first) + " " + " ".join(part.split()[1:])
                lower_part = part.casefold()
                has_quality = any(marker in lower_part for marker in QUALITY_REQUIREMENT_MARKERS) or bool(
                    re.search(r"\b\d+(?:\.\d+)?\s*(?:%|ms|milliseconds?|seconds?)\b", lower_part)
                )
                if not has_quality:
                    continue
                # Two explicit quality outcomes sharing one modal become two
                # independently testable NFRs.
                shared = re.match(
                    r"^(?P<prefix>.+?\b(?:requires?|must\s+provide|must\s+maintain|must\s+support))\s+"
                    r"(?P<left>.+?)\s+and\s+(?P<right>.+)$",
                    part,
                    flags=re.I,
                )
                if shared and any(
                    marker in shared.group("right").casefold()
                    for marker in QUALITY_REQUIREMENT_MARKERS
                ):
                    result.extend([
                        shared.group("prefix") + " " + shared.group("left").rstrip(".") + ".",
                        shared.group("prefix") + " " + shared.group("right").rstrip(".") + ".",
                    ])
                else:
                    result.append(part.rstrip(".") + ".")
        return self._dedupe_quality_requirements(
            self._dedupe_semantic_requirements(result)
        )

    def _dedupe_quality_requirements(self, values: list[str]) -> list[str]:
        """Collapse the same quality target without merging distinct SLOs."""
        topic_patterns = {
            "real-time": r"\b(?:near[- ]?)?real[- ]?time\b|\brealtime\b",
            "availability": r"\b(?:availability|available|uptime)\b",
            "reliability": r"\b(?:reliab\w*|resilien\w*|durab\w*)\b",
            "security": r"\b(?:security|privacy|encrypt\w*|confidential\w*|integrity)\b",
            "recovery": r"\b(?:recovery|backup|failover)\b",
            "performance": r"\b(?:performance|latency|response time|throughput)\b",
            "scale": r"\b(?:scalab\w*|capacity|high volumes?)\b",
            "consistency": r"\b(?:consisten\w*|idempotent)\b",
            "audit": r"\b(?:audit\w*|traceab\w*|provenance)\b",
            "retention": r"\b(?:retention|retain\w*)\b",
            "observability": r"\bobservab\w*\b",
            "usability": r"\b(?:usability|accessibility)\b",
        }
        quality_words = {
            "near", "real", "time", "realtime", "availability", "available",
            "uptime", "reliable", "reliability", "resilient", "resilience",
            "durable", "durability", "security", "secure", "privacy",
            "encrypted", "encryption", "confidentiality", "integrity",
            "recovery", "backup", "failover", "performance", "latency",
            "response", "throughput", "scalable", "scalability", "capacity",
            "high", "volume", "volumes", "consistent", "consistency",
            "idempotent", "audit", "auditable", "traceability", "provenance",
            "retention", "retain", "retained", "observability", "usability",
            "accessibility", "provide", "support", "maintain", "update",
            "updates", "system", "platform", "application", "service",
        }
        result: list[str] = []
        prior_signals: list[tuple[set[str], set[str]]] = []
        for value in values:
            lower = value.casefold()
            topics = {
                topic for topic, pattern in topic_patterns.items()
                if re.search(pattern, lower)
            }
            content = self._constraint_signature(value) - quality_words
            duplicate = False
            for prior_topics, prior_content in prior_signals:
                if not topics or topics != prior_topics:
                    continue
                shared = len(content & prior_content)
                containment = shared / max(min(len(content), len(prior_content)), 1)
                if not content or not prior_content or containment >= 0.75:
                    duplicate = True
                    break
            if not duplicate:
                result.append(value)
                prior_signals.append((topics, content))
        return result

    def _split_multi_actor_requirements(
        self, functional: list[str], actors: list[Actor]
    ) -> list[str]:
        """Split a sentence containing several independent actor actions."""
        actor_token_sets = [
            {self._normalize_token(token) for token in tokenize(actor.name) if len(token) > 2}
            for actor in actors
        ]
        actor_patterns = []
        for actor in actors:
            words = tokenize(actor.name)
            if not words:
                continue
            actor_patterns.append(
                r"\s+".join(re.escape(word) for word in words[:-1])
                + (r"\s+" if len(words) > 1 else "")
                + re.escape(words[-1])
                + r"(?:s|es)?"
            )
        separator = r",\s*(?:and\s+)?"
        if actor_patterns:
            separator += r"|\s+and\s+(?=(?:the\s+)?(?:" + "|".join(actor_patterns) + r")\b)"
        result: list[str] = []
        for requirement in functional:
            clauses = [
                re.sub(r"^(?:and|while)\s+", "", item.strip(), flags=re.I)
                for item in re.split(separator, requirement.rstrip("."), flags=re.I)
                if item.strip()
            ]
            actor_clauses = sum(
                any(
                    tokens and tokens <= {
                        self._normalize_token(token) for token in tokenize(clause)
                    }
                    for tokens in actor_token_sets
                )
                for clause in clauses
            )
            if actor_clauses >= 2:
                result.extend(
                    clause[:1].upper() + clause[1:] + "."
                    for clause in clauses
                    if clause
                )
            else:
                result.append(requirement)
        return self._dedupe(result)

    def _deterministic_actor_description(
        self, name: str, kind: str, capabilities: list[str], source_text: str
    ) -> str:
        name_tokens = {token for token in tokenize(name) if len(token) > 2}
        for capability in capabilities:
            if self._clause_coverage(name, capability) > 0:
                return next((
                    re.sub(r"^(?:and|while)\s+", "", part.strip(), flags=re.I).rstrip(".") + "."
                    for part in re.split(r";\s*|,\s*", capability)
                    if name_tokens <= {self._normalize_token(token) for token in tokenize(part)}
                ), capability)
        for sentence in split_sentences(source_text):
            sentence_tokens = set(tokenize(sentence))
            if name_tokens & sentence_tokens and len(sentence.split()) <= 28:
                actor_clause = next((
                    re.sub(r"^(?:and|while)\s+", "", part.strip(), flags=re.I)
                    for part in re.split(r";\s*|,\s*", sentence)
                    if name_tokens <= {self._normalize_token(token) for token in tokenize(part)}
                ), sentence)
                return " ".join(actor_clause.split())
        if kind == "organizational":
            return f"External business party participating in {name} responsibilities; confirm scope during review."
        if kind == "machine":
            return f"Machine participant exchanging operational data; confirm protocols during review."
        return "Responsibilities require clarification."

    def _deterministic_open_questions(
        self,
        source_text: str,
        answers: dict[str, str],
        actors: list[Actor],
        integrations: list[str],
    ) -> list[str]:
        questions = [
            "Which actors perform each workflow and what permissions do they need?",
        ]
        lower = source_text.casefold()

        def _answered(key: str) -> bool:
            return self._answer_is_known(str(answers.get(key, "") or "")) and bool(
                str(answers.get(key, "") or "").strip()
            )

        if not re.search(r"\d[\d,]*\s*(million|thousand|k)?\s*\+?\s*(users|transactions|requests)", lower) and not _answered("scale"):
            questions.append(
                "What workload volume, concurrency, and growth should the architecture support?"
            )
        if not integrations and not _answered("legacy_systems"):
            questions.append("Which external systems must this software exchange data with?")
        if ("availability" not in lower and "sla" not in lower and "uptime" not in lower) and not _answered("sla") and not _answered("failover"):
            questions.append("What availability, recovery, and downtime tolerance apply?")
        if ("audit" not in lower and "compliance" not in lower and "regulation" not in lower) and not _answered("retention"):
            questions.append("What audit, retention, and regulatory obligations apply?")
        if not _answered("auth"):
            questions.append("What authentication model is required for end users and operators?")
        if not _answered("preferred_cloud") and "cloud" not in lower and "host" not in lower:
            questions.append("What hosting or cloud preference constrains deployment?")
        if not _answered("team_size"):
            questions.append("What team size and operational capacity are available?")
        return questions[:8]

    def apply_clarifications(
        self,
        requirements: RequirementModel,
        answers: dict[str, str],
        questions: dict[str, str] | None = None,
    ) -> RequirementModel:
        updates = requirements.model_copy(deep=True)
        questions = questions or {}
        # Remove derived wrapper strings from older workspaces before
        # rebuilding typed clarification signals. They produced a phantom
        # integration literally named "User-specified external/legacy
        # integration" and duplicated format answers as constraints.
        updates.integrations = [
            item for item in updates.integrations
            if not item.casefold().startswith("user-specified external/legacy integration:")
        ]
        updates.constraints = [
            item for item in updates.constraints
            if not item.casefold().startswith("user-specified integration data formats/protocols:")
        ]

        for key, raw_value in answers.items():
            value = " ".join(raw_value.split()).strip()
            if not value:
                continue

            lower_value = value.casefold()
            is_unknown = not self._answer_is_known(value)
            if key == "preferred_cloud" and not is_unknown:
                updates.constraints.append(f"User-specified hosting preference: {value}.")
            elif key == "auth" and not is_unknown:
                updates.functional_requirements.append(
                    f"Use {value} for user authentication."
                )
            elif key == "sla" and not is_unknown:
                updates.non_functional_requirements.append(
                    f"Meet the user-selected availability expectation: {value}."
                )
            elif key == "retention" and not is_unknown:
                updates.non_functional_requirements.append(
                    f"Apply the user-selected data retention posture: {value}."
                )
            elif key == "scale" and not is_unknown:
                inferred_scale = self._scale_profile_from_answer(value)
                if inferred_scale:
                    updates.scale_profile = inferred_scale
                else:
                    updates.constraints.append(f"User-described peak workload: {value}.")
            elif key == "payments" and not is_unknown:
                if lower_value == "in scope":
                    updates.functional_requirements.append(
                        "User-selected payment scope: payment transaction handling is in scope."
                    )
                elif lower_value == "external system":
                    updates.integrations.append(
                        "Payment Systems: Purpose not specified in the brief. Ownership: external. Sync: unspecified."
                    )
                elif lower_value == "not in scope":
                    updates.constraints.append(
                        "User-selected payment scope: payment transaction handling is not in scope."
                    )
            elif key == "team_size" and not is_unknown:
                team_number = self._parse_team_size(value)
                if team_number > 0:
                    updates.constraints.append(
                        f"User-specified team size: {team_number} engineers."
                    )
            elif key == "legacy_systems" and not is_unknown:
                # hydrate_project_signals owns canonical integration parsing;
                # adding a prose wrapper here creates a second fake boundary.
                pass
            elif key == "data_formats" and not is_unknown:
                # Protocols/formats/modes are typed integration properties,
                # not constraints. Hydration applies them to the named
                # boundary and also records the technical characteristic.
                pass
            elif key == "failover" and not is_unknown:
                updates.non_functional_requirements.append(
                    f"Apply the user-selected failover/recovery posture: {value.rstrip('.')}."
                )
            elif key == "geographic_regions" and not is_unknown:
                updates.constraints.append(
                    f"User-specified deployment geography: {value.rstrip('.')}."
                )
            elif key == "constraints" and not is_unknown:
                for item in re.split(r"[;\n]+", value):
                    cleaned = item.strip().strip(",")
                    if cleaned:
                        updates.constraints.append(cleaned)
            elif key.startswith("domain_open_") and not is_unknown:
                question = questions.get(key, "Architecture-critical detail")
                category = clarification_category(key, question)
                if category == "availability":
                    updates.non_functional_requirements.append(value.rstrip(".") + ".")
                elif category in {"integrations", "technical-data"}:
                    # Parsed into IntegrationDetail/TechnicalCharacteristic by
                    # the canonical signal hydrator below.
                    pass
                else:
                    updates.constraints.append(
                        f"Confirmed clarification - {question.rstrip('?')}: {value.rstrip('.')}."
                    )

        updates.functional_requirements = self._dedupe(updates.functional_requirements)
        updates.non_functional_requirements = self._dedupe(
            updates.non_functional_requirements
        )
        updates.constraints = self._dedupe_constraints(updates.constraints)
        updates.integrations = self._dedupe(updates.integrations)
        return hydrate_project_signals(
            RequirementModel.model_validate(updates.model_dump()), answers, questions
        )

    def _analyze_known(
        self,
        title: str,
        description: str,
        combined_text: str,
        business_context: str | None,
        answers: dict[str, str],
        constraints: list[str],
        blueprint: DomainBlueprint,
    ) -> RequirementModel:
        # A blueprint is a fast domain classifier, never a source of product
        # requirements. Earlier versions copied every blueprint feature,
        # actor, entity, and compliance item into the project, so mentioning
        # an online pharmacy could invent checkout, payments, inventory, and
        # admin workflows. Reuse the grounded deterministic extractor and
        # only apply the confidently matched domain label.
        grounded = self._analyze_deterministic(
            title,
            description,
            business_context,
            answers,
            constraints,
        )
        if grounded is None:
            grounded = self._conservative_fallback(title, description, constraints)

        lower_text = combined_text.casefold()
        entity_aliases = {
            "stations": ("station",),
            "chargers": ("charger",),
            "bookings": ("booking", "reservation", "slot"),
            "charging_sessions": ("charging session",),
            "products": ("product", "medicine", "drug", "catalog"),
            "inventory": ("inventory", "stock"),
            "prescriptions": ("prescription",),
            "orders": ("order",),
            "shipments": ("shipment", "delivery", "courier", "fulfillment"),
        }
        existing_entity_map = {
            frozenset(
                self._normalize_token(token)
                for token in re.findall(r"[a-z][a-z0-9-]+", entity.name.casefold())
            ): entity
            for entity in grounded.domain_entities
        }
        grounded_blueprint_entities: list[DomainEntityHint] = []
        for entity_name in blueprint.entities:
            normalized_name = entity_name.replace("_", " ")
            name_tokens = {
                self._normalize_token(token)
                for token in re.findall(r"[a-z][a-z0-9-]+", normalized_name)
            }
            directly_grounded = self._tokens_fully_grounded(normalized_name, combined_text)
            alias_grounded = any(
                marker in lower_text for marker in entity_aliases.get(entity_name, ())
            )
            if entity_name == "payments":
                alias_grounded = (
                    payment_evidence_level(combined_text) >= 2
                    or "checkout" in lower_text
                )
            elif entity_name == "order_items":
                alias_grounded = (
                    "order" in lower_text
                    and any(marker in lower_text for marker in ("product", "medicine", "item"))
                )
            if not (directly_grounded or alias_grounded):
                continue
            entity_key = frozenset(name_tokens)
            if entity_key in existing_entity_map:
                existing_entity = existing_entity_map[entity_key]
                # Normalize only a noun already present in the brief (for
                # example Payment -> payments); no new concept is introduced.
                existing_entity.name = entity_name
                grounded_blueprint_entities.append(existing_entity)
                continue
            grounded_blueprint_entities.append(
                DomainEntityHint(
                    name=entity_name,
                    description=(
                        f"{normalized_name.title()} record supported by explicit project vocabulary."
                    ),
                    source_evidence=[
                        SourceEvidence(
                            source_id="BLUEPRINT-GROUNDED-ENTITY",
                            source="matched blueprint entity grounded by project vocabulary",
                            status="inferred",
                        )
                    ],
                )
            )
            existing_entity_map[entity_key] = grounded_blueprint_entities[-1]
        # Put the explicitly supported canonical nouns first so diagram and
        # UI display limits do not hide them behind lower-confidence tokens.
        grounded.domain_entities = [
            *grounded_blueprint_entities,
            *[
                entity
                for entity in grounded.domain_entities
                if entity not in grounded_blueprint_entities
            ],
        ]

        # A confidently matched domain may imply one primary human role even
        # when a terse brief only names that role's actions (for example,
        # "station discovery" implies a driver). Keep this single inference
        # explicit and traceable; never copy the blueprint's full actor list.
        primary_actor_name, primary_actor_description = blueprint.actors[0]
        if not any(
            actor.name.casefold() == primary_actor_name.casefold()
            for actor in grounded.actors
        ):
            grounded.actors.insert(
                0,
                Actor(
                    name=primary_actor_name,
                    description=primary_actor_description,
                    actor_type="human",
                    source_evidence=[
                        SourceEvidence(
                            source_id="BLUEPRINT-PRIMARY-ACTOR",
                            source="primary role inferred from matched domain vocabulary",
                            status="inferred",
                        )
                    ],
                ),
            )
        for workflow in grounded.domain_workflows:
            if workflow.primary_actor.casefold() in {"source", "user", "unknown"}:
                workflow.primary_actor = primary_actor_name

        grounded.domain = blueprint.domain
        grounded.analysis_source = "predefined-blueprint"
        grounded.analysis_warnings = self._dedupe(
            [
                warning
                for warning in grounded.analysis_warnings
                if not warning.startswith("Domain inferred as")
                and not warning.startswith("No dominant domain vocabulary")
            ]
            + [
                "A static blueprint classified the domain; all actors, capabilities, "
                "entities, constraints, and integrations remain grounded in the project brief."
            ]
        )
        grounded.scale_profile = self._infer_scale_profile(combined_text, answers)
        return grounded

    def _conservative_fallback(
        self, title: str, description: str, constraints: list[str]
    ) -> RequirementModel:
        return RequirementModel(
            summary=f"{title}: {description}",
            domain="Unknown domain",
            scale_profile="unknown",
            functional_requirements=[description],
            non_functional_requirements=[],
            actors=[],
            constraints=constraints,
            assumptions=[],
            open_questions=[
                "Which actors perform each workflow and what permissions do they need?",
                "What workload volume, concurrency, and growth should the architecture support?",
                "Which external systems must this software exchange data with?",
                "What availability, recovery, retention, and regulatory obligations apply?",
            ],
            analysis_source="conservative-fallback",
            analysis_warnings=[
                "Ollama was unavailable or did not return a trustworthy structured extraction."
            ],
        )

    def append_change(self, requirements: RequirementModel, change_request: str) -> RequirementModel:
        updates = requirements.model_copy(deep=True)
        normalized_change = " ".join(change_request.split()).strip()
        if normalized_change:
            updates.functional_requirements.append(normalized_change.rstrip(".") + ".")
        updates.functional_requirements = self._dedupe(updates.functional_requirements)
        return RequirementModel.model_validate(updates.model_dump())

    def _pick_blueprint(self, text: str) -> DomainBlueprint | None:
        """Score blueprint keyword evidence instead of first-substring matching.

        A single generic word (e.g. "commerce" inside "digital commerce") is
        not enough to claim a domain: matching requires either two distinct
        keyword hits with a combined score of 2+, or three distinct hits.
        Multi-word phrases count double because they are far more specific.
        """
        lower_text = text.lower()
        generic_singles = {"shop", "store", "cart", "commerce", "course"}
        best: DomainBlueprint | None = None
        best_score = 0.0
        for blueprint in BLUEPRINTS:
            score = 0.0
            hits = 0
            for keyword in blueprint.keywords:
                if " " in keyword:
                    if keyword in lower_text:
                        score += 2.0
                        hits += 1
                elif re.search(rf"\b{re.escape(keyword)}\b", lower_text):
                    score += 0.5 if keyword in generic_singles else 1.0
                    hits += 1
            if (hits >= 2 and score >= 2.0) or hits >= 3:
                if score > best_score:
                    best, best_score = blueprint, score
        return best

    def _infer_scale_profile(
        self, text: str, answers: dict[str, str], *, unknown_default: bool = False
    ) -> str:
        lower_text = text.lower()
        scale_match = re.search(
            r"(\d[\d,]*)\s*(million|m|thousand|k)?\s*\+?\s+users?", lower_text
        )
        users = 0
        if scale_match:
            base = int(scale_match.group(1).replace(",", ""))
            suffix = scale_match.group(2)
            if suffix in {"million", "m"}:
                users = base * 1_000_000
            elif suffix in {"thousand", "k"}:
                users = base * 1_000
            else:
                users = base
        users = max(users, self._parse_user_count(answers.get("scale", "")))
        if users >= 250_000:
            return "high-scale"
        if users >= 25_000:
            return "growth-scale"
        if users > 0:
            return "small-scale"
        return "unknown" if unknown_default else "small-scale"

    def _parse_user_count(self, value: str) -> int:
        match = re.search(r"(\d[\d,]*)\s*(million|m|thousand|k)?", value.lower())
        if not match:
            return 0
        count = int(match.group(1).replace(",", ""))
        if match.group(2) in {"million", "m"}:
            return count * 1_000_000
        if match.group(2) in {"thousand", "k"}:
            return count * 1_000
        return count

    def _scale_profile_from_answer(self, value: str) -> str | None:
        count = self._parse_user_count(value)
        if count >= 250_000:
            return "high-scale"
        if count >= 25_000:
            return "growth-scale"
        if count > 0:
            return "small-scale"

        lower_value = value.casefold()
        if any(marker in lower_value for marker in ("high", "large", "enterprise")):
            return "high-scale"
        if any(marker in lower_value for marker in ("growth", "medium")):
            return "growth-scale"
        if any(marker in lower_value for marker in ("pilot", "small", "startup")):
            return "small-scale"
        return None

    def _constraints_from_answers(self, answers: dict[str, str]) -> list[str]:
        stored = answers.get("constraints", "")
        # Split on semicolons and newlines; comma-joined user input is kept
        # whole downstream by normalize_constraint_statements which handles
        # conditional comma-splitting. Also fold legacy explicit keys that
        # older clients may still send as free-form constraints.
        parts: list[str] = []
        for chunk in re.split(r"[;\n]+", stored):
            item = chunk.strip().strip(",")
            if item:
                parts.append(item)
        return parts

    def _feature_overrides(self, text: str) -> list[str]:
        lower_text = text.lower()

        def _has_word(word: str) -> bool:
            return re.search(rf"\b{re.escape(word)}\b", lower_text) is not None

        # Commerce-sensitive capabilities require strong evidence: a passing
        # mention of "payment" (e.g. "external payment systems, where
        # required") must never conjure carts, checkout, or refunds.
        commerce_level = payment_evidence_level(text)
        gated_map = {
            "payment": (
                commerce_level >= 2,
                "Integrate payment authorization, settlement, and refund handling.",
            ),
            "refund": (
                "refund" in lower_text
                and (commerce_level >= 1 or "return" in lower_text or "cancel" in lower_text),
                "Support refund review flows with auditable payment status transitions.",
            ),
        }
        features: list[str] = []
        for keyword, (allowed, feature) in gated_map.items():
            if _has_word(keyword) and allowed:
                features.append(feature)
        # Domain-sensitive overrides: EV-charging vocabulary must not leak
        # into unrelated domains (e.g. "station" substring inside other
        # words, or "booking" in a travel brief pulling charger details).
        # Only emit charger/station features when the brief carries explicit
        # EV-charging evidence.
        ev_evidence = any(
            phrase in lower_text
            for phrase in ("ev charging", "charging station", "charging slot", "charger")
        ) or (_has_word("ev") and _has_word("charging"))
        keyword_map = {
            "notification": "Allow users to manage notification preferences and delivery channels.",
            "search": "Provide full-text search with business-aware filtering.",
            "analytics": "Deliver usage analytics and operational KPI dashboards.",
            "chat": "Support conversational or collaborative workflows with moderation controls.",
            "mobile": "Keep APIs optimized for future mobile clients and offline-tolerant use cases.",
        }
        ev_keyword_map = {
            "booking": "Allow users to reschedule or cancel reservations without losing operational traceability.",
            "charger": "Surface charger specifications, connector types, and live availability signals.",
            "station": "Present rich station details, operating windows, and wayfinding context.",
        }
        for keyword, feature in keyword_map.items():
            if _has_word(keyword):
                features.append(feature)
        if ev_evidence:
            for keyword, feature in ev_keyword_map.items():
                if _has_word(keyword):
                    features.append(feature)
        return features

    def _extract_explicit_constraints(
        self, description: str, business_context: str | None
    ) -> list[str]:
        result: list[str] = []
        for clause in self._source_clauses(description, business_context):
            lower = f" {clause.casefold()} "
            if "do not assume" in lower or "don't assume" in lower:
                continue
            if re.search(r"\bintegrat\w*\s+with\b", lower):
                continue
            hard_negative = any(marker in lower for marker in (
                " must not ", " never ", " cannot ", " only ", " does not ", " do not ",
            ))
            obligated_solution = any(marker in lower for marker in (
                " must use ", " shall use ", " required to use ", " must deploy ",
                " must host ", " data residency ", " in-country ",
                " strongly consistent ", " idempotent ", " prevent duplicates ",
                " regulatory compliance ",
            ))
            if hard_negative or obligated_solution:
                result.append(re.sub(r"^and\s+", "", clause, flags=re.I))
        return result

    def _extract_explicit_quality_requirements(
        self, description: str, business_context: str | None
    ) -> list[str]:
        return [
            clause
            for clause in self._source_clauses(description, business_context)
            if (
                any(marker in clause.casefold() for marker in QUALITY_REQUIREMENT_MARKERS)
                or bool(re.search(
                    r"\b\d+(?:\.\d+)?\s*(?:%|ms|milliseconds?|seconds?)\b",
                    clause.casefold(),
                ))
                or bool(re.search(
                    r"\b\d[\d,.]*\s*(?:k|m|million|thousand)?\+?\s*"
                    r"(?:concurrent\s+)?(?:users?|requests?|transactions?|events?|messages?)",
                    clause.casefold(),
                ))
            )
            and "do not assume" not in clause.lower()
            and "don't assume" not in clause.lower()
            # Short context labels ("Fleet safety reviews.") carry a quality
            # substring but state no requirement; only full clauses qualify.
            and len(tokenize(clause)) >= 4
        ]

    def _business_context_requirement_text(
        self, business_context: str | None
    ) -> str:
        """Return only context clauses that explicitly direct the product.

        Business context explains why the project exists.  A sentence such as
        "leadership coordinates teams in spreadsheets" is evidence about the
        current business, not a requirement that the new system coordinate
        leadership or reproduce spreadsheets.  Explicit product directives
        remain valid, including qualities and constraints, and are reclassified
        later by their semantics.
        """
        if not business_context:
            return ""
        directives: list[str] = []
        for clause in self._source_clauses(business_context, None):
            lower = f" {clause.casefold()} "
            product_subject = re.search(
                r"\b(?:application|platform|product|service|software|system|tool)\b",
                lower,
            )
            directive = re.search(
                r"\b(?:must|shall|should|needs?\s+to|required\s+to|"
                r"allow|allows|enable|enables|provide|provides|support|supports)\b",
                lower,
            )
            imperative = re.match(
                r"^(?:must|shall|allow|enable|provide|support|retain|ensure)\b",
                clause.strip(),
                flags=re.I,
            )
            if (product_subject and directive) or imperative:
                directives.append(clause)
        return " ".join(directives)

    def _extract_explicit_data_characteristics(
        self, description: str, business_context: str | None
    ) -> list[str]:
        characteristics: list[str] = []
        for clause in self._source_clauses(description, business_context):
            lower_clause = clause.lower()
            categories = {
                "Geospatial data": ("geospatial", "coordinates", "map"),
                "File-based data exchange": ("file", "import", "export"),
                "Incremental or streaming data": ("as they arrive", "stream", "telemetry"),
                "Provenance and lineage data": ("immutable", "lineage", "provenance", "tamper-evident"),
                "Versioned or conflict-aware data": ("conflict", "sequence", "version"),
                "Instrument or sensor observations": (
                    "controller", "humidity", "measurement", "reading", "sensor", "ultraviolet"
                ),
                "User-defined operating rules": ("-defined", "configurable threshold"),
                "Reversibility-sensitive records": ("reversible", "reversibility"),
            }
            for label, markers in categories.items():
                if any(marker in lower_clause for marker in markers):
                    characteristics.append(f"{label}: {clause}")
        return self._dedupe(characteristics)

    def _extract_integration_requirements(self, requirements: list[str]) -> list[str]:
        return extract_integrations(" ".join(requirements), None)

    def _extract_named_integrations(
        self, description: str, business_context: str | None
    ) -> list[str]:
        # Use the canonical parser so a sentence containing several systems
        # becomes several typed boundaries rather than one sentence-shaped
        # integration name.
        return extract_integrations(description, business_context)

    def _preserve_uncovered_clauses(
        self,
        functional: list[str],
        constraints: list[str],
        integrations: list[str],
        description: str,
        business_context: str | None,
    ) -> tuple[list[str], list[str], list[str]]:
        represented_text = " ".join([*functional, *constraints, *integrations])
        sources = [(description, True)]
        if business_context:
            sources.append((business_context, False))
        for source, behavior_source in sources:
            for source_clause in self._source_clauses(source, None):
                clause = self._authoritative_requirement_clause(source_clause)
                if not clause:
                    continue
                lower_clause = clause.lower()
                if self._clause_coverage(clause, represented_text) >= 0.85:
                    continue
                is_integration = any(
                    re.search(pattern, lower_clause)
                    for pattern in (
                        r"\bintegrat(?:e|es|ion)\s+with\b",
                        r"\bimport(?:s|ed|ing)?\b.+\bfrom\b",
                        r"\bexport(?:s|ed|ing)?\b.+\bto\b",
                    )
                )
                hard_obligation = any(
                    marker in f" {lower_clause} "
                    for marker in (
                        " must ", " never ", " only ", " cannot ", " require ",
                        " requires ", " required ", " shall ", " does not ", " do not ",
                    )
                )
                context_directive = behavior_source or bool(
                    self._business_context_requirement_text(source_clause)
                )
                if is_integration:
                    parsed = extract_integrations(clause, None)
                    for integration in parsed:
                        if self._clause_coverage(integration, " ".join(integrations)) < 0.85:
                            integrations.append(integration)
                elif hard_obligation and context_directive and (
                    "do not assume" not in lower_clause and "don't assume" not in lower_clause
                ):
                    constraints.append(clause)
                elif (
                    context_directive
                    and self._looks_like_capability(clause)
                    and len(tokenize(clause)) >= 4
                ):
                    best_index = None
                    best_score = 0.0
                    for index, requirement in enumerate(functional):
                        score = max(
                            self._clause_coverage(clause, requirement),
                            self._clause_coverage(requirement, clause),
                        )
                        if score > best_score:
                            best_index = index
                            best_score = score
                    if best_index is not None and best_score >= 0.3:
                        functional[best_index] = clause
                    else:
                        functional.append(clause)
                represented_text += f" {clause}"
        return self._dedupe(functional), self._dedupe_constraints(constraints), self._dedupe(integrations)

    def _authoritative_requirement_clause(self, clause: str) -> str | None:
        framing = re.match(
            r"^(?:build|create|develop)\b.+?\bwhere\s+(.+)$",
            clause.rstrip("."),
            flags=re.IGNORECASE,
        )
        if framing:
            clause = framing.group(1)
        elif clause.casefold().startswith(("build ", "create ", "develop ")):
            return None
        cleaned = clause.strip().rstrip(".")
        return cleaned[:1].upper() + cleaned[1:] + "." if cleaned else None

    def _looks_like_capability(self, clause: str) -> bool:
        return re.search(
            r"\b(?:allow|approve|capture|continue|coordinate|create|export|import|ingest|maintain|manage|monitor|pause|process|record|register|review|search|synchronize|track|update|view)\w*\b",
            clause,
            flags=re.IGNORECASE,
        ) is not None

    def _source_clauses(
        self, description: str, business_context: str | None
    ) -> list[str]:
        text = " ".join(part for part in (description, business_context or "") if part)
        clauses: list[str] = []
        for sentence in split_sentences(text):
            if not sentence.strip():
                continue
            lower_sentence = sentence.casefold()
            # Sentences carrying obligation language ("must ...", "required ...")
            # are kept whole: splitting them on commas produces fragments such
            # as "privacy" or "financial" that lose their meaning.
            keep_whole = (
                "do not assume" in lower_sentence
                or "don't assume" in lower_sentence
                or any(
                    marker in f" {lower_sentence} "
                    for marker in (
                        " must ", " must not ", " shall ", " need ", " needs ",
                        " required ", " requires ", " only ", " cannot ",
                        " never ", " at least ", " no more than ",
                    )
                )
            )
            parts = [sentence] if keep_whole else re.split(r",\s+", sentence)
            for part in parts:
                # `split_sentences` has already reattached conjunction-led
                # continuations.  Never strip `and` here: doing so converted
                # meaningful clauses into detached requirement fragments.
                cleaned = part.strip().rstrip(".;!?")
                if cleaned:
                    clauses.append(cleaned[:1].upper() + cleaned[1:] + ".")
        return clauses

    def _extract_explicit_unknown_questions(
        self, description: str, business_context: str | None
    ) -> list[str]:
        text = " ".join(part for part in (description, business_context or "") if part)
        lower_text = text.casefold()
        if "do not assume" not in lower_text and "don't assume" not in lower_text:
            return []

        candidates = (
            (("cloud", "hosting", "provider"), "Which hosting environment or cloud provider, if any, is required?"),
            (("user count", "users", "traffic", "workload"), "What user volume, workload, and growth should the architecture support?"),
            (("latency", "response time"), "What latency or response-time targets apply to critical workflows?"),
            (("availability", "uptime", "sla"), "What availability and recovery targets are required?"),
            (("retention",), "How long must operational and audit data be retained?"),
            (("team size", "team"), "What team size and operational skills are available?"),
            (("region", "geography"), "Which deployment regions or data-residency boundaries apply?"),
        )
        return [question for markers, question in candidates if any(marker in lower_text for marker in markers)]

    def _clause_coverage(self, clause: str, represented_text: str) -> float:
        stop_words = {
            "a", "an", "and", "any", "are", "as", "be", "before", "build", "but",
            "for", "from", "in", "is", "it", "of", "on", "or", "software", "system",
            "the", "to", "when", "with",
        }
        clause_tokens = {
            self._normalize_token(token)
            for token in re.findall(r"[a-z][a-z0-9-]+", clause.lower())
            if token not in stop_words
        }
        represented_tokens = {
            self._normalize_token(token)
            for token in re.findall(r"[a-z][a-z0-9-]+", represented_text.lower())
        }
        if not clause_tokens:
            return 1.0
        return len(clause_tokens & represented_tokens) / len(clause_tokens)

    def _normalize_token(self, token: str) -> str:
        if token.endswith("ies") and len(token) > 4:
            return token[:-3] + "y"
        if token.endswith("s") and not token.endswith("ss") and len(token) > 4:
            return token[:-1]
        return token

    def _tokens_fully_grounded(self, label: str, source_text: str) -> bool:
        """Whether every significant token of a label appears in the source.

        Ollama often invents qualified names ("Sales Manager", "Financial Record")
        where only the head noun exists in the brief. Head-only checks let those
        through; full-token grounding rejects an invented qualifier while keeping
        genuine brief participants (pluralization-insensitive).
        """
        tokens = [
            self._normalize_token(token)
            for token in re.findall(r"[a-z][a-z0-9-]+", label.casefold())
            if len(token) > 2
        ]
        if not tokens:
            return False
        source_tokens = {
            self._normalize_token(token)
            for token in re.findall(r"[a-z][a-z0-9-]+", source_text.casefold())
        }
        return all(token in source_tokens for token in tokens)

    def _filter_grounded_items(
        self,
        values: list[str],
        source_text: str,
        warnings: list[str],
        label: str,
        *,
        allow_inference: bool = False,
    ) -> list[str]:
        filtered: list[str] = []
        for raw_value in values:
            value = " ".join(raw_value.split()).strip()
            if not value:
                continue
            unsupported_numbers = self._unsupported_numbers(value, source_text)
            unsupported_technologies = self._unsupported_technologies(value, source_text)
            unsupported_characteristics = self._unsupported_characteristics(
                value, source_text
            )
            unsupported_actions = self._unsupported_actions(value, source_text)
            unsupported_unknown_claims = (
                []
                if label == "open question"
                else self._unsupported_unknown_claims(value, source_text)
            )
            if (
                unsupported_numbers
                or unsupported_technologies
                or unsupported_characteristics
                or unsupported_actions
                or unsupported_unknown_claims
            ):
                details = ", ".join(
                    [
                        *unsupported_numbers,
                        *unsupported_technologies,
                        *unsupported_characteristics,
                        *unsupported_actions,
                        *unsupported_unknown_claims,
                    ]
                )
                warnings.append(f"Removed ungrounded {label}: {details}.")
                continue
            if label == "functional requirement" and not self._has_meaningful_overlap(
                value, source_text, threshold=0.4
            ):
                warnings.append("Removed weakly grounded functional requirement.")
                continue
            if label == "non-functional requirement" and not self._has_meaningful_overlap(
                value, source_text, threshold=0.5
            ):
                warnings.append("Removed weakly grounded non-functional requirement.")
                continue
            if not allow_inference and label in {"constraint", "integration"}:
                if not self._has_meaningful_overlap(value, source_text):
                    warnings.append(f"Removed weakly grounded {label}.")
                    continue
            filtered.append(value)
        return filtered

    def _strip_unsupported_claims(self, value: str, source_text: str) -> str:
        if self._unsupported_numbers(value, source_text):
            return ""
        if self._unsupported_technologies(value, source_text):
            return ""
        if self._unsupported_characteristics(value, source_text):
            return ""
        if self._unsupported_actions(value, source_text):
            return ""
        if self._unsupported_unknown_claims(value, source_text):
            return ""
        return " ".join(value.split()).strip()

    def _label_is_safe(self, value: str, source_text: str) -> bool:
        return not self._unsupported_numbers(
            value, source_text
        ) and not self._unsupported_technologies(
            value, source_text
        ) and not self._unsupported_characteristics(
            value, source_text
        ) and not self._unsupported_actions(
            value, source_text
        ) and not self._unsupported_unknown_claims(value, source_text)

    def _unsupported_numbers(self, value: str, source_text: str) -> list[str]:
        output_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", value.lower()))
        source_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", source_text.lower()))
        return sorted(output_numbers - source_numbers)

    def _unsupported_technologies(self, value: str, source_text: str) -> list[str]:
        lower_value = value.lower()
        lower_source = source_text.lower()
        return [
            technology
            for technology in TECHNOLOGY_NAMES
            if re.search(rf"\b{re.escape(technology)}\b", lower_value)
            and not re.search(rf"\b{re.escape(technology)}\b", lower_source)
        ]

    def _unsupported_characteristics(self, value: str, source_text: str) -> list[str]:
        lower_value = value.casefold()
        lower_source = source_text.casefold()
        return [
            characteristic
            for characteristic, (output_markers, source_markers) in SPECIAL_CHARACTERISTICS.items()
            if any(marker in lower_value for marker in output_markers)
            and not any(marker in lower_source for marker in source_markers)
        ]

    def _unsupported_actions(self, value: str, source_text: str) -> list[str]:
        lower_value = value.casefold()
        lower_source = source_text.casefold()
        return [
            action
            for action, markers in ACTION_FAMILIES.items()
            if any(re.search(rf"\b{re.escape(marker)}\b", lower_value) for marker in markers)
            and not any(re.search(rf"\b{re.escape(marker)}\b", lower_source) for marker in markers)
        ]

    def _unsupported_unknown_claims(self, value: str, source_text: str) -> list[str]:
        directives = " ".join(
            re.findall(
                r"(?:do not assume|don't assume)\s+([^.!?]+)",
                source_text.casefold(),
            )
        )
        if not directives or value.rstrip().endswith("?"):
            return []
        lower_value = value.casefold()
        return [
            topic
            for topic, source_markers, output_markers in UNCERTAIN_TOPIC_MARKERS
            if any(marker in directives for marker in source_markers)
            and any(marker in lower_value for marker in output_markers)
        ]

    def _ensure_non_functional_requirements(
        self,
        values: list[str],
        actors: list[Actor],
        entities: list[DomainEntityHint],
        workflows: list[DomainWorkflowHint],
        source_text: str = "",
    ) -> list[str]:
        """Backfill NFRs only from brief-evidenced quality language.

        The previous version unconditionally injected generic consistency /
        authorization / validation sentences whenever fewer than two NFRs
        survived grounding, which violated the extraction prompt's no-invention
        rule and turned every unknown domain into the same three NFRs.
        Candidates are now added only when they share vocabulary with the
        source brief; otherwise the gap stays an open question.
        """
        requirements = self._dedupe(values)
        if len(requirements) >= 2:
            return requirements
        # Generic candidates name the workflows/actors/entities, which would
        # always pass a coverage check against them. Gate each candidate on
        # the brief actually discussing that concern; otherwise the gap stays
        # an open question instead of a fabricated requirement.
        lower_source = (source_text or "").casefold()
        has_consistency_signal = any(
            marker in lower_source
            for marker in ("consisten", "integrity", "concurren", "conflict", "atomic", "state")
        )
        # Actor nouns alone ("operator", "reviewer") are not authorization
        # evidence; only identity/access language justifies the boundary NFR.
        has_auth_signal = any(
            marker in lower_source
            for marker in ("auth", "permission", "role", "boundary", "access")
        )
        has_validation_signal = any(
            marker in lower_source
            for marker in ("validat", "partial", "transaction", "workflow", "approv")
        )
        workflow_names = " and ".join(workflow.name for workflow in workflows[:2])
        entity_names = ", ".join(entity.name for entity in entities[:3])
        actor_names = ", ".join(actor.name for actor in actors[:3])
        candidates = [
            (
                (
                    f"Preserve consistent domain state across {workflow_names} workflows."
                    if workflow_names
                    else "Preserve consistent domain state across confirmed workflows."
                ),
                has_consistency_signal,
            ),
            (
                (
                    f"Enforce authorization boundaries for {actor_names} according to their confirmed responsibilities."
                    if actor_names
                    else "Enforce authorization boundaries according to confirmed actor responsibilities."
                ),
                has_auth_signal,
            ),
            (
                (
                    f"Validate changes to {entity_names} without leaving partial updates."
                    if entity_names
                    else "Validate state changes without leaving partial updates."
                ),
                has_validation_signal,
            ),
        ]
        for candidate, allowed in candidates:
            if len(requirements) >= 2:
                break
            if not allowed:
                continue
            requirements.append(candidate)
        return self._dedupe(requirements)

    def _has_meaningful_overlap(
        self, value: str, source_text: str, *, threshold: float = 0.25
    ) -> bool:
        stop_words = {
            "a", "an", "and", "are", "as", "be", "for", "from", "in", "is", "of",
            "on", "or", "should", "system", "the", "to", "with",
        }
        value_tokens = {
            self._normalize_token(token)
            for token in re.findall(r"[a-z][a-z0-9_-]+", value.lower())
            if token not in stop_words
        }
        source_tokens = {
            self._normalize_token(token)
            for token in re.findall(r"[a-z][a-z0-9_-]+", source_text.lower())
        }
        return bool(value_tokens) and len(value_tokens & source_tokens) / len(value_tokens) >= threshold

    def _actor_is_active(self, name: str, source_text: str) -> bool:
        normalized_name = " ".join(
            self._normalize_token(token)
            for token in re.findall(r"[a-z][a-z0-9-]+", name.casefold())
        )
        normalized_source = " ".join(
            self._normalize_token(token)
            for token in re.findall(r"[a-z][a-z0-9-]+", source_text.casefold())
        )
        actor_tokens = set(normalized_name.split())
        if not actor_tokens or not actor_tokens.issubset(set(normalized_source.split())):
            return False

        actor = re.escape(normalized_name)
        passive_reference = re.search(
            rf"\b(?:browse|choose|find|search|see|select|view)\s+(?:available\s+)?{actor}\b",
            normalized_source,
        )
        explicit_action = re.search(
            rf"\b{actor}\s+(?:can|may|must|should|will|approve|book|cancel|continue|create|enter|ingest|maintain|manage|monitor|operate|pause|provide|record|register|reschedule|review|submit|sync|update|use)(?:s|d|ed|ing)?\b",
            normalized_source,
        )
        enabled_action = re.search(
            rf"\b(?:allow|enable|let)(?:s|d)?\s+(?:the\s+)?{actor}\s+(?:to\s+)?\w+",
            normalized_source,
        )
        machine_actor = any(
            marker in actor_tokens
            for marker in ("controller", "device", "instrument", "sensor")
        )
        if passive_reference and not explicit_action and not enabled_action:
            return False
        return explicit_action is not None or enabled_action is not None or machine_actor

    def _external_party_is_integration_boundary(
        self, name: str, source_text: str
    ) -> bool:
        """Accept a named business party when the product exchanges with it."""
        tokens = {
            self._normalize_token(token)
            for token in tokenize(name)
        }
        if not tokens & {
            "partner", "supplier", "vendor", "provider", "retailer",
            "wholesaler", "distributor", "carrier", "broker", "manufacturer",
        }:
            return False
        name_words = [self._normalize_token(token) for token in tokenize(name)]
        head = re.escape(name_words[-1]) if name_words else ""
        normalized = " ".join(
            self._normalize_token(token)
            for token in tokenize(source_text)
        )
        return bool(re.search(
            rf"\b(?:integrate|integration|exchange|sync|synchronize)\w*\b[^.!?]{{0,100}}\b{head}\b",
            normalized,
        ))

    def _actor_grounded_in_requirements(
        self, name: str, functional: list[str], source_text: str = ""
    ) -> bool:
        """Whether a requirement assigns an action to the actor as subject."""
        words = [
            self._normalize_token(token)
            for token in re.findall(r"[a-z][a-z0-9-]+", name.casefold())
            if len(token) > 3
        ]
        if not words:
            return False
        head = words[-1]
        if source_text:
            source_tokens = {
                self._normalize_token(token)
                for token in re.findall(r"[a-z][a-z0-9-]+", source_text.casefold())
            }
            if not any(
                self._role_head_matches(head, candidate) for candidate in source_tokens
            ):
                return False
        action_pattern = (
            r"(?:can|may|must|should|will|shall|able|"
            r"accept|add|allocate|analyze|approve|assess|assign|authenticate|"
            r"book|browse|calibrate|cancel|capture|check|collect|compute|configure|"
            r"coordinate|create|deploy|dispatch|download|enter|evaluate|execute|export|"
            r"fulfill|generate|import|index|ingest|inspect|issue|maintain|make|manage|"
            r"measure|monitor|notify|operate|orchestrate|pay|perform|place|plan|prepare|"
            r"process|produce|provision|publish|receive|record|register|render|report|"
            r"request|resolve|review|route|scan|schedule|search|send|settle|simulate|"
            r"stream|submit|support|sync|track|transfer|transform|transmit|update|upload|"
            r"use|validate|verify|view)\w*"
        )
        for requirement in functional:
            normalized = " ".join(
                self._normalize_token(token)
                for token in re.findall(r"[a-z][a-z0-9-]+", requirement.casefold())
            )
            # Allow up to two role modifiers between the head and its verb,
            # but never validate an object mentioned after somebody else's
            # action ("operators support customers").
            if re.search(
                rf"\b{re.escape(head)}\b(?:\s+\w+){{0,2}}\s+{action_pattern}\b",
                normalized,
            ):
                return True
        return False

    @staticmethod
    def _role_head_matches(head: str, candidate: str) -> bool:
        """Whether a brief token validates an actor's head role noun.

        Only true morphological kinship counts: identical stems, plurals, or
        collective nouns ("partnership" validates "partner"). Activity
        nominalizations ("management") and bare verbs ("manage") never
        validate the corresponding role ("manager"), and related-but-distinct
        words ("distribution" vs "distributor") need their own mention —
        which genuine briefs provide.
        """
        if len(candidate) <= 3:
            return False
        if head == candidate:
            return True
        if candidate.startswith(head):
            return candidate[len(head):] in {"s", "es", "ship"}
        return False

    def _actor_description(self, name: str, functional: list[str]) -> str:
        for requirement in functional:
            if self._clause_coverage(name, requirement) > 0:
                return requirement
        return "Responsibilities require clarification."

    def _build_workflow_hints(
        self,
        _names: list[str],
        functional: list[str],
        actors: list[Actor],
        entities: list[DomainEntityHint],
        source_text: str,
    ) -> list[DomainWorkflowHint]:
        workflows: list[DomainWorkflowHint] = []
        # Keep enough independently decomposed workflows for downstream API
        # contracts; six broad items used to hide later actor operations.
        for matching_requirement in functional[:16]:
            name = self._workflow_name(matching_requirement)
            actor_scores = []
            req_lower = matching_requirement.lower()
            for item in actors:
                coverage = self._clause_coverage(item.name, matching_requirement)
                if coverage > 0:
                    pos = req_lower.find(item.name.lower())
                    if pos == -1:
                        first_tok = next((t for t in item.name.lower().split() if len(t) > 2), "")
                        pos = req_lower.find(first_tok) if first_tok else 999
                    pos = pos if pos != -1 else 999
                    actor_scores.append((coverage, -pos, item))
            actor = max(actor_scores, key=lambda triplet: (triplet[0], triplet[1]))[2] if actor_scores else None
            related_entities = [
                entity.name
                for entity in entities
                if self._clause_coverage(
                    entity.name, f"{name} {matching_requirement}"
                )
                > 0
            ]
            workflows.append(
                DomainWorkflowHint(
                    name=name,
                    description=matching_requirement,
                    primary_actor=actor.name if actor else "Needs clarification",
                    related_entities=related_entities,
                )
            )
        return self._dedupe_workflows(workflows)

    def _workflow_name(self, requirement: str) -> str:
        value = requirement.rstrip(".").strip()
        value = re.sub(
            r"^(the organization|the platform|the system|the company|also)\s+",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"^(key capabilities|capabilities)\s+(include|including)\s+",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(r"^(include|including)\s+", "", value, flags=re.IGNORECASE)
        passive = re.match(
            r"(.+?)\s+(?:can|must|should|will)?\s*be\s+([a-z]+)\b",
            value,
            flags=re.IGNORECASE,
        )
        if passive:
            action = self._base_verb(passive.group(2))
            value = f"{action} {passive.group(1)}"
        else:
            maintained = re.match(
                r"(.+?)\s+(?:is|are)\s+([a-z]+)\b",
                value,
                flags=re.IGNORECASE,
            )
            if maintained:
                value = f"{self._base_verb(maintained.group(2))} {maintained.group(1)}"
            else:
                sliced = self._slice_at_first_action(value)
                if sliced:
                    value = sliced
                else:
                    value = re.sub(
                        r"^[A-Za-z][A-Za-z ]{0,40}\s+(?:can|may|must|should|will)\s+",
                        "",
                        value,
                        flags=re.IGNORECASE,
                    )
                    value = re.sub(r"^system\s+", "", value, flags=re.IGNORECASE)
                    words = value.split()
                    if words:
                        from app.services.domain_inference import _CAPABILITY_VERBS as _VERBS

                        if words[0].strip(",;").lower() in _VERBS:
                            words[0] = self._base_verb(words[0])
                        value = " ".join(words)
        value = re.sub(r"\s*\([^)]*$", "", value)
        words = [word.strip(",;") for word in value.split()[:6]]
        while words and words[-1].lower() in {
            "for", "through", "with", "to", "of", "and", "across", "in", "on", "that",
        }:
            words.pop()
        return " ".join(words).title()

    @staticmethod
    def _slice_at_first_action(value: str) -> str | None:
        """Slice framing prose to verb + object ("... company that manages
        product formulation, ..." -> "manage product formulation").

        Only verbs slice (noun-led items like "Supply chain management" are
        already crisp labels). Passive/maintained constructions are handled
        by their dedicated branches before this runs.
        """
        from app.services.domain_inference import _BASE_ACTION_VERBS

        words = value.split()
        for index, word in enumerate(words):
            cleaned = word.strip(",;").lower()
            if cleaned in _BASE_ACTION_VERBS:
                chosen = [words[index], *words[index + 1: index + 3]]
                return " ".join(part.strip(",;") for part in chosen)
        return None

    def _base_verb(self, value: str) -> str:
        lower = value.casefold()
        common_past = {
            "approved": "approve",
            "created": "create",
            "maintained": "maintain",
            "operated": "operate",
            "paused": "pause",
            "preserved": "preserve",
            "registered": "register",
            "updated": "update",
            "supporting": "support",
            "maintaining": "maintain",
            "processing": "process",
            "providing": "provide",
            "tracking": "track",
        }
        if lower in common_past:
            return common_past[lower]
        if lower.endswith("ies") and len(lower) > 4:
            return lower[:-3] + "y"
        if lower.endswith("ses") and len(lower) > 4:
            return lower[:-2]
        if lower.endswith("s") and not lower.endswith("ss") and len(lower) > 3:
            return lower[:-1]
        return lower

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            # Normalized key ignores punctuation/case so "Support X." and
            # "Support X" collapse instead of duplicating requirements.
            key = self._requirement_key(value)
            if key and key not in seen:
                deduped.append(value)
                seen.add(key)
        return deduped

    def _dedupe_constraints(self, values: list[str]) -> list[str]:
        """Collapse repeated constraints even when provenance wrappers differ.

        Clarifications may be re-applied to an already generated workspace.
        Exact string dedupe cannot recognize that ``User-specified retention:
        7 years`` and ``Retain records for 7 years`` express the same boundary.
        This conservative token comparison removes only near-equivalent
        statements; related but independently testable limits remain separate.
        """
        normalized, _ = normalize_constraint_statements(values)
        result: list[str] = []
        signatures: list[set[str]] = []
        for value in normalized:
            signature = self._constraint_signature(value)
            duplicate = False
            for prior in signatures:
                if not signature or not prior:
                    continue
                shared = len(signature & prior)
                containment = shared / min(len(signature), len(prior))
                union = shared / len(signature | prior)
                if (
                    signature == prior
                    or (min(len(signature), len(prior)) >= 3 and containment >= 0.9)
                    or (min(len(signature), len(prior)) >= 4 and union >= 0.72)
                ):
                    duplicate = True
                    break
            if not duplicate:
                result.append(value)
                signatures.append(signature)
        return result

    def _constraint_signature(self, value: str) -> set[str]:
        aliases = {
            "available": "availability", "uptime": "availability",
            "retain": "retention", "retained": "retention", "retaining": "retention",
            "host": "hosting", "hosted": "hosting",
            "engineer": "team", "engineers": "team",
            "formats": "format", "protocols": "protocol",
            "requires": "require", "required": "require",
        }
        boilerplate = {
            "apply", "architecture", "clarification", "confirmed", "described",
            "expectation", "preference", "project", "selected", "specified",
            "user", "must", "shall", "should", "require", "use", "using",
            "the", "a", "an", "and", "or", "to", "for", "of", "is", "be",
        }
        tokens = {
            aliases.get(self._normalize_token(token), self._normalize_token(token))
            for token in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?%?", value.casefold())
        }
        return {token for token in tokens if token and token not in boilerplate}

    def _requirement_key(self, value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))

    def _dedupe_characteristics(self, values: list[str]) -> list[str]:
        # Dedupe by full normalized content, not by category prefix: two
        # distinct "Geospatial data: ..." clauses must both survive.
        seen: set[str] = set()
        result: list[str] = []
        for value in self._dedupe(values):
            key = self._requirement_key(value)
            if key not in seen:
                result.append(value)
                seen.add(key)
        return result

    def _merge_explicit_items(
        self, generated: list[str], explicit: list[str]
    ) -> list[str]:
        result = list(generated)
        for source_item in explicit:
            source_special = {
                name
                for name, (_, source_markers) in SPECIAL_CHARACTERISTICS.items()
                if any(marker in source_item.casefold() for marker in source_markers)
            }
            matching_indices: list[int] = []
            for index, candidate in enumerate(result):
                score = max(
                    self._clause_coverage(source_item, candidate),
                    self._clause_coverage(candidate, source_item),
                )
                candidate_special = {
                    name
                    for name, (output_markers, _) in SPECIAL_CHARACTERISTICS.items()
                    if any(marker in candidate.casefold() for marker in output_markers)
                }
                if source_special & candidate_special:
                    score = max(score, 0.75)
                shared_quality_markers = {
                    marker
                    for marker in (
                        "audit", "conflict", "offline", "privacy", "provenance",
                        "real-time", "realtime", "recovery", "retention", "safety",
                        "secure", "tamper-evident",
                    )
                    if marker in source_item.casefold() and marker in candidate.casefold()
                }
                if shared_quality_markers:
                    score = max(score, 0.75)
                if score >= 0.5:
                    matching_indices.append(index)
            if matching_indices:
                matched = set(matching_indices)
                result = [candidate for index, candidate in enumerate(result) if index not in matched]
            result.append(source_item)
        return self._dedupe(result)

    def _answer_is_known(self, value: str) -> bool:
        return " ".join(value.split()).casefold() not in UNKNOWN_ANSWER_VALUES

    @staticmethod
    def _parse_team_size(value: str) -> int:
        match = re.search(r"\d+", str(value or ""))
        return int(match.group()) if match else 0

    def _dedupe_actors(self, values: list[Actor]) -> list[Actor]:
        seen: set[str] = set()
        result: list[Actor] = []
        for value in values:
            key = value.name.casefold()
            if key not in seen:
                result.append(value)
                seen.add(key)
        return result

    def _dedupe_entities(self, values: list[DomainEntityHint]) -> list[DomainEntityHint]:
        seen: set[str] = set()
        result: list[DomainEntityHint] = []
        for value in values:
            key = value.name.casefold()
            if key not in seen:
                result.append(value)
                seen.add(key)
        return result

    def _dedupe_workflows(self, values: list[DomainWorkflowHint]) -> list[DomainWorkflowHint]:
        seen: set[str] = set()
        result: list[DomainWorkflowHint] = []
        for value in values:
            key = value.name.casefold()
            if key not in seen:
                result.append(value)
                seen.add(key)
        return result
