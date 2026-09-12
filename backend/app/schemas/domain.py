import base64
import binascii
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CURRENT_REQUIREMENT_MODEL_VERSION = "evidence-owned-domain-model-v3"


CausalNodeType = Literal[
    "user_requirement",
    "functional_requirement",
    "non_functional_requirement",
    "constraint",
    "assumption",
    "technical_characteristic",
    "architecture_decision",
    "architecture_component",
    "service_module",
    "api",
    "database_entity",
    "integration",
    "infrastructure",
    "risk",
    "cost",
    "adr",
    "diagram",
]

CausalRelationshipType = Literal[
    "requires",
    "satisfies",
    "caused_by",
    "implemented_by",
    "depends_on",
    "stores_in",
    "exposed_by",
    "deployed_on",
    "mitigates",
    "constrained_by",
    "affects",
]


class CausalGraphNode(BaseModel):
    id: str
    type: CausalNodeType
    name: str
    description: str
    source: str
    version: str = "1"
    confidence: float | None = Field(default=None, ge=0, le=1)
    metadata: dict = Field(default_factory=dict)


class CausalGraphEdge(BaseModel):
    id: str
    source_node_id: str
    target_node_id: str
    relationship: CausalRelationshipType
    reason: str
    confidence: float | None = Field(default=None, ge=0, le=1)


class CausalGraph(BaseModel):
    version: str = "1"
    nodes: list[CausalGraphNode] = Field(default_factory=list)
    edges: list[CausalGraphEdge] = Field(default_factory=list)
    orphan_node_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph_integrity(self):
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Causal graph node IDs must be unique")

        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("Causal graph edge IDs must be unique")

        known_nodes = set(node_ids)
        for edge in self.edges:
            if edge.source_node_id not in known_nodes or edge.target_node_id not in known_nodes:
                raise ValueError(f"Causal graph edge {edge.id} references an unknown node")
            if edge.source_node_id == edge.target_node_id:
                raise ValueError(f"Causal graph edge {edge.id} cannot reference itself")

        if not set(self.orphan_node_ids).issubset(known_nodes):
            raise ValueError("Causal graph orphan IDs must reference graph nodes")
        return self


class CausalGraphTrace(BaseModel):
    selected_node: CausalGraphNode
    why_it_exists: list[str] = Field(default_factory=list)
    requirements: list[CausalGraphNode] = Field(default_factory=list)
    upstream: list[CausalGraphNode] = Field(default_factory=list)
    downstream: list[CausalGraphNode] = Field(default_factory=list)
    related_adrs: list[CausalGraphNode] = Field(default_factory=list)
    affected_artifacts: list[str] = Field(default_factory=list)


EvidenceStatus = Literal["confirmed", "inferred", "assumed", "user-edited"]


class SourceEvidence(BaseModel):
    """Traceable origin for a generated or user-confirmed fact."""

    source_id: str
    source: str
    status: EvidenceStatus = "inferred"
    excerpt: str | None = None


class StructuredClarification(BaseModel):
    question_id: str
    category: str
    answer: str
    status: EvidenceStatus = "confirmed"
    source_evidence: list[SourceEvidence] = Field(default_factory=list)
    downstream_consumers: list[str] = Field(default_factory=list)


class IntegrationDetail(BaseModel):
    id: str
    name: str
    integration_type: str = "external-system"
    purpose: str
    external_owner: str | None = "external"
    protocol: list[str] = Field(default_factory=list)
    data_formats: list[str] = Field(default_factory=list)
    interaction_mode: Literal["synchronous", "asynchronous", "batch", "unknown"] = "unknown"
    security_mechanisms: list[str] = Field(default_factory=list)
    reliability_requirements: list[str] = Field(default_factory=list)
    bounded_context: str | None = None
    source_evidence: list[SourceEvidence] = Field(default_factory=list)


class TechnicalCharacteristic(BaseModel):
    id: str
    category: str
    value: str
    status: EvidenceStatus = "inferred"
    source_evidence: list[SourceEvidence] = Field(default_factory=list)


class SecurityModel(BaseModel):
    human_authentication: list[str] = Field(default_factory=list)
    service_authentication: list[str] = Field(default_factory=list)
    partner_authentication: list[str] = Field(default_factory=list)
    authorization: list[str] = Field(default_factory=list)
    data_protection: list[str] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)


