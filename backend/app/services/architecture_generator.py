import logging
import re

from pydantic import BaseModel, Field, ValidationError

from app.schemas.domain import ArchitectureComponent, ArchitectureOption, RequirementModel
from app.services.ai.client import OllamaStructuredClient

logger = logging.getLogger(__name__)

CATALOG_IDS = [
    "modular-monolith",
    "service-based",
    "event-driven-microservices",
    "serverless-platform",
    "hybrid-modular-serverless",
    "hybrid-event-serverless",
]


class _ArchitectureSelection(BaseModel):
    selected_ids: list[str] = Field(min_length=3, max_length=3)
    rationale: str = ""


class ArchitectureGenerator:
    def __init__(self) -> None:
        self.ai_client = OllamaStructuredClient()

    def generate(
        self,
        requirements: RequirementModel,
        answers: dict[str, str] | None = None,
        *,
        refine_with_ai: bool = False,
    ) -> list[ArchitectureOption]:
        answers = answers or {}
        deterministic = self._deterministic_shortlist(requirements, answers)
        selected_ids = self._ollama_shortlist(requirements, answers, deterministic) or deterministic
        builders = {
            "modular-monolith": lambda: self._modular_monolith(requirements),
            "service-based": lambda: self._service_based(requirements),
            "event-driven-microservices": lambda: self._event_driven_microservices(requirements),
            "serverless-platform": lambda: self._serverless(requirements, answers),
            "hybrid-modular-serverless": lambda: self._hybrid_modular_serverless(requirements, answers),
            "hybrid-event-serverless": lambda: self._hybrid_event_serverless(requirements),
        }
        options = [builders[option_id]() for option_id in selected_ids]
        if not refine_with_ai or requirements.analysis_source == "ollama-pretrained":
            return options
        refinable_fields = {"overview"}
        refinement_seed = {
            "architectures": [
                {
                    "id": item.id,
                    "name": item.name,
                    **{
                        field: getattr(item, field)
                        for field in refinable_fields
                    },
                }
                for item in options
            ]
        }
        refined = self.ai_client.refine("architecture-generation", refinement_seed)
        if refined and isinstance(refined.get("architectures"), list):
            try:
                patches = {
                    item["id"]: item
                    for item in refined["architectures"]
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                }
                return [
                    ArchitectureOption.model_validate(
                        {
                            **option.model_dump(),
                            **{
                                field: patches.get(option.id, {}).get(
                                    field,
                                    getattr(option, field),
                                )
                                for field in refinable_fields
                            },
                        }
                    )
                    for option in options
                ]
            except (KeyError, TypeError, ValueError):
                return options
        return options

    # ------------------------------------------------------------------
    # Selection: deterministic shortlist + Ollama hybrid/second opinion
    # ------------------------------------------------------------------

    def _deterministic_shortlist(
        self, requirements: RequirementModel, answers: dict[str, str]
    ) -> list[str]:
        scores = self._suitability_scores(requirements, answers)
        ranked = sorted(CATALOG_IDS, key=lambda option_id: (-scores[option_id], CATALOG_IDS.index(option_id)))
        return ranked[:3]

    def _ollama_shortlist(
        self,
        requirements: RequirementModel,
        answers: dict[str, str],
        deterministic: list[str],
    ) -> list[str] | None:
        signals = self._signals(requirements, answers)
        scores = self._suitability_scores(requirements, answers)
        try:
            result = self.ai_client.generate(
                "architecture-selection",
                {
                    "domain": requirements.domain,
                    "summary": requirements.summary,
                    "scale_profile": requirements.scale_profile,
                    "candidate_ids": CATALOG_IDS,
                    "candidates": [
                        {"id": option_id, "score": round(scores[option_id], 1)}
                        for option_id in CATALOG_IDS
                    ],
                    "deterministic_shortlist": deterministic,
                    "signals": signals,
                },
                response_schema=_ArchitectureSelection.model_json_schema(),
                num_predict=220,
                num_ctx=4096,
                minimum_timeout_seconds=60,
            )
        except Exception as exc:  # pragma: no cover - defensive; client already swallows network errors
            logger.info("Skipping Ollama architecture selection: %s", exc)
            return None
        if not result:
            return None
        try:
            selection = _ArchitectureSelection.model_validate(result)
        except ValidationError as exc:
            logger.info("Ignoring invalid Ollama architecture selection: %s", exc.errors()[0]["msg"])
            return None
        unique_ids = list(dict.fromkeys(selection.selected_ids))
        if len(unique_ids) != 3 or any(option_id not in CATALOG_IDS for option_id in unique_ids):
            return None
        if unique_ids != deterministic:
            logger.info("Ollama architecture selection adjusted shortlist to %s", unique_ids)
        return unique_ids

    def _signals(self, requirements: RequirementModel, answers: dict[str, str]) -> dict:
        text = " ".join(
            requirements.functional_requirements
            + requirements.non_functional_requirements
            + requirements.constraints
            + requirements.data_characteristics
        ).lower()
        team_size = self._parse_team_size(answers)
        regions = self._parse_int(answers.get("geographic_regions", "0"))
        latency_match = re.search(r"(?:latency|response time)[^\d]{0,20}(\d+)\s*ms", text)
        return {
            "scale_profile": requirements.scale_profile,
            "team_size": team_size or "unknown",
            "entity_count": len(requirements.domain_entities),
            "workflow_count": len(requirements.domain_workflows),
            "integration_count": len(requirements.integrations),
            "realtime_or_event_driven": any(
                marker in text
                for marker in ("realtime", "real-time", "event processing", "stream", "telemetry", "sensor")
            ),
            "strict_availability": any(
                marker in text for marker in ("99.99", "four nines", "strict availability")
            ),
            "low_latency_ms": int(latency_match.group(1)) if latency_match else None,
            "compliance_sensitive": any(
                marker in text for marker in ("audit", "compliance", "pci", "hipaa", "gdpr", "soc2", "regulated")
            ),
            "budget": (answers.get("budget") or "").lower() or "unknown",
            "regions": regions,
            "cloud": answers.get("preferred_cloud") or "unknown",
            "variable_demand": any(marker in text for marker in ("bursty", "spiky", "variable demand", "seasonal", "batch")),
        }

    def _suitability_scores(
        self, requirements: RequirementModel, answers: dict[str, str]
    ) -> dict[str, float]:
        signals = self._signals(requirements, answers)
        scores: dict[str, float] = {option_id: 50.0 for option_id in CATALOG_IDS}

        def add(option_id: str, delta: float) -> None:
            scores[option_id] += delta

        scale = signals["scale_profile"]
        if scale == "high-scale":
            add("event-driven-microservices", 18)
            add("hybrid-event-serverless", 16)
            add("serverless-platform", 10)
            add("service-based", 8)
            add("hybrid-modular-serverless", 6)
            add("modular-monolith", -15)
        elif scale == "growth-scale":
            add("service-based", 10)
            add("hybrid-modular-serverless", 10)
            add("hybrid-event-serverless", 8)
            add("event-driven-microservices", 8)
            add("serverless-platform", 6)
            add("modular-monolith", 2)
        elif scale == "startup-scale":
            add("modular-monolith", 12)
            add("hybrid-modular-serverless", 10)
            add("serverless-platform", 6)
            add("service-based", 4)
            add("hybrid-event-serverless", -6)
            add("event-driven-microservices", -10)
        else:  # unknown scale favours reversible, low-regret shapes
            add("modular-monolith", 4)
            add("hybrid-modular-serverless", 4)
            add("service-based", 2)

        team = signals["team_size"]
        if isinstance(team, int):
            if team <= 6:
                add("modular-monolith", 10)
                add("hybrid-modular-serverless", 8)
                add("serverless-platform", 4)
                add("service-based", -2)
                add("hybrid-event-serverless", -10)
                add("event-driven-microservices", -14)
            elif team <= 12:
                add("service-based", 8)
                add("hybrid-modular-serverless", 6)
                add("hybrid-event-serverless", 6)
                add("event-driven-microservices", 4)
                add("modular-monolith", -2)
            else:
                add("event-driven-microservices", 12)
                add("hybrid-event-serverless", 10)
                add("service-based", 6)
                add("hybrid-modular-serverless", -2)
                add("modular-monolith", -8)

        if signals["realtime_or_event_driven"]:
            add("event-driven-microservices", 12)
            add("hybrid-event-serverless", 12)
            add("serverless-platform", 6)
            add("service-based", 4)
            add("hybrid-modular-serverless", 4)
            add("modular-monolith", -6)

        if signals["strict_availability"]:
            add("event-driven-microservices", 8)
            add("hybrid-event-serverless", 8)
            add("serverless-platform", 6)
            add("hybrid-modular-serverless", 4)
            add("service-based", 2)
            add("modular-monolith", -10)

        low_latency = signals["low_latency_ms"]
        if isinstance(low_latency, int) and low_latency <= 100:
            add("modular-monolith", 6)
            add("service-based", 4)
            add("hybrid-modular-serverless", 2)
            add("event-driven-microservices", -4)
            add("hybrid-event-serverless", -4)
            add("serverless-platform", -6)

        if signals["compliance_sensitive"]:
            add("modular-monolith", 4)
            add("service-based", 2)
            add("hybrid-modular-serverless", 2)
            add("event-driven-microservices", -2)
            add("hybrid-event-serverless", -2)

        budget = signals["budget"]
        if budget == "low":
            if scale == "high-scale":
                add("modular-monolith", 4)
                add("hybrid-modular-serverless", 4)
                add("serverless-platform", -4)
                add("event-driven-microservices", -10)
                add("hybrid-event-serverless", -6)
            else:
                add("modular-monolith", 8)
                add("hybrid-modular-serverless", 6)
                add("serverless-platform", 4)
                add("event-driven-microservices", -10)
                add("hybrid-event-serverless", -6)
        elif budget == "high":
            add("event-driven-microservices", 4)
            add("hybrid-event-serverless", 4)

        if isinstance(signals["regions"], int) and signals["regions"] > 1:
            add("event-driven-microservices", 8)
            add("hybrid-event-serverless", 8)
            add("serverless-platform", 8)
            add("hybrid-modular-serverless", 4)
            add("service-based", 2)
            add("modular-monolith", -10)

        cloud = str(signals["cloud"]).lower()
        if cloud in {"aws", "azure", "gcp"}:
            add("serverless-platform", 6)
            add("hybrid-event-serverless", 4)
            add("hybrid-modular-serverless", 4)
            add("event-driven-microservices", 2)
        elif cloud in {"on-premise", "on premise", "onprem", "self-hosted"}:
            add("modular-monolith", 6)
            add("service-based", 4)
            add("event-driven-microservices", -4)
            add("hybrid-event-serverless", -6)
            add("hybrid-modular-serverless", -8)
            add("serverless-platform", -12)

        if signals["entity_count"] >= 6 or signals["workflow_count"] >= 5:
            add("service-based", 6)
            add("event-driven-microservices", 6)
            add("hybrid-event-serverless", 4)
            add("hybrid-modular-serverless", -2)
            add("modular-monolith", -6)

        if signals["integration_count"] >= 3:
            add("event-driven-microservices", 6)
            add("service-based", 4)
            add("hybrid-event-serverless", 4)
            add("modular-monolith", -4)

        if signals["variable_demand"]:
            add("serverless-platform", 8)
            add("hybrid-modular-serverless", 8)
            add("hybrid-event-serverless", 6)
            add("modular-monolith", -2)

        return scores

    @staticmethod
    def _parse_team_size(answers: dict[str, str]) -> int:
        match = re.search(r"\d+", str(answers.get("team_size", "") or ""))
        return int(match.group()) if match else 0

    @staticmethod
    def _parse_int(value: str) -> int:
        match = re.search(r"\d+", str(value or ""))
        return int(match.group()) if match else 0

    def _shared_components(self, requirements: RequirementModel) -> list[ArchitectureComponent]:
        machine_markers = ("controller", "device", "instrument", "sensor")
        human_actors = [
            actor
            for actor in requirements.actors
            if not any(marker in actor.name.casefold() for marker in machine_markers)
        ]
        machine_actors = [
            actor
            for actor in requirements.actors
            if any(marker in actor.name.casefold() for marker in machine_markers)
        ]
        actors = ", ".join(actor.name for actor in human_actors[:4]) or "human roles to clarify"
        components = [
            ArchitectureComponent(
                name="User and Operator Interface",
                responsibility=f"Supports the confirmed workflows for {actors}.",
                technologies=["Web or native client (recommendation)"],
                interactions=["Invokes domain operations", "Presents workflow state"],
            ),
            ArchitectureComponent(
                name="Domain API",
                responsibility="Validates domain commands and queries while enforcing workflow invariants.",
                technologies=["Versioned HTTP or protocol adapters (recommendation)"],
                interactions=[
                    workflow.name for workflow in requirements.domain_workflows[:4]
                ] or ["Routes validated operations", "Coordinates integration boundaries"],
            ),
            ArchitectureComponent(
                name=f"{requirements.domain} Core",
                responsibility=requirements.summary,
                technologies=["Domain services (recommendation)"],
                interactions=[workflow.name for workflow in requirements.domain_workflows[:3]],
            ),
        ]
        if machine_actors:
            machine_names = ", ".join(actor.name for actor in machine_actors[:4])
            components.append(
                ArchitectureComponent(
                    name="Machine Interface Adapters",
                    responsibility=f"Validates input and commands exchanged with {machine_names}.",
                    technologies=["Device protocol adapters (recommendation)"],
                    interactions=[actor.description for actor in machine_actors[:4]],
                )
            )
        if requirements.integrations:
            components.append(
                ArchitectureComponent(
                    name="Integration Adapters",
                    responsibility="Isolates the external interfaces explicitly identified in the brief.",
                    technologies=["Protocol adapters (recommendation)"],
                    interactions=requirements.integrations[:4],
                )
            )
        return components

    def _modular_monolith(self, requirements: RequirementModel) -> ArchitectureOption:
        components = self._shared_components(requirements)
        components.extend(
            [
                ArchitectureComponent(
                    name="PostgreSQL",
                    responsibility=f"Stores transactional records for {requirements.domain}.",
                    technologies=["PostgreSQL", "JSONB"],
                    interactions=["Receives transactional writes from the domain core"],
                ),
            ]
        )
        if self._requires_event_processing(requirements):
            components.append(
                ArchitectureComponent(
                    name="Event and Background Processing",
                    responsibility="Handles justified realtime, streaming, or long-running domain work outside request threads.",
                    technologies=["Durable queue or stream (recommendation)"],
                    interactions=["Consumes domain events", "Updates durable workflow state"],
                )
            )

        return ArchitectureOption(
            id="modular-monolith",
            name="Modular Monolith",
            style="Layered / Clean Architecture",
            overview=f"A cohesive {requirements.domain} application with modules aligned to the extracted entities and workflows.",
            components=components,
            data_flow=self._data_flow(requirements),
            technology_stack=["Client appropriate to confirmed actors", "Domain API", "PostgreSQL"],
            database="Relational system of record, with additional storage selected only for confirmed data characteristics.",
            api_style="Versioned domain APIs; protocol details remain subject to integration clarification.",
            deployment="Containerized application deployed behind NGINX with horizontal replicas.",
            advantages=[
                "Lowest operational overhead while preserving strong module boundaries.",
                "Excellent fit for MVP-to-growth transitions and smaller platform teams.",
                "Simplifies transactional consistency across generated artifacts.",
            ],
            disadvantages=[
                "Fault isolation is weaker than a distributed microservice topology.",
                "Independent team scaling is limited without further decomposition.",
            ],
            suitable_scenarios=[
                "A single team needs to ship quickly with strong architectural discipline.",
                "Compliance and debugging simplicity matter more than maximum autonomy.",
            ],
            estimated_complexity="Medium",
            estimated_cost="Low to medium",
            maintenance="Straightforward with one deployment unit and clear internal contracts.",
        )

    def _service_based(self, requirements: RequirementModel) -> ArchitectureOption:
        primary_entity = (
            requirements.domain_entities[0].name if requirements.domain_entities else requirements.domain
        )
        return ArchitectureOption(
            id="service-based",
            name="Service-Based Architecture",
            style="Service-Based / Coarse Services",
            overview=f"Groups {requirements.domain} capabilities into a small number of coarse, independently deployable services sharing governed contracts.",
            components=[
                ArchitectureComponent(
                    name="Client Application",
                    responsibility="Delivers the confirmed user and operator workflows over versioned APIs.",
                    technologies=["Web client (recommendation)"],
                    interactions=[workflow.name for workflow in requirements.domain_workflows[:3]],
                ),
                ArchitectureComponent(
                    name=f"{primary_entity} Service",
                    responsibility=f"Owns the lifecycle and invariants for {primary_entity} and closely related records.",
                    technologies=["Coarse domain service"],
                    interactions=["Enforces transactional boundaries", "Exposes versioned service APIs"],
                ),
                ArchitectureComponent(
                    name="Workflow Service",
                    responsibility="Coordinates the cross-entity workflows identified in the requirement extraction.",
                    technologies=["Domain service", "Background jobs"],
                    interactions=[workflow.name for workflow in requirements.domain_workflows[:3]],
                ),
                ArchitectureComponent(
                    name="Integration Service",
                    responsibility="Owns external-system boundaries that evolve on a different release cadence from core domain logic.",
                    technologies=["Protocol adapters"],
                    interactions=requirements.integrations[:4] or ["No external integration confirmed"],
                ),
                ArchitectureComponent(
                    name="Shared Data Platform",
                    responsibility="Provides governed relational storage plus caching for the coarse services.",
                    technologies=["PostgreSQL", "Redis"],
                    interactions=["Supports service-local access patterns with shared governance"],
                ),
            ],
            data_flow=self._data_flow(requirements),
            technology_stack=["Coarse domain services", "PostgreSQL", "Redis", "Containerized deployment"],
            database="Shared relational system of record with service-scoped schemas; cache only for confirmed hot paths.",
            api_style="Versioned REST service APIs with synchronous calls for confirmed workflows.",
            deployment="Containerized coarse services behind NGINX with independent scaling per service.",
            advantages=[
                "Better fault and team isolation than a monolith without full microservices overhead.",
                "Lets hot or volatile capabilities scale and release independently.",
                "Keeps data governance simpler than fully distributed ownership.",
            ],
            disadvantages=[
                "More deployment and contract overhead than a single deployable unit.",
                "Shared data governance needs discipline to avoid cross-service coupling.",
            ],
            suitable_scenarios=[
                "A growing team needs bounded ownership before committing to microservices.",
                "Some workflows need independent scaling while most stay cohesive.",
            ],
            estimated_complexity="Medium",
            estimated_cost="Medium",
            maintenance="Moderate: a handful of deployables with shared data governance.",
        )

    def _event_driven_microservices(self, requirements: RequirementModel) -> ArchitectureOption:
        primary_entity = (
            requirements.domain_entities[0].name if requirements.domain_entities else requirements.domain
        )
        return ArchitectureOption(
            id="event-driven-microservices",
            name="Event-Driven Microservices",
            style="Microservices / Event Driven",
            overview=f"Separates {requirements.domain} workflows into independently operated services connected by durable events.",
            components=[
                ArchitectureComponent(
                    name="API Gateway",
                    responsibility="Routes external traffic to bounded-context services.",
                    technologies=["NGINX", "FastAPI gateway"],
                    interactions=["Handles authentication, rate limiting, and aggregation"],
                ),
                ArchitectureComponent(
                    name=f"{primary_entity} Service",
                    responsibility=f"Owns the lifecycle and invariants for {primary_entity}.",
                    technologies=["Independent domain service"],
                    interactions=["Publishes state changes after successful transactions"],
                ),
                ArchitectureComponent(
                    name="Workflow Coordination Service",
                    responsibility="Coordinates the cross-entity workflows identified in the requirement extraction.",
                    technologies=["Domain service", "Workflow state machine"],
                    interactions=[workflow.name for workflow in requirements.domain_workflows[:3]],
                ),
                ArchitectureComponent(
                    name="Integration Service",
                    responsibility="Owns external-system and device boundaries that require independent lifecycle management.",
                    technologies=["Protocol adapters"],
                    interactions=requirements.integrations[:4] or ["No external integration confirmed"],
                ),
                ArchitectureComponent(
                    name="Event Backbone",
                    responsibility="Decouples independently scalable domain workflows where asynchronous behavior is justified.",
                    technologies=["Kafka or Redis Streams"],
                    interactions=["Carries versioned domain events", "Supports retry and replay policies"],
                ),
                ArchitectureComponent(
                    name="Polyglot Persistence",
                    responsibility="Stores transactional state and any confirmed high-volume or binary domain data.",
                    technologies=["PostgreSQL", "Redis"],
                    interactions=["Supports service-local read/write patterns"],
                ),
            ],
            data_flow=self._data_flow(requirements, event_driven=True),
            technology_stack=["API gateway", "Domain services", "PostgreSQL", "Event backbone"],
            database="Service-owned transactional schemas; stream and object storage are recommendations only when justified.",
            api_style="REST externally, async events internally, versioned contracts between services.",
            deployment="Kubernetes-based deployment with service autoscaling and event infrastructure.",
            advantages=[
                "Best fault isolation and bounded-context autonomy.",
                "Strongest fit for high-scale workloads and parallel team ownership.",
                "Supports fine-grained incremental regeneration naturally.",
            ],
            disadvantages=[
                "Highest operational complexity and longer platform bootstrap time.",
                "Requires mature observability and contract governance.",
            ],
            suitable_scenarios=[
                "Traffic and team structure justify distributed ownership.",
                "Independent scaling and resilience are top priorities.",
            ],
            estimated_complexity="High",
            estimated_cost="High",
            maintenance="Operationally heavy but resilient when supported by platform engineering maturity.",
        )

    def _serverless(
        self, requirements: RequirementModel, answers: dict[str, str]
    ) -> ArchitectureOption:
        cloud = answers.get("preferred_cloud")
        if not cloud or cloud.casefold() == "no preference":
            cloud = "a suitable hosting platform"
        return ArchitectureOption(
            id="serverless-platform",
            name="Serverless Platform",
            style="Serverless / Managed Services",
            overview=f"Implements bounded {requirements.domain} operations with managed compute and workflow services.",
            components=[
                ArchitectureComponent(
                    name="Static Web App",
                    responsibility="Delivers the confirmed user and operator interactions.",
                    technologies=["Vite build", "CDN", "Object storage"],
                    interactions=["Calls managed API endpoints over HTTPS"],
                ),
                ArchitectureComponent(
                    name="Managed API",
                    responsibility="Runs stateless domain commands and queries behind managed endpoints.",
                    technologies=["Serverless functions", "API Gateway"],
                    interactions=[workflow.name for workflow in requirements.domain_workflows[:3]],
                ),
                ArchitectureComponent(
                    name="Workflow Orchestrator",
                    responsibility="Coordinates long-running or asynchronous domain workflows.",
                    technologies=["Managed workflow engine", "Event bus"],
                    interactions=["Tracks durable workflow state", "Invokes integration adapters"],
                ),
                ArchitectureComponent(
                    name="Managed Data Layer",
                    responsibility="Persists core relational data and cached projections.",
                    technologies=["Managed PostgreSQL", "Managed Redis"],
                    interactions=["Supports autoscaling reads and transactional writes"],
                ),
            ],
            data_flow=self._data_flow(requirements, event_driven=True),
            technology_stack=["Managed API", "Serverless functions", "Managed relational storage", "Managed workflow service"],
            database="Managed relational storage plus object storage only when confirmed data characteristics require it.",
            api_style="REST backed by function endpoints and event-triggered background tasks.",
            deployment=f"Cloud-native deployment on {cloud} with managed autoscaling and CDN edge delivery.",
            advantages=[
                "Reduces baseline infrastructure overhead and simplifies elastic scaling.",
                "Strong fit for spiky workloads and lean operations teams.",
                "Managed services accelerate compliance and disaster recovery baselines.",
            ],
            disadvantages=[
                "Vendor coupling and cold-start behavior need active mitigation.",
                "Complex local debugging compared with a monolith.",
            ],
            suitable_scenarios=[
                "Teams want fast operational leverage with managed services.",
                "Traffic is bursty and cost should track real usage closely.",
            ],
            estimated_complexity="Medium to high",
            estimated_cost="Usage-based medium",
            maintenance="Moderate, with less infra maintenance but more vendor-specific architecture decisions.",
        )

    def _hybrid_modular_serverless(
        self, requirements: RequirementModel, answers: dict[str, str]
    ) -> ArchitectureOption:
        cloud = answers.get("preferred_cloud")
        if not cloud or cloud.casefold() == "no preference":
            cloud = "a suitable hosting platform"
        components = self._shared_components(requirements)
        components.extend(
            [
                ArchitectureComponent(
                    name="PostgreSQL Core",
                    responsibility=f"Stores transactional records for {requirements.domain} inside the cohesive core.",
                    technologies=["PostgreSQL", "JSONB"],
                    interactions=["Receives transactional writes from the domain core"],
                ),
                ArchitectureComponent(
                    name="Serverless Task Handlers",
                    responsibility="Runs bursty, scheduled, or long-running slices outside the core request path.",
                    technologies=["Serverless functions", "Managed queue"],
                    interactions=["Consumes core domain events", "Writes back validated results"],
                ),
            ]
        )
        return ArchitectureOption(
            id="hybrid-modular-serverless",
            name="Hybrid: Modular Core + Serverless Edge",
            style="Hybrid / Modular Monolith + Serverless",
            overview=f"Keeps a cohesive {requirements.domain} core for transactional workflows while offloading variable or asynchronous slices to serverless handlers.",
            components=components,
            data_flow=[*self._data_flow(requirements), "Variable slices publish events that serverless handlers process independently."],
            technology_stack=["Modular core service", "PostgreSQL", "Serverless functions", "Managed queue"],
            database="Relational core remains the system of record; serverless handlers use idempotent writes and retries.",
            api_style="Versioned domain APIs for the core plus event-triggered function endpoints at the edge.",
            deployment=f"Containerized core behind NGINX plus function deployments on {cloud} with shared observability.",
            advantages=[
                "Keeps transactional simplicity while absorbing spikes without over-provisioning the core.",
                "Lets a small team adopt serverless selectively instead of all at once.",
                "Isolates failure and scaling of variable workloads from the core path.",
            ],
            disadvantages=[
                "Two operational models need shared contracts and tracing.",
                "Idempotency and retry design become mandatory at the core-edge boundary.",
            ],
            suitable_scenarios=[
                "Most workflows are transactional but some are bursty, scheduled, or long-running.",
                "A lean team needs elastic capacity without full distributed ownership.",
            ],
            estimated_complexity="Medium",
            estimated_cost="Low to medium, tracking edge usage",
            maintenance="Moderate: one core deployable plus small independently versioned functions.",
        )

    def _hybrid_event_serverless(self, requirements: RequirementModel) -> ArchitectureOption:
        primary_entity = (
            requirements.domain_entities[0].name if requirements.domain_entities else requirements.domain
        )
        return ArchitectureOption(
            id="hybrid-event-serverless",
            name="Hybrid: Event-Driven Services + Serverless",
            style="Hybrid / Event-Driven + Serverless",
            overview=f"Combines coarse {requirements.domain} services for stable domains with serverless consumers for event-heavy or variable workloads.",
            components=[
                ArchitectureComponent(
                    name="API Gateway",
                    responsibility="Routes external traffic to stable domain services and managed endpoints.",
                    technologies=["NGINX", "Managed API gateway"],
                    interactions=["Handles authentication, rate limiting, and aggregation"],
                ),
                ArchitectureComponent(
                    name=f"{primary_entity} Service",
                    responsibility=f"Owns the lifecycle and invariants for {primary_entity} as a stable deployable service.",
                    technologies=["Coarse domain service"],
                    interactions=["Publishes versioned domain events after successful transactions"],
                ),
                ArchitectureComponent(
                    name="Workflow Service",
                    responsibility="Coordinates the cross-entity workflows identified in the requirement extraction.",
                    technologies=["Domain service", "Workflow state machine"],
                    interactions=[workflow.name for workflow in requirements.domain_workflows[:3]],
                ),
                ArchitectureComponent(
                    name="Event Backbone",
                    responsibility="Decouples stable services from variable consumers with replayable streams.",
                    technologies=["Kafka or managed event bus"],
                    interactions=["Carries versioned domain events", "Supports retry and replay policies"],
                ),
                ArchitectureComponent(
                    name="Serverless Event Consumers",
                    responsibility="Scales variable or bursty reactions to domain events without standing capacity.",
                    technologies=["Serverless functions", "Managed workflow engine"],
                    interactions=["Consumes domain events idempotently", "Invokes integration adapters"],
                ),
                ArchitectureComponent(
                    name="Polyglot Persistence",
                    responsibility="Stores transactional state plus projections needed by event consumers.",
                    technologies=["PostgreSQL", "Redis"],
                    interactions=["Supports service-local and consumer read patterns"],
                ),
            ],
            data_flow=self._data_flow(requirements, event_driven=True),
            technology_stack=["Coarse domain services", "Event backbone", "Serverless consumers", "PostgreSQL"],
            database="Service-owned transactional schemas plus consumer projections; streams carry only versioned facts.",
            api_style="REST externally, async versioned events internally, functions for variable consumers.",
            deployment="Containerized services with autoscaling plus managed function deployments sharing one event bus.",
            advantages=[
                "Isolates variable workloads elastically while keeping stable domains operable.",
                "Better cost tracking for spiky consumers than standing service capacity.",
                "Preserves event replay and independent evolution of consumers.",
            ],
            disadvantages=[
                "Event contracts, idempotency, and observability span two compute models.",
                "Cold starts and retry storms need explicit budgets and alerts.",
            ],
            suitable_scenarios=[
                "Core domains are stable but reactions to their events are bursty or experimental.",
                "The team can own a few services plus small functions but not a full microservice estate.",
            ],
            estimated_complexity="Medium to high",
            estimated_cost="Medium, with usage-based consumer spend",
            maintenance="Moderate to heavy: fewer services than microservices, but event governance remains mandatory.",
        )

    def _data_flow(
        self, requirements: RequirementModel, event_driven: bool = False
    ) -> list[str]:
        flows: list[str] = []
        for workflow in requirements.domain_workflows[:3]:
            mode = "publishes a durable event after" if event_driven else "processes"
            flows.append(
                f"{workflow.primary_actor} {mode} {workflow.name.lower()}, involving "
                f"{', '.join(workflow.related_entities) or 'the confirmed domain records'}."
            )
        if requirements.integrations:
            flows.append(
                "Integration adapters exchange validated data with: "
                + ", ".join(requirements.integrations[:4])
                + "."
            )
        return flows or ["The domain flow remains provisional until workflow questions are answered."]

    def _requires_event_processing(self, requirements: RequirementModel) -> bool:
        text = " ".join(
            requirements.functional_requirements
            + requirements.non_functional_requirements
            + requirements.data_characteristics
        ).lower()
        return any(
            token in text
            for token in (
                "as they arrive", "event", "immediate", "real-time", "realtime", "sensor",
                "stream", "telemetry",
            )
        )
