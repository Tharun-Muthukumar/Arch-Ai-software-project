import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from pydantic import BaseModel, Field, ValidationError

from app.schemas.domain import (
    Actor,
    DomainEntityHint,
    DomainWorkflowHint,
    RequirementModel,
)
from app.services.ai.client import OllamaStructuredClient


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
    functional_requirements: list[str] = Field(min_length=2, max_length=10)
    non_functional_requirements: list[str] = Field(min_length=2, max_length=6)
    actors: list[str] = Field(min_length=1, max_length=6)
    domain_entities: list[str] = Field(min_length=2, max_length=8)
    domain_workflows: list[str] = Field(min_length=2, max_length=6)
    integrations: list[str] = Field(default_factory=list, max_length=8)
    data_characteristics: list[str] = Field(default_factory=list, max_length=8)
    explicit_constraints: list[str] = Field(default_factory=list, max_length=8)
    assumptions: list[str] = Field(default_factory=list, max_length=6)
    open_questions: list[str] = Field(min_length=1, max_length=8)


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
        entities=("users", "products", "orders", "order_items", "payments", "shipments"),
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
}

ACTION_FAMILIES = {
    "approval": ("approve", "approved", "approves", "approving", "approval"),
    "deletion": ("delete", "deleted", "deletes", "deleting", "deletion"),
    "export": ("export", "exported", "exporting"),
    "generation": ("generate", "generated", "generates", "generating", "generation"),
    "import": ("import", "imported", "importing"),
    "notification": ("notify", "notified", "notifies", "notification", "notifications"),
    "rejection": ("reject", "rejected", "rejecting", "rejection"),
    "synchronization": ("sync", "synchronize", "synchronized", "synchronization"),
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
    ) -> RequirementModel:
        answers = answers or {}
        constraints = constraints or []
        combined_text = " ".join(
            part for part in [title, description, business_context or ""] if part
        )
        blueprint = self._pick_blueprint(combined_text)
        if blueprint is None:
            return self._analyze_unknown(
                title, description, business_context, answers, constraints
            )
        return self._analyze_known(
            title,
            combined_text,
            business_context,
            answers,
            constraints,
            blueprint,
        )

    def _analyze_unknown(
        self,
        title: str,
        description: str,
        business_context: str | None,
        answers: dict[str, str],
        constraints: list[str],
    ) -> RequirementModel:
        effective_constraints = self._dedupe(
            [*constraints, *self._constraints_from_answers(answers)]
        )
        raw_requirement = {
            "title": title,
            "description": description,
            "business_context": business_context,
            "user_constraints": effective_constraints,
            "clarification_answers": answers,
        }
        source_text = " ".join(
            [title, description, business_context or "", *effective_constraints, *answers.values()]
        )
        generated = self.ai_client.generate(
            "unknown-domain-requirement-extraction",
            {"raw_requirement": raw_requirement},
            response_schema=UnknownDomainExtraction.model_json_schema(),
            num_predict=520,
            num_ctx=4096,
            minimum_timeout_seconds=90,
        )
        if generated is None:
            return self._conservative_fallback(title, description, effective_constraints)

        try:
            extraction = UnknownDomainExtraction.model_validate(generated)
        except ValidationError as exc:
            fallback = self._conservative_fallback(title, description, effective_constraints)
            fallback.analysis_warnings.append(
                f"Ollama returned invalid structured requirements: {exc.errors()[0]['msg']}"
            )
            return fallback

        warnings: list[str] = []
        functional = self._filter_grounded_items(
            extraction.functional_requirements, source_text, warnings, "functional requirement"
        )
        if len(functional) < 2:
            fallback = self._conservative_fallback(title, description, effective_constraints)
            fallback.analysis_warnings.extend(warnings)
            fallback.analysis_warnings.append(
                "Ollama output did not retain enough grounded functional detail."
            )
            return fallback

        non_functional = self._filter_grounded_items(
            [
                *extraction.non_functional_requirements,
                *self._extract_explicit_quality_requirements(description, business_context),
            ],
            source_text,
            warnings,
            "non-functional requirement",
        )
        model_constraints = [
            item
            for item in self._filter_grounded_items(
                extraction.explicit_constraints, source_text, warnings, "constraint"
            )
            if self._has_meaningful_overlap(item, source_text)
        ]
        actors = [
            Actor(
                name=actor.strip(),
                description=self._actor_description(actor, functional),
            )
            for actor in extraction.actors
            if actor.strip()
            and actor.strip().casefold() not in GENERIC_ACTOR_NAMES
            and self._label_is_safe(actor, source_text)
            and self._has_meaningful_overlap(actor, source_text)
            and self._actor_is_active(actor, source_text)
        ]
        entities = [
            DomainEntityHint(
                name=entity.strip(),
                description=f"{entity.strip()} identified from the user's brief.",
            )
            for entity in extraction.domain_entities
            if entity.strip()
            and self._label_is_safe(entity, source_text)
            and self._has_meaningful_overlap(entity, source_text)
        ]
        actors = self._dedupe_actors(actors)
        entities = self._dedupe_entities(entities)
        workflows = self._build_workflow_hints(
            extraction.domain_workflows,
            functional,
            actors,
            entities,
            source_text,
        )
        if not actors or len(entities) < 2 or len(workflows) < 2:
            fallback = self._conservative_fallback(title, description, effective_constraints)
            fallback.analysis_warnings.extend(warnings)
            fallback.analysis_warnings.append(
                "Ollama output lacked grounded actors, entities, or workflows required by the pipeline."
            )
            return fallback
        non_functional = self._ensure_non_functional_requirements(
            non_functional,
            actors,
            entities,
            workflows,
        )
        assumptions = [
            f"Assumption: {item.removeprefix('Assumption:').strip()}"
            for item in self._filter_grounded_items(
                extraction.assumptions,
                source_text,
                warnings,
                "assumption",
                allow_inference=True,
            )
            if item.strip()
        ]
        explicit_constraints = [
            *effective_constraints,
            *self._extract_explicit_constraints(description, business_context),
            *model_constraints,
        ]
        if budget := answers.get("budget"):
            explicit_constraints.append(f"User-specified budget posture: {budget}.")
        if (cloud := answers.get("preferred_cloud")) and cloud.casefold() != "no preference":
            explicit_constraints.append(f"User-specified hosting preference: {cloud}.")

        summary = self._strip_unsupported_claims(extraction.summary, source_text)
        if not summary:
            summary = f"{title}: {description}"

        source_integrations = self._extract_named_integrations(description, business_context)
        integration_candidates = source_integrations or [
            *extraction.integrations,
            *self._extract_integration_requirements(functional),
        ]
        integrations = self._dedupe(
            self._filter_grounded_items(
                integration_candidates,
                source_text,
                warnings,
                "integration",
            )
        )
        functional, explicit_constraints, integrations = self._preserve_uncovered_clauses(
            functional,
            explicit_constraints,
            integrations,
            description,
            business_context,
        )
        functional = self._preserve_uncovered_terms(functional, description)

        domain = self._strip_unsupported_claims(extraction.domain, source_text)
        if not domain:
            domain = "Unknown domain"
            warnings.append("Removed an ungrounded domain label.")

        return RequirementModel(
            summary=summary,
            domain=domain,
            scale_profile=self._infer_scale_profile(source_text, answers, unknown_default=True),
            functional_requirements=self._dedupe(functional),
            non_functional_requirements=self._dedupe(non_functional),
            actors=actors,
            constraints=self._dedupe(explicit_constraints),
            assumptions=self._dedupe(assumptions),
            domain_entities=entities,
            domain_workflows=workflows,
            integrations=self._dedupe(integrations),
            data_characteristics=self._dedupe(
                self._filter_grounded_items(
                    [
                        *extraction.data_characteristics,
                        *self._extract_explicit_data_characteristics(
                            description, business_context
                        ),
                    ],
                    source_text,
                    warnings,
                    "data characteristic",
                    allow_inference=True,
                )
            ),
            open_questions=self._dedupe(
                self._filter_grounded_items(
                    extraction.open_questions,
                    source_text,
                    warnings,
                    "open question",
                    allow_inference=True,
                )
            ),
            analysis_source="ollama-pretrained",
            analysis_warnings=self._dedupe(warnings),
        )

    def apply_clarifications(
        self,
        requirements: RequirementModel,
        answers: dict[str, str],
        questions: dict[str, str] | None = None,
    ) -> RequirementModel:
        updates = requirements.model_copy(deep=True)
        questions = questions or {}

        for key, raw_value in answers.items():
            value = " ".join(raw_value.split()).strip()
            if not value:
                continue

            lower_value = value.casefold()
            is_unknown = lower_value in {
                "undecided",
                "unknown",
                "not specified",
                "not specified yet",
                "needs discussion",
            }
            if key == "preferred_cloud" and lower_value != "no preference":
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
                        "Payment transaction handling is in scope."
                    )
                elif lower_value == "external system":
                    updates.integrations.append(
                        "An external payment system owns payment transactions."
                    )
                elif lower_value == "not in scope":
                    updates.constraints.append(
                        "Payment transaction handling is not in scope."
                    )
            elif key.startswith("domain_open_") and not is_unknown:
                question = questions.get(key, "Architecture-critical detail")
                updates.constraints.append(
                    f"Confirmed clarification - {question.rstrip('?')}: {value.rstrip('.')}."
                )

        updates.functional_requirements = self._dedupe(updates.functional_requirements)
        updates.non_functional_requirements = self._dedupe(
            updates.non_functional_requirements
        )
        updates.constraints = self._dedupe(updates.constraints)
        updates.integrations = self._dedupe(updates.integrations)
        return RequirementModel.model_validate(updates.model_dump())

    def _analyze_known(
        self,
        title: str,
        combined_text: str,
        business_context: str | None,
        answers: dict[str, str],
        constraints: list[str],
        blueprint: DomainBlueprint,
    ) -> RequirementModel:
        scale_profile = self._infer_scale_profile(combined_text, answers)
        functional_requirements = [*blueprint.features, *self._feature_overrides(combined_text)]
        non_functional_requirements = [
            "Maintain clear bounded contexts and strongly typed service contracts.",
            "Capture structured logs, metrics, and audit trails for all critical workflows.",
            "Enforce validation, graceful error handling, and resilient API boundaries.",
        ]
        if scale_profile == "high-scale":
            non_functional_requirements.append(
                "Scale horizontally for burst traffic and long-running background workloads."
            )
        else:
            non_functional_requirements.append(
                "Optimize for fast delivery while preserving modular extensibility."
            )

        domain_constraints = [f"Respect {item}." for item in blueprint.compliance]
        domain_constraints.extend(constraints)
        domain_constraints.extend(self._constraints_from_answers(answers))
        if budget := answers.get("budget"):
            domain_constraints.append(f"User-specified budget posture: {budget}.")
        if (cloud := answers.get("preferred_cloud")) and cloud.casefold() != "no preference":
            domain_constraints.append(f"User-specified hosting preference: {cloud}.")

        assumptions = []
        if business_context:
            assumptions.append(f"Business context considered: {business_context}.")
        requirement_model = RequirementModel(
            summary=f"{title} is modeled as a {blueprint.domain.lower()}.",
            domain=blueprint.domain,
            scale_profile=scale_profile,
            functional_requirements=self._dedupe(functional_requirements),
            non_functional_requirements=self._dedupe(non_functional_requirements),
            actors=[Actor(name=name, description=description) for name, description in blueprint.actors],
            constraints=self._dedupe(domain_constraints),
            assumptions=assumptions,
            domain_entities=[
                DomainEntityHint(
                    name=entity,
                    description=f"Core {blueprint.domain.lower()} record.",
                )
                for entity in blueprint.entities
            ],
            domain_workflows=[
                DomainWorkflowHint(
                    name=feature.rstrip("."),
                    description=feature,
                    primary_actor=blueprint.actors[0][0],
                )
                for feature in blueprint.features[:5]
            ],
            analysis_source="predefined-blueprint",
        )

        return requirement_model

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
        lower_change = change_request.lower()
        if "notification" in lower_change:
            updates.functional_requirements.append(
                "Support notification preferences and asynchronous delivery tracking."
            )
            updates.non_functional_requirements.append(
                "Notification workflows should remain eventually consistent and retry-safe."
            )
        if "analytics" in lower_change or "report" in lower_change:
            updates.functional_requirements.append(
                "Expose analytics dashboards and exportable reporting workflows."
            )
        if "payment" in lower_change:
            updates.functional_requirements.append(
                "Integrate secure payment authorization, capture, and refund workflows."
            )
        updates.assumptions.append(f"Change request considered: {change_request}.")
        return RequirementModel.model_validate(updates.model_dump())

    def _pick_blueprint(self, text: str) -> DomainBlueprint | None:
        lower_text = text.lower()
        for blueprint in BLUEPRINTS:
            if any(keyword in lower_text for keyword in blueprint.keywords):
                return blueprint
        return None

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
            return "startup-scale"
        return "unknown" if unknown_default else "startup-scale"

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
            return "startup-scale"

        lower_value = value.casefold()
        if any(marker in lower_value for marker in ("high", "large", "enterprise")):
            return "high-scale"
        if any(marker in lower_value for marker in ("growth", "medium")):
            return "growth-scale"
        if any(marker in lower_value for marker in ("pilot", "small", "startup")):
            return "startup-scale"
        return None

    def _constraints_from_answers(self, answers: dict[str, str]) -> list[str]:
        stored = answers.get("constraints", "")
        return [item.strip() for item in stored.split(";") if item.strip()]

    def _feature_overrides(self, text: str) -> list[str]:
        lower_text = text.lower()
        features: list[str] = []
        keyword_map = {
            "notification": "Allow users to manage notification preferences and delivery channels.",
            "payment": "Integrate payment authorization, settlement, and refund handling.",
            "search": "Provide full-text search with business-aware filtering.",
            "analytics": "Deliver usage analytics and operational KPI dashboards.",
            "chat": "Support conversational or collaborative workflows with moderation controls.",
            "mobile": "Keep APIs optimized for future mobile clients and offline-tolerant use cases.",
            "booking": "Allow users to reschedule or cancel reservations without losing operational traceability.",
            "charger": "Surface charger specifications, connector types, and live availability signals.",
            "station": "Present rich station details, operating windows, and wayfinding context.",
            "refund": "Support refund review flows with auditable payment status transitions.",
        }
        for keyword, feature in keyword_map.items():
            if keyword in lower_text:
                features.append(feature)
        return features

    def _extract_explicit_constraints(
        self, description: str, business_context: str | None
    ) -> list[str]:
        markers = (
            " must ", " must not ", " never ", " only ", " cannot ", " required ",
            " require ", " does not ", " do not ", " without ",
        )
        return [
            re.sub(r"^and\s+", "", clause, flags=re.IGNORECASE)
            for clause in self._source_clauses(description, business_context)
            if any(marker in f" {clause.lower()} " for marker in markers)
        ]

    def _extract_explicit_quality_requirements(
        self, description: str, business_context: str | None
    ) -> list[str]:
        quality_markers = (
            "audit", "conflict", "immediate", "immutable", "integrity", "latency",
            "lineage", "offline", "privacy", "provenance", "real-time", "realtime",
            "recovery", "reliable", "retention", "safety", "secure", "without connectivity",
        )
        return [
            clause
            for clause in self._source_clauses(description, business_context)
            if any(marker in clause.lower() for marker in quality_markers)
        ]

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
                "Immutable or lineage-preserving data": ("immutable", "lineage", "provenance"),
                "Versioned or conflict-aware data": ("conflict", "sequence", "version"),
            }
            for label, markers in categories.items():
                if any(marker in lower_clause for marker in markers):
                    characteristics.append(f"{label}: {clause}")
        return self._dedupe(characteristics)

    def _extract_integration_requirements(self, requirements: list[str]) -> list[str]:
        integrations: list[str] = []
        for requirement in requirements:
            match = re.match(
                r"(?:integrate|integration)\s+with\s+(.+?)(?:\s+system)?\.?$",
                requirement.strip(),
                flags=re.IGNORECASE,
            )
            if match:
                integrations.append(match.group(1).strip())
        return integrations

    def _extract_named_integrations(
        self, description: str, business_context: str | None
    ) -> list[str]:
        patterns = (
            r"\bintegrat(?:e|es|ion)\s+with\b",
            r"\bimport(?:s|ed|ing)?\b.+\bfrom\b",
            r"\bexport(?:s|ed|ing)?\b.+\bto\b",
        )
        integrations: list[str] = []
        for clause in self._source_clauses(description, business_context):
            if not any(re.search(pattern, clause, flags=re.IGNORECASE) for pattern in patterns):
                continue
            integration_clause = re.split(r"\s+but\s+", clause, maxsplit=1, flags=re.IGNORECASE)[0]
            integrations.append(integration_clause.rstrip(".") + ".")
        return integrations

    def _preserve_uncovered_clauses(
        self,
        functional: list[str],
        constraints: list[str],
        integrations: list[str],
        description: str,
        business_context: str | None,
    ) -> tuple[list[str], list[str], list[str]]:
        represented_text = " ".join([*functional, *constraints, *integrations])
        for clause in self._source_clauses(description, business_context):
            lower_clause = clause.lower()
            if lower_clause.startswith(("build ", "create ", "develop ")):
                continue
            if self._clause_coverage(clause, represented_text) >= 0.55:
                continue
            if any(
                re.search(pattern, lower_clause)
                for pattern in (
                    r"\bintegrat(?:e|es|ion)\s+with\b",
                    r"\bimport(?:s|ed|ing)?\b.+\bfrom\b",
                    r"\bexport(?:s|ed|ing)?\b.+\bto\b",
                )
            ):
                integrations.append(clause)
            elif any(
                marker in f" {lower_clause} "
                for marker in (
                    " must ", " never ", " only ", " cannot ", " require ",
                    " does not ", " do not ", " without ",
                )
            ):
                constraints.append(clause)
            represented_text += f" {clause}"
        return self._dedupe(functional), self._dedupe(constraints), self._dedupe(integrations)

    def _preserve_uncovered_terms(
        self, functional: list[str], description: str
    ) -> list[str]:
        stop_words = {
            "allow", "allows", "and", "available", "build", "can", "create",
            "develop", "for", "from", "launch", "need", "needs", "see", "should",
            "software", "system", "that", "the", "their", "them", "they", "this",
            "through", "user", "users", "view", "with", "would", "yes",
        }
        source_terms = {
            self._normalize_token(token)
            for token in re.findall(r"[a-z][a-z0-9-]+", description.casefold())
            if len(token) >= 4 and token not in stop_words
        }
        represented_terms = {
            self._normalize_token(token)
            for token in re.findall(
                r"[a-z][a-z0-9-]+", " ".join(functional).casefold()
            )
        }

        uncovered = [
            term
            for term in sorted(source_terms)
            if not any(
                SequenceMatcher(None, term, represented).ratio() >= 0.75
                for represented in represented_terms
            )
        ]
        for term in uncovered[:3]:
            functional.append(
                f"Support the explicitly mentioned {term} in the relevant workflow; exact behavior requires clarification."
            )
        return self._dedupe(functional)

    def _source_clauses(
        self, description: str, business_context: str | None
    ) -> list[str]:
        text = " ".join(part for part in (description, business_context or "") if part)
        return [
            clause.strip().rstrip(".;!?") + "."
            for clause in re.split(r"(?<=[.!?;])\s+", text)
            if clause.strip()
        ]

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
            if (
                unsupported_numbers
                or unsupported_technologies
                or unsupported_characteristics
                or unsupported_actions
            ):
                details = ", ".join(
                    [
                        *unsupported_numbers,
                        *unsupported_technologies,
                        *unsupported_characteristics,
                        *unsupported_actions,
                    ]
                )
                warnings.append(f"Removed ungrounded {label}: {details}.")
                continue
            if label == "non-functional requirement" and not self._has_meaningful_overlap(
                value, source_text, threshold=0.2
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
        return " ".join(value.split()).strip()

    def _label_is_safe(self, value: str, source_text: str) -> bool:
        return not self._unsupported_numbers(
            value, source_text
        ) and not self._unsupported_technologies(
            value, source_text
        ) and not self._unsupported_characteristics(
            value, source_text
        ) and not self._unsupported_actions(value, source_text)

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

    def _ensure_non_functional_requirements(
        self,
        values: list[str],
        actors: list[Actor],
        entities: list[DomainEntityHint],
        workflows: list[DomainWorkflowHint],
    ) -> list[str]:
        requirements = self._dedupe(values)
        workflow_names = " and ".join(workflow.name for workflow in workflows[:2])
        entity_names = ", ".join(entity.name for entity in entities[:3])
        actor_names = ", ".join(actor.name for actor in actors[:3])
        candidates = [
            (
                f"Preserve consistent domain state across {workflow_names} workflows."
                if workflow_names
                else "Preserve consistent domain state across confirmed workflows."
            ),
            (
                f"Enforce authorization boundaries for {actor_names} according to their confirmed responsibilities."
                if actor_names
                else "Enforce authorization boundaries according to confirmed actor responsibilities."
            ),
            (
                f"Validate changes to {entity_names} without leaving partial updates."
                if entity_names
                else "Validate state changes without leaving partial updates."
            ),
        ]
        for candidate in candidates:
            if len(requirements) >= 2:
                break
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
        actor = re.escape(self._normalize_token(name.casefold()))
        normalized_source = " ".join(
            self._normalize_token(token)
            for token in re.findall(r"[a-z][a-z0-9-]+", source_text.casefold())
        )
        passive_reference = re.search(
            rf"\b(?:browse|choose|find|search|see|select|view)\s+(?:available\s+)?{actor}\b",
            normalized_source,
        )
        explicit_action = re.search(
            rf"\b{actor}\s+(?:can|may|must|should|will|approve|book|cancel|create|enter|manage|monitor|operate|provide|record|reschedule|review|submit|update|use)(?:s|d|ed|ing)?\b",
            normalized_source,
        )
        return not passive_reference or explicit_action is not None

    def _actor_description(self, name: str, functional: list[str]) -> str:
        for requirement in functional:
            if self._clause_coverage(name, requirement) > 0:
                return requirement
        return "Responsibilities require clarification."

    def _build_workflow_hints(
        self,
        names: list[str],
        functional: list[str],
        actors: list[Actor],
        entities: list[DomainEntityHint],
        source_text: str,
    ) -> list[DomainWorkflowHint]:
        candidate_names = [
            name.strip()
            for name in names
            if name.strip()
            and self._label_is_safe(name, source_text)
            and self._has_meaningful_overlap(name, source_text)
        ]
        for requirement in functional:
            if len(candidate_names) >= 2:
                break
            name = re.sub(
                r"^[A-Za-z][A-Za-z ]{0,40}\s+(?:can|must|should|will)\s+",
                "",
                requirement.rstrip("."),
                flags=re.IGNORECASE,
            )
            candidate_names.append(" ".join(name.split()[:8]).title())

        workflows: list[DomainWorkflowHint] = []
        for name in self._dedupe(candidate_names):
            matching_requirement = max(
                functional,
                key=lambda requirement: self._clause_coverage(name, requirement),
            )
            actor = next(
                (
                    item
                    for item in actors
                    if self._clause_coverage(item.name, matching_requirement) > 0
                ),
                actors[0] if actors else None,
            )
            if actor is None:
                continue
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
                    primary_actor=actor.name,
                    related_entities=related_entities,
                )
            )
        return self._dedupe_workflows(workflows)

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            key = value.casefold()
            if key not in seen:
                deduped.append(value)
                seen.add(key)
        return deduped

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