class ProjectProfile(BaseModel):
    classification: str = "unknown"
    team_size: int | None = Field(default=None, ge=1)
    concurrent_users: int | None = Field(default=None, ge=1)
    event_volume_per_day: int | None = Field(default=None, ge=1)
    geographic_scope: str = "unknown"
    criticality: str = "unknown"
    integration_complexity: str = "unknown"
    availability_target_percent: float | None = Field(default=None, ge=90, le=100)
    workload_variability: str = "unknown"
    data_complexity: str = "unknown"
    regulatory_sensitivity: str = "unknown"
    source_evidence: list[SourceEvidence] = Field(default_factory=list)


class ConfidenceReport(BaseModel):
    input_completeness: int = Field(default=0, ge=0, le=100)
    inference_confidence: int = Field(default=0, ge=0, le=100)
    architecture_confidence: int = Field(default=0, ge=0, le=100)
    rationale: list[str] = Field(default_factory=list)


class Actor(BaseModel):
    id: str | None = None
    name: str
    description: str
    actor_type: Literal[
        "human", "organizational", "external-partner", "external-system",
        "device", "event-source", "machine", "unknown",
    ] = "unknown"
    responsibilities: list[str] = Field(default_factory=list)
    owning_boundary: str | None = None
    permissions: list[str] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)


class DomainEntityHint(BaseModel):
    id: str | None = None
    name: str
    description: str
    attributes: list[str] = Field(default_factory=list)
    bounded_context: str | None = None
    lifecycle_fields: list[str] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)


class DomainWorkflowHint(BaseModel):
    name: str
    description: str
    primary_actor: str
    related_entities: list[str] = Field(default_factory=list)


class BoundedContext(BaseModel):
    id: str
    name: str
    responsibilities: list[str] = Field(default_factory=list)
    owned_entities: list[str] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)


class RequirementModel(BaseModel):
    requirement_model_version: str = CURRENT_REQUIREMENT_MODEL_VERSION
    summary: str
    domain: str
    scale_profile: str
    functional_requirements: list[str] = Field(default_factory=list)
    non_functional_requirements: list[str] = Field(default_factory=list)
    actors: list[Actor] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    domain_entities: list[DomainEntityHint] = Field(default_factory=list)
    domain_workflows: list[DomainWorkflowHint] = Field(default_factory=list)
    bounded_contexts: list[BoundedContext] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)
    data_characteristics: list[str] = Field(default_factory=list)
    clarification_answers: list[StructuredClarification] = Field(default_factory=list)
    integration_details: list[IntegrationDetail] = Field(default_factory=list)
    technical_characteristics: list[TechnicalCharacteristic] = Field(default_factory=list)
    security_model: SecurityModel = Field(default_factory=SecurityModel)
    project_profile: ProjectProfile = Field(default_factory=ProjectProfile)
    confidence: ConfidenceReport = Field(default_factory=ConfidenceReport)
    open_questions: list[str] = Field(default_factory=list)
    analysis_source: Literal[
        "predefined-blueprint", "ollama-pretrained", "deterministic-extraction",
        "conservative-fallback", "legacy",
    ] = "legacy"
    analysis_warnings: list[str] = Field(default_factory=list)


class ClarificationQuestion(BaseModel):
    key: str
    category: str
    question: str
    rationale: str
    priority: str
    options: list[str] = Field(default_factory=list)


class ClarificationPlan(BaseModel):
    completeness_score: int
    missing_areas: list[str] = Field(default_factory=list)
    questions: list[ClarificationQuestion] = Field(default_factory=list)


class ArchitectureComponent(BaseModel):
    name: str
    responsibility: str
    technologies: list[str] = Field(default_factory=list)
    interactions: list[str] = Field(default_factory=list)
    # Exact component names this component needs at runtime. Blast-radius
    # analysis follows these edges instead of generic architecture-role maps.
    dependencies: list[str] = Field(default_factory=list)


class ArchitectureOption(BaseModel):
    id: str
    name: str
    style: str
    overview: str
    components: list[ArchitectureComponent] = Field(default_factory=list)
    data_flow: list[str] = Field(default_factory=list)
    technology_stack: list[str] = Field(default_factory=list)
    database: str
    api_style: str
    deployment: str
    advantages: list[str] = Field(default_factory=list)
    disadvantages: list[str] = Field(default_factory=list)
    suitable_scenarios: list[str] = Field(default_factory=list)
    estimated_complexity: str
    estimated_cost: str
    maintenance: str


