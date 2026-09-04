from app.schemas.domain import ArchitectureComponent, ArchitectureOption, RequirementModel
from app.services.ai.client import OllamaStructuredClient


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
        options = [
            self._modular_monolith(requirements),
            self._event_driven_microservices(requirements),
            self._serverless(requirements, answers),
        ]
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

    def _shared_components(self, requirements: RequirementModel) -> list[ArchitectureComponent]:
        actors = ", ".join(actor.name for actor in requirements.actors[:4]) or "actors to clarify"
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
                interactions=["Routes validated operations", "Coordinates integration boundaries"],
            ),
            ArchitectureComponent(
                name=f"{requirements.domain} Core",
                responsibility=requirements.summary,
                technologies=["Domain services (recommendation)"],
                interactions=[workflow.name for workflow in requirements.domain_workflows[:3]],
            ),
        ]
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