ArchitecturePatchKind = Literal[
    "add_component",
    "update_component",
    "remove_component",
    "replace_text",
    "set_field",
]
ArchitecturePatchField = Literal[
    "overview",
    "database",
    "api_style",
    "deployment",
    "estimated_complexity",
    "estimated_cost",
    "maintenance",
]


class ArchitecturePatchOperation(BaseModel):
    """A small, validated change to one existing architecture option."""

    model_config = ConfigDict(extra="forbid")

    operation: ArchitecturePatchKind
    component_name: str | None = Field(default=None, max_length=120)
    component: ArchitectureComponent | None = None
    field: ArchitecturePatchField | None = None
    from_value: str | None = Field(default=None, max_length=200)
    to_value: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_operation_shape(self):
        if self.operation == "add_component" and self.component is None:
            raise ValueError("component is required when adding a component")
        if self.operation == "update_component" and (
            not self.component_name or self.component is None
        ):
            raise ValueError(
                "component_name and component are required when updating a component"
            )
        if self.operation == "remove_component" and not self.component_name:
            raise ValueError("component_name is required when removing a component")
        if self.operation == "replace_text" and (
            not self.from_value or not self.to_value
        ):
            raise ValueError("from_value and to_value are required for text replacement")
        if self.operation == "set_field" and (not self.field or not self.to_value):
            raise ValueError("field and to_value are required when setting a field")
        return self


class ArchitectureRequirementAddition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: Literal[
        "functional_requirement",
        "non_functional_requirement",
        "constraint",
        "assumption",
    ]
    text: str = Field(min_length=3, max_length=500)


class ArchitectureChatHistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=3000)


class ArchitectureChatImage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    media_type: Literal["image/jpeg", "image/png", "image/webp"]
    data: str = Field(min_length=16, max_length=5_600_000)

    @field_validator("data")
    @classmethod
    def validate_image_data(cls, value: str) -> str:
        try:
            decoded = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Image data must be valid base64") from exc
        if len(decoded) > 4 * 1024 * 1024:
            raise ValueError("Images must be 4 MB or smaller")
        return value

    @model_validator(mode="after")
    def validate_image_signature(self):
        decoded = base64.b64decode(self.data)
        valid_signature = {
            "image/png": decoded.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": decoded.startswith(b"\xff\xd8\xff"),
            "image/webp": decoded.startswith(b"RIFF") and decoded[8:12] == b"WEBP",
        }[self.media_type]
        if not valid_signature:
            raise ValueError("Image content does not match its media type")
        return self


class ArchitectureChangeProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    architecture_id: str
    base_updated_at: datetime
    request: str
    summary: str
    reasoning: str
    architecture_changes: list[ArchitecturePatchOperation] = Field(
        default_factory=list, max_length=8
    )
    requirement_additions: list[ArchitectureRequirementAddition] = Field(
        default_factory=list, max_length=4
    )
    affected_components: list[str] = Field(default_factory=list, max_length=12)
    tradeoffs: list[str] = Field(default_factory=list, max_length=8)
    risk_level: Literal["low", "medium", "high"]
    auto_apply_safe: bool = False

    @model_validator(mode="after")
    def validate_has_change(self):
        if not self.architecture_changes and not self.requirement_additions:
            raise ValueError("An architecture change proposal must contain a change")
        return self


class ArchitectureChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=3000)
    architecture_id: str | None = Field(default=None, max_length=120)
    history: list[ArchitectureChatHistoryMessage] = Field(
        default_factory=list, max_length=12
    )
    images: list[ArchitectureChatImage] = Field(default_factory=list, max_length=1)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        message = " ".join(value.split()).strip()
        if not message:
            raise ValueError("Message cannot be empty")
        return message


class ArchitectureChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["question", "architecture_change"]
    answer: str
    affected_components: list[str] = Field(default_factory=list, max_length=12)
    recommendations: list[str] = Field(default_factory=list, max_length=8)
    proposal: ArchitectureChangeProposal | None = None

    @model_validator(mode="after")
    def validate_response_shape(self):
        if self.type == "architecture_change" and self.proposal is None:
            raise ValueError("A change response must include a proposal")
        if self.type == "question" and self.proposal is not None:
            raise ValueError("An informational response cannot include a proposal")
        return self


class ArchitectureChatApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal: ArchitectureChangeProposal


RiskSeverity = Literal["critical", "high", "medium", "low", "informational"]
RiskCategory = Literal[
    "reliability",
    "scalability",
    "security",
    "performance",
    "data",
    "cost",
    "operations",
    "compliance",
    "architecture_complexity",
    "resilience",
]


class ArchitectureRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str = Field(min_length=3, max_length=140)
    category: RiskCategory
    severity: RiskSeverity
    description: str = Field(min_length=3, max_length=1000)
    evidence: str = Field(min_length=3, max_length=1000)
    affected_components: list[str] = Field(default_factory=list, max_length=12)
    impact: str = Field(min_length=3, max_length=1000)
    recommendation: str = Field(min_length=3, max_length=1000)
    confidence: float = Field(ge=0, le=1)
    needs_verification: bool = False
    related_node_ids: list[str] = Field(default_factory=list, max_length=20)


class ArchitectureRiskSummary(BaseModel):
    critical: int = Field(default=0, ge=0)
    high: int = Field(default=0, ge=0)
    medium: int = Field(default=0, ge=0)
    low: int = Field(default=0, ge=0)
    informational: int = Field(default=0, ge=0)


class ArchitectureRiskAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    architecture_id: str
    analyzed_workspace_updated_at: datetime
    overall_risk: RiskSeverity
    overview: str
    summary: ArchitectureRiskSummary
    risks: list[ArchitectureRisk] = Field(default_factory=list, max_length=30)


class ArchitectureRiskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    architecture_id: str | None = Field(default=None, max_length=120)
    include_ai: bool = False


class MetricScore(BaseModel):
    metric: str
    score: int
    direction: Literal["maximize", "minimize"] = "maximize"
    normalized_score: float | None = Field(default=None, ge=0, le=10)
    explanation: str
    weight: float | None = None
    contribution: float | None = None
    requirement_signals: list[str] = Field(default_factory=list)


class ArchitectureScorecard(BaseModel):
    architecture_id: str
    architecture_name: str
    overall_score: float
    weighted_score: float
    ranking_score: float | None = None
    metric_scores: list[MetricScore] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    decision_model: str = "deterministic score produced by the decision model"


class ComparisonResult(BaseModel):
    weights: dict[str, float] = Field(default_factory=dict)
    scorecards: list[ArchitectureScorecard] = Field(default_factory=list)
    reasoning: list[str] = Field(default_factory=list)


class RecommendationResult(BaseModel):
    recommended_architecture_id: str
    recommended_architecture_name: str
    decision_summary: str
    why: list[str] = Field(default_factory=list)
    why_not: dict[str, list[str]] = Field(default_factory=dict)
    rollout_plan: list[str] = Field(default_factory=list)
    confidence: str


class DiagramArtifact(BaseModel):
    title: str
    description: str
    mermaid: str
    plantuml: str


class DatabaseField(BaseModel):
    name: str
    data_type: str
    nullable: bool = False
    indexed: bool = False
    description: str
    source_evidence: list[SourceEvidence] = Field(default_factory=list)


class DatabaseEntity(BaseModel):
    id: str | None = None
    name: str
    description: str
    fields: list[DatabaseField] = Field(default_factory=list)
    bounded_context: str | None = None
    source_evidence: list[SourceEvidence] = Field(default_factory=list)


class DatabaseRelationship(BaseModel):
    source: str
    target: str
    relationship: str
    description: str
    cardinality: str | None = None
    foreign_key: str | None = None
    ownership_implication: str | None = None
    source_evidence: list[SourceEvidence] = Field(default_factory=list)


class DatabaseDesign(BaseModel):
    database_engine: str
    entities: list[DatabaseEntity] = Field(default_factory=list)
    relationships: list[DatabaseRelationship] = Field(default_factory=list)
    indexes: list[str] = Field(default_factory=list)
    normalization_notes: list[str] = Field(default_factory=list)
    sql_schema: str
    sample_inserts: str


class ApiEndpoint(BaseModel):
    method: str
    path: str
    purpose: str
    auth_required: bool | None
    request_description: str = ""
    response_description: str = ""
    service: str | None = None
    requirement_ids: list[str] = Field(default_factory=list)
    request_example: dict = Field(default_factory=dict)
    response_example: dict = Field(default_factory=dict)
    group: str | None = None
    resource: str | None = None
    operation_type: Literal["command", "query", "event", "unknown"] = "unknown"
    owner: str | None = None
    security_mechanisms: list[str] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)
    # Event-contract semantics (populated only for operation_type == "event").
    producer: str | None = None
    consumers: list[str] = Field(default_factory=list)
    delivery_semantics: str | None = None
    ordering_key: str | None = None


class ApiGroup(BaseModel):
    name: str
    description: str
    endpoints: list[ApiEndpoint] = Field(default_factory=list)


class ApiDesign(BaseModel):
    style: str
    authentication_strategy: str
    groups: list[ApiGroup] = Field(default_factory=list)
    validation_rules: list[str] = Field(default_factory=list)
    openapi_summary: list[str] = Field(default_factory=list)


class DeploymentPlan(BaseModel):
    deployment_model: str
    replicas: int | None = Field(default=None, ge=1, le=1000)
    regions: list[str] = Field(default_factory=list)
    deployment_strategy: str | None = None
    availability_configuration: str | None = None
    target_stack: list[str] = Field(default_factory=list)
    docker_services: list[str] = Field(default_factory=list)
    kubernetes_modules: list[str] = Field(default_factory=list)
    cicd_pipeline: list[str] = Field(default_factory=list)
    observability: list[str] = Field(default_factory=list)
    scaling_strategy: list[str] = Field(default_factory=list)
    security_controls: list[str] = Field(default_factory=list)
    cloud_recommendation: str
    stack_rationale: list[str] = Field(default_factory=list)
    replicas_per_region: int | None = Field(default=None, ge=1, le=1000)
    total_baseline_replicas: int | None = Field(default=None, ge=1, le=100000)
    availability_target_percent: float | None = Field(default=None, ge=90, le=100)
    failover_mode: str | None = None
    rto: str | None = None
    rpo: str | None = None
    source_evidence: list[SourceEvidence] = Field(default_factory=list)


class ImpactAssessment(BaseModel):
    change_request: str
    impacted_modules: list[str] = Field(default_factory=list)
    reasoning: list[str] = Field(default_factory=list)
    regenerated_sections: list[str] = Field(default_factory=list)
    directly_affected_node_ids: list[str] = Field(default_factory=list)
    indirectly_affected_node_ids: list[str] = Field(default_factory=list)
    affected_artifacts: list[str] = Field(default_factory=list)


WorkspaceEditTarget = Literal[
    "functional_requirement",
    "non_functional_requirement",
    "actor",
    "constraint",
    "assumption",
    "integration",
    "data_characteristic",
    "domain_entity",
    "architecture_component",
    "api_endpoint",
    "database_entity",
    "deployment",
    "diagram_layout",
]
WorkspaceEditOperation = Literal["add", "update", "delete", "reorder"]
ImpactLevel = Literal["none", "minor", "moderate", "major", "visual"]


class WorkspaceEditRequest(BaseModel):
    target_type: WorkspaceEditTarget
    operation: WorkspaceEditOperation
    target_id: str | None = None
    parent_id: str | None = None
    value: str | dict[str, Any] | None = None
    destination_index: int | None = Field(default=None, ge=0)
    use_ai: bool = False
    expected_updated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_edit_shape(self):
        if self.operation in {"update", "delete", "reorder"} and not self.target_id:
            raise ValueError("target_id is required for this edit")
        if self.operation in {"add", "update"} and self.value is None:
            raise ValueError("value is required for this edit")
        if self.operation == "reorder" and self.destination_index is None:
            raise ValueError("destination_index is required when reordering")
        if self.target_type == "diagram_layout" and self.operation == "delete":
            raise ValueError("diagram layout entries are reset with an update")
        return self


class WorkspaceImpactItem(BaseModel):
    area: str
    level: ImpactLevel
    summary: str


class WorkspaceEditImpact(BaseModel):
    items: list[WorkspaceImpactItem] = Field(default_factory=list)
    directly_affected_node_ids: list[str] = Field(default_factory=list)
    indirectly_affected_node_ids: list[str] = Field(default_factory=list)
    affected_artifacts: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False


class SemanticEditSuggestion(BaseModel):
    suggested_text: str
    rationale: str
    inferred_characteristics: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    source: Literal["ollama", "deterministic-fallback"]


class WorkspaceEditPreview(BaseModel):
    edit: WorkspaceEditRequest
    normalized_value: str | dict[str, Any] | None = None
    impact: WorkspaceEditImpact
    suggestion: SemanticEditSuggestion | None = None
    warnings: list[str] = Field(default_factory=list)


class ConsistencyIssue(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    related_ids: list[str] = Field(default_factory=list)


class CriteriaWeights(BaseModel):
    """User-adjustable weights for each scoring criterion.

    Values range 0.0-3.0 where 1.0 is the neutral default.
    Used by the What-If Playground to let stakeholders explore
    how different priority emphases change the architecture ranking.
    All scoring remains deterministic and rule-based.
    """

    weights: dict[str, float] = Field(default_factory=dict)


class RequirementAnalysis(BaseModel):
    """Minimal entity analysis consumed by deterministic insight engines."""

    detected_entities: list[str] = Field(default_factory=list)


class ProjectConstraints(BaseModel):
    """Project inputs used by deterministic team and architecture-fit checks."""

    team_size: int = Field(ge=1)
    expected_scale: str = "medium"
    timeline_weeks: int = Field(default=12, ge=1)


class TeamDefinition(BaseModel):
    name: str
    member_count: int = Field(ge=1)


class RoleDefinition(BaseModel):
    role_name: str
    description: str
    suggested_percentage: float = Field(ge=0, le=1)
    min_headcount: int = Field(ge=0)
    essential: bool


class RoleRecommendation(BaseModel):
    role_name: str
    description: str
    recommended_headcount: int = Field(ge=0)
    rationale: str


class TeamFitPlan(BaseModel):
    architecture_id: str
    total_team_size: int = Field(ge=1)
    roles: list[RoleRecommendation] = Field(default_factory=list)
    coverage_warning: str | None = None


class OwnershipSuggestion(BaseModel):
    component: str
    suggested_team: str
    reason: str


class FrictionPoint(BaseModel):
    description: str
    severity: Literal["low", "medium", "high"]
    affected_components: list[str] = Field(default_factory=list)
    affected_teams: list[str] = Field(default_factory=list)


class ConwayFitResult(BaseModel):
    fit_score: float = Field(ge=0, le=10)
    team_fit_plan: TeamFitPlan
    ownership_mapping: list[OwnershipSuggestion] = Field(default_factory=list)
    friction_points: list[FrictionPoint] = Field(default_factory=list)
    summary: str


class ConwayFitRequest(BaseModel):
    architecture: ArchitectureOption
    entities: list[str] = Field(default_factory=list)
    bounded_contexts: list[BoundedContext] = Field(default_factory=list)
    constraints: ProjectConstraints


class TwinCaseStudy(BaseModel):
    id: str
    company: str
    architecture_id: str
    score_vector: dict[str, int] = Field(default_factory=dict)
    notable_services: list[str] = Field(default_factory=list)
    summary: str
    lesson: str
    source_note: str
    evidence_type: str = "public engineering summary"
    evidence_confidence: Literal["low", "medium", "high"] = "medium"
    domain_tags: list[str] = Field(default_factory=list)
    capability_tags: list[str] = Field(default_factory=list)
    workload_tags: list[str] = Field(default_factory=list)
    scale_tags: list[str] = Field(default_factory=list)
    data_tags: list[str] = Field(default_factory=list)
    reliability_tags: list[str] = Field(default_factory=list)
    integration_tags: list[str] = Field(default_factory=list)


class TwinSimilarMetric(BaseModel):
    metric: str
    user_score: int
    case_score: int
    delta: int


class TwinMatch(BaseModel):
    case_study: TwinCaseStudy
    similarity_score: float = Field(ge=0, le=100)
    overlap_services: list[str] = Field(default_factory=list)
    rationale: str
    similar_metrics: list[TwinSimilarMetric] = Field(default_factory=list)
    domain_similarity: float | None = Field(default=None, ge=0, le=100)
    capability_similarity: float | None = Field(default=None, ge=0, le=100)
    architecture_similarity: float | None = Field(default=None, ge=0, le=100)
    workload_similarity: float | None = Field(default=None, ge=0, le=100)
    scale_similarity: float | None = Field(default=None, ge=0, le=100)
    technology_similarity: float | None = Field(default=None, ge=0, le=100)
    data_similarity: float | None = Field(default=None, ge=0, le=100)
    reliability_similarity: float | None = Field(default=None, ge=0, le=100)
    integration_similarity: float | None = Field(default=None, ge=0, le=100)
    industry_similarity: float | None = Field(default=None, ge=0, le=100)
    architecture_precedent_similarity: float | None = Field(default=None, ge=0, le=100)
    technology_precedent_similarity: float | None = Field(default=None, ge=0, le=100)
    domain_compatible: bool = False
    match_strength: str = "architecture-only"
    dimension_evidence: dict[str, bool] = Field(default_factory=dict)
    evidence_notice: str = "Algorithmic similarity based on available public precedent data and selected metrics."


class TwinMatchRequest(BaseModel):
    comparison_matrix: dict[str, dict[str, int]]
    recommended_architecture_id: str
    deployment_stack: list[str] = Field(default_factory=list)
    weights: dict[str, float] | None = None
    domain: str = ""
    domain_signals: list[str] = Field(default_factory=list)
    capability_signals: list[str] = Field(default_factory=list)
    workload_signals: list[str] = Field(default_factory=list)
    data_signals: list[str] = Field(default_factory=list)
    reliability_signals: list[str] = Field(default_factory=list)
    integration_signals: list[str] = Field(default_factory=list)
    project_profile: ProjectProfile | None = None
    similarity_weights: dict[str, float] | None = None


class ArchitectureDecisionRecord(BaseModel):
    """Immutable snapshot of a single architectural decision.

    Created at initial analysis and each evolution step. The frontend
    accumulates these client-side to build the decision history timeline
    without requiring server-side storage.
    """

    id: str
    timestamp: str
    title: str
    context: str
    decision: str
    status: str = "accepted"
    consequences: str
    changed_modules: list[str] = Field(default_factory=list)


class ReweightRequest(BaseModel):
    """Lightweight payload for the What-If reweight endpoint.

    Contains the raw score matrix (architecture x criterion) and
    the user's desired weights. The server recomputes the weighted
    sum and returns re-ranked ArchitectureScorecards.
    """

    matrix: dict[str, dict[str, int]]
    weights: CriteriaWeights


class ExportAdrsRequest(BaseModel):
    """Payload for the ADR export endpoint.

    Accepts a list of ArchitectureDecisionRecords accumulated by the
    frontend and returns formatted markdown.
    """

    adrs: list[ArchitectureDecisionRecord]


class ComponentStatus(BaseModel):
    """Status of a single component after a simulated failure."""

    component: str
    role: str
    status: str  # "down" | "degraded" | "healthy"
    reason: str | None = None


class BlastRadiusResult(BaseModel):
    """Deterministic blast-radius simulation result for a component failure.

    Contains per-component status, a plain-English impact summary, and a
    severity score 0-10. All fields are computed rule-based — no LLM.
    """

    failed_component: str
    architecture_id: str
    statuses: list[ComponentStatus] = Field(default_factory=list)
    impact_summary: str
    severity_score: float


class BlastRadiusRequest(BaseModel):
    """Payload for the blast-radius simulation endpoint.

    Accepts the target architecture, the component that failed, and the
    comparison matrix (needed for the fault_isolation score).
    """

    architecture: ArchitectureOption
    failed_component: str
    comparison_matrix: dict[str, dict[str, int]]


class ResilienceRecommendation(BaseModel):
    """A single deterministic mitigation suggestion for reducing blast radius.

    Each recommendation maps to a hard-coded entry in the MITIGATION_CATALOG.
    The LLM never decides scores or recommendations — only prose descriptions.
    """

    id: str
    name: str
    category: str
    description: str
    severity_reduction: float


class ResilienceRecommendationsRequest(BaseModel):
    """Payload for the resilience-recommendations endpoint.

    Accepts a completed blast radius result and the architecture it was
    simulated against. Returns deterministic mitigation suggestions.
    """

    blast_result: BlastRadiusResult
    architecture: ArchitectureOption


class ApplyMitigationsRequest(BaseModel):
    """Payload for the blast-radius/apply-mitigations endpoint.

    Accepts a blast radius result, a list of selected mitigation IDs,
    and the architecture. Returns a modified blast radius result with
    updated statuses and reduced severity score.
    """

    blast_result: BlastRadiusResult
    selected_mitigation_ids: list[str]
    architecture: ArchitectureOption


class WorkspaceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str
    business_context: str | None = None
    preferred_cloud: str | None = None
    constraints: list[str] = Field(default_factory=list)
    team_size: int | None = Field(default=None, ge=1, le=1000)


class ProjectDescriptionAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=5000)

    @field_validator("prompt")
    @classmethod
    def validate_useful_prompt(cls, value: str) -> str:
        prompt = value.strip()
        if len(prompt) < 40 or len(prompt.split()) < 8:
            raise ValueError(
                "Describe the project in at least 40 characters and 8 words."
            )
        return prompt


class ClarificationAnswerRequest(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)


class ChangeRequest(BaseModel):
    change_request: str


CounterfactualVariable = Literal[
    "expected_users",
    "peak_traffic_multiplier",
    "availability_percent",
    "latency_ms",
    "team_size",
    "geographic_regions",
    "realtime_required",
    "compliance_level",
    "data_volume_multiplier",
    "growth_rate_percent",
]
CounterfactualValue = str | float | int | bool | None


class CounterfactualChange(BaseModel):
    variable: CounterfactualVariable
    original_value: CounterfactualValue = None
    hypothetical_value: CounterfactualValue
    source: Literal["structured", "scenario"] = "structured"


class CounterfactualSimulationRequest(BaseModel):
    scenario: str | None = Field(default=None, max_length=1000)
    changes: list[CounterfactualChange] = Field(default_factory=list, max_length=12)


class CounterfactualArchitectureRank(BaseModel):
    architecture_id: str
    architecture_name: str
    rank: int = Field(ge=1)
    suitability_score: float = Field(ge=0, le=100)
    team_fit_score: float | None = Field(default=None, ge=0, le=10)


class CounterfactualSnapshot(BaseModel):
    architecture_id: str
    architecture_name: str
    suitability_score: float = Field(ge=0, le=100)
    rank: int = Field(ge=1)
    resilience_score: float = Field(ge=0, le=10)
    risk_score: float = Field(ge=0, le=10)
    risk_level: Literal["Low", "Medium", "High"]
    team_fit_score: float | None = Field(default=None, ge=0, le=10)
    operational_complexity_score: float = Field(ge=0, le=10)


class CounterfactualSimulationResult(BaseModel):
    simulation_id: str
    workspace_id: str
    current_architecture_version: str
    scenario: str | None = None
    changed_variables: list[CounterfactualChange] = Field(default_factory=list)
    directly_affected_node_ids: list[str] = Field(default_factory=list)
    indirectly_affected_node_ids: list[str] = Field(default_factory=list)
    affected_components: list[str] = Field(default_factory=list)
    before: CounterfactualSnapshot
    after: CounterfactualSnapshot
    before_ranking: list[CounterfactualArchitectureRank] = Field(default_factory=list)
    after_ranking: list[CounterfactualArchitectureRank] = Field(default_factory=list)
    current_architecture_still_suitable: bool
    recommended_architecture_id: str
    recommended_architecture_name: str
    recommended_evolution_path: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list)
    confidence: Literal["Low", "Medium", "High"]
    estimate_notes: list[str] = Field(default_factory=list)


class WorkspaceResponse(BaseModel):
    id: str
    title: str
    original_prompt: str
    business_context: str | None = None
    answers: dict[str, str] = Field(default_factory=dict)
    requirements: RequirementModel
    clarification_plan: ClarificationPlan
    architectures: list[ArchitectureOption] = Field(default_factory=list)
    comparison: ComparisonResult
    recommendation: RecommendationResult
    diagrams: dict[str, DiagramArtifact] = Field(default_factory=dict)
    database_design: DatabaseDesign
    api_design: ApiDesign
    deployment_plan: DeploymentPlan
    documentation_markdown: str
    impact_history: list[ImpactAssessment] = Field(default_factory=list)
    adr: ArchitectureDecisionRecord | None = None
    adrs: list[ArchitectureDecisionRecord] = Field(default_factory=list)
    causal_graph: CausalGraph | None = None
    diagram_layouts: dict[str, dict[str, Any]] = Field(default_factory=dict)
    consistency_issues: list[ConsistencyIssue] = Field(default_factory=list)
    can_undo: bool = False
    can_redo: bool = False
    created_at: datetime
    updated_at: datetime


class WorkspaceMutationResponse(BaseModel):
    workspace: WorkspaceResponse
    impact: WorkspaceEditImpact
    consistency_issues: list[ConsistencyIssue] = Field(default_factory=list)
    message: str
