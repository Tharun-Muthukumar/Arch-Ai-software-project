import re
import uuid
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.schemas.domain import (
    ArchitectureChangeProposal,
    ArchitectureChatRequest,
    ArchitectureChatResponse,
    ArchitectureOption,
    ArchitecturePatchOperation,
    ArchitectureRequirementAddition,
    ArchitectureRisk,
    ArchitectureRiskAnalysis,
    ArchitectureRiskSummary,
    RiskCategory,
    RiskSeverity,
    WorkspaceResponse,
)
from app.services.ai.client import OllamaStructuredClient


class ArchitectureAssistantUnavailableError(RuntimeError):
    pass


class _ArchitectureChatAIResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["question", "architecture_change"]
    answer: str = Field(min_length=3, max_length=3000)
    summary: str | None = Field(default=None, max_length=500)
    reasoning: str | None = Field(default=None, max_length=1500)
    architecture_changes: list[ArchitecturePatchOperation] = Field(
        default_factory=list, max_length=8
    )
    requirement_additions: list[ArchitectureRequirementAddition] = Field(
        default_factory=list, max_length=4
    )
    affected_components: list[str] = Field(default_factory=list, max_length=12)
    recommendations: list[str] = Field(default_factory=list, max_length=8)
    tradeoffs: list[str] = Field(default_factory=list, max_length=8)
    risk_level: Literal["low", "medium", "high"] = "low"

    @model_validator(mode="after")
    def validate_response_shape(self):
        has_changes = bool(self.architecture_changes or self.requirement_additions)
        if self.type == "architecture_change" and not has_changes:
            raise ValueError("A change response must contain an applicable change")
        if self.type == "question" and has_changes:
            raise ValueError("An informational response cannot contain changes")
        return self


class _ArchitectureImageAIResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=3, max_length=1600)
    suggested_item: str | None = Field(default=None, max_length=500)
    affected_components: list[str] = Field(default_factory=list, max_length=8)


class _ArchitectureRiskAIItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=120)
    category: RiskCategory
    severity: RiskSeverity
    description: str = Field(min_length=3, max_length=400)
    evidence: str = Field(min_length=3, max_length=400)
    affected_components: list[str] = Field(default_factory=list, max_length=8)
    impact: str = Field(min_length=3, max_length=400)
    recommendation: str = Field(min_length=3, max_length=400)
    confidence: float = Field(ge=0, le=1)
    needs_verification: bool = False


class _ArchitectureRiskAIResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overview: str = Field(min_length=3, max_length=500)
    risks: list[_ArchitectureRiskAIItem] = Field(default_factory=list, max_length=3)


class ArchitectureAssistantService:
    """Grounded architecture discussion, controlled patches, and risk analysis."""

    _DATABASE_MARKERS = {
        "postgresql", "mysql", "mongodb", "dynamodb", "cassandra", "database",
        "relational storage", "document storage", "data store", "datastore",
    }
    _REDUNDANCY_MARKERS = {
        "replica", "replication", "failover", "multi-zone", "multi zone",
        "active-active", "active-passive", "standby", "redundant",
    }
    _OBSERVABILITY_MARKERS = {
        "observability", "monitoring", "metrics", "tracing", "logging", "telemetry",
    }
    _CONTROL_MARKER_GROUPS = (
        _REDUNDANCY_MARKERS,
        _OBSERVABILITY_MARKERS,
        {"retention", "purge", "lifecycle"},
        {"audit", "tamper-evident", "tamper evident"},
        {"backup", "recovery", "restore", "rto", "rpo"},
        {"authentication", "identity", "oauth", "oidc", "sso"},
        {"authorization", "rbac", "abac", "permission"},
        {"rate limit", "throttling", "quota"},
        {"encryption", "encrypted", "tls", "kms"},
        {"cache", "caching", "redis"},
        {"api gateway", "gateway", "ingress"},
    )
    _ABSENCE_MARKERS = {
        "absent", "missing", "no explicit", "not explicit", "not represented",
        "not integrated", "without",
    }
    _SEVERITY_ORDER: dict[RiskSeverity, int] = {
        "informational": 0,
        "low": 1,
        "medium": 2,
        "high": 3,
        "critical": 4,
    }

    def __init__(self) -> None:
        self.ai_client = OllamaStructuredClient()

    def chat(
        self, workspace: WorkspaceResponse, request: ArchitectureChatRequest
    ) -> ArchitectureChatResponse:
        architecture = self._select_architecture(workspace, request.architecture_id)
        if request.images:
            return self._chat_with_image(workspace, architecture, request)
        direct_response = self._direct_command_response(workspace, architecture, request)
        if direct_response is not None:
            return direct_response
        clarification = self._clarify_vague_quality_change(workspace, request.message)
        if clarification is not None:
            return clarification
        grounded_response = self._grounded_component_answer(architecture, request.message)
        if grounded_response is not None:
            return grounded_response
        input_data = {
            "project_id": workspace.id,
            "raw_requirement": request.message,
            "project": {
                "title": workspace.title,
                "original_prompt": workspace.original_prompt[:1200],
                "requirements": {
                    "domain": workspace.requirements.domain,
                    "functional": workspace.requirements.functional_requirements[:12],
                    "non_functional": workspace.requirements.non_functional_requirements[:6],
                    "constraints": workspace.requirements.constraints[:6],
                    "assumptions": workspace.requirements.assumptions[:6],
                    "actors": [
                        self._known_values(item.model_dump())
                        for item in workspace.requirements.actors[:8]
                    ],
                    "domain_entities": [
                        self._known_values(item.model_dump())
                        for item in workspace.requirements.domain_entities[:8]
                    ],
                    "integrations": workspace.requirements.integrations[:5],
                    "technical_characteristics": [
                        {
                            "category": item.category,
                            "value": item.value,
                            "status": item.status,
                        }
                        for item in workspace.requirements.technical_characteristics[:6]
                    ],
                    "project_profile": self._known_values(
                        workspace.requirements.project_profile.model_dump()
                    ),
                },
            },
            "current_architecture": self._compact_architecture(architecture),
            "current_deployment": self._compact_deployment(workspace),
            "conversation": [item.model_dump() for item in request.history[-8:]],
            "attached_images": [image.name for image in request.images],
        }
        raw = self.ai_client.generate(
            "architecture-chat",
            input_data,
            response_schema=_ArchitectureChatAIResult.model_json_schema(),
            num_predict=280,
            num_ctx=3072,
            timeout_seconds=60,
            model=self.ai_client.settings.ollama_assistant_model,
        )
        if raw is None:
            if request.images:
                raise ArchitectureAssistantUnavailableError(
                    "Image analysis is unavailable. Install the configured vision model "
                    f"with: ollama pull {self.ai_client.settings.ollama_vision_model}"
                )
            raise ArchitectureAssistantUnavailableError(
                "AI Assistant is currently unavailable. Verify Ollama is running and try again."
            )
        try:
            result = _ArchitectureChatAIResult.model_validate(raw)
        except ValidationError as exc:
            repaired = self._repair_explicit_replacement(request.message, architecture, raw)
            if repaired is None:
                raise ArchitectureAssistantUnavailableError(
                    "AI Assistant returned an invalid response. Please try again."
                ) from exc
            result = repaired

        known_names = {component.name.casefold(): component.name for component in architecture.components}
        if result.type == "question":
            affected = self._dedupe([
                *self._known_component_names(result.affected_components, known_names),
                *self._mentioned_component_names(result.answer, known_names),
            ])
            return ArchitectureChatResponse(
                type="question",
                answer=result.answer,
                affected_components=affected,
                recommendations=self._dedupe(result.recommendations),
            )

        changes = self._validated_patch_operations(architecture, result.architecture_changes)
        additions = self._validated_requirement_additions(
            request.message, result.requirement_additions
        )
        if not changes and not additions:
            raise ArchitectureAssistantUnavailableError(
                "AI Assistant could not produce a safe, applicable change proposal."
            )
        added_names = {
            operation.component.name.casefold(): operation.component.name
            for operation in changes
            if operation.operation == "add_component" and operation.component
        }
        affected = self._known_component_names(
            result.affected_components, {**known_names, **added_names}
        )
        affected = self._dedupe([
            *affected,
            *self._mentioned_component_names(result.answer, {**known_names, **added_names}),
        ])
        proposal = ArchitectureChangeProposal(
            proposal_id=str(uuid.uuid4()),
            architecture_id=architecture.id,
            base_updated_at=workspace.updated_at,
            request=request.message,
            summary=result.summary or result.answer,
            reasoning=result.reasoning or result.answer,
            architecture_changes=changes,
            requirement_additions=additions,
            affected_components=affected,
            tradeoffs=self._dedupe(result.tradeoffs),
            risk_level=result.risk_level,
        )
        return ArchitectureChatResponse(
            type="architecture_change",
            answer=result.answer,
            affected_components=affected,
            recommendations=self._dedupe(result.recommendations),
            proposal=proposal,
        )

    def _chat_with_image(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
    ) -> ArchitectureChatResponse:
        addition_target = self._image_addition_target(request.message)
        known_names = {
            component.name.casefold(): component.name
            for component in architecture.components
        }
        input_data = {
            "project_id": workspace.id,
            "raw_requirement": request.message,
            "requested_item_type": addition_target,
            "project": {
                "title": workspace.title,
                "domain": workspace.requirements.domain,
                "existing_constraints": workspace.requirements.constraints[:5],
                "existing_assumptions": workspace.requirements.assumptions[:5],
            },
            "component_names": list(known_names.values()),
            "conversation": [item.model_dump() for item in request.history[-4:]],
            "attached_images": [image.name for image in request.images],
        }
        raw = self.ai_client.generate(
            "architecture-image-chat",
            input_data,
            num_predict=100,
            num_ctx=3072,
            timeout_seconds=120,
            model=self.ai_client.settings.ollama_vision_model,
            images=[image.data for image in request.images],
        )
        if raw is None:
            raise ArchitectureAssistantUnavailableError(
                "Image analysis is unavailable. Install the configured vision model "
                f"with: ollama pull {self.ai_client.settings.ollama_vision_model}"
            )
        try:
            result = _ArchitectureImageAIResult.model_validate(raw)
        except ValidationError as exc:
            raise ArchitectureAssistantUnavailableError(
                "The vision model returned an invalid response. Please try a clearer image or prompt."
            ) from exc

        affected = self._known_component_names(result.affected_components, known_names)
        if addition_target is None or not result.suggested_item:
            return ArchitectureChatResponse(
                type="question",
                answer=result.answer,
                affected_components=affected,
            )

        item_text = " ".join(result.suggested_item.split()).strip(" .!?")
        if len(item_text) < 3:
            return ArchitectureChatResponse(
                type="question",
                answer=result.answer,
                affected_components=affected,
            )
        collections = {
            "functional_requirement": workspace.requirements.functional_requirements,
            "non_functional_requirement": workspace.requirements.non_functional_requirements,
            "constraint": workspace.requirements.constraints,
            "assumption": workspace.requirements.assumptions,
        }
        if any(item.casefold() == item_text.casefold() for item in collections[addition_target]):
            return ArchitectureChatResponse(
                type="question",
                answer=f"{result.answer} That project item already exists, so no duplicate was proposed.",
                affected_components=affected,
            )

        label = addition_target.replace("_", " ")
        proposal = ArchitectureChangeProposal(
            proposal_id=str(uuid.uuid4()),
            architecture_id=architecture.id,
            base_updated_at=workspace.updated_at,
            request=request.message,
            summary=f"Add image-derived {label}: {item_text}",
            reasoning=(
                "The item is derived from visible image evidence and requires user review before apply."
            ),
            requirement_additions=[
                ArchitectureRequirementAddition(target_type=addition_target, text=item_text)
            ],
            affected_components=affected,
            tradeoffs=["Confirm that the image was interpreted correctly before applying this item."],
            risk_level="medium",
            auto_apply_safe=False,
        )
        return ArchitectureChatResponse(
            type="architecture_change",
            answer=result.answer,
            affected_components=affected,
            proposal=proposal,
        )

    def apply_patch(
        self, workspace: WorkspaceResponse, proposal: ArchitectureChangeProposal
    ) -> WorkspaceResponse:
        updated = workspace.model_copy(deep=True)
        architecture = self._select_architecture(updated, proposal.architecture_id)
        for operation in proposal.architecture_changes:
            architecture = self._apply_operation(architecture, operation)
        if not architecture.components:
            raise ValueError("An architecture must retain at least one component.")
        normalized_names = [component.name.casefold() for component in architecture.components]
        if len(normalized_names) != len(set(normalized_names)):
            raise ValueError("Architecture component names must remain unique.")
        updated.architectures = [
            architecture if item.id == architecture.id else item
            for item in updated.architectures
        ]
        return updated

    def analyze_risks(
        self,
        workspace: WorkspaceResponse,
        architecture_id: str | None = None,
        *,
        include_ai: bool = False,
    ) -> ArchitectureRiskAnalysis:
        architecture = self._select_architecture(workspace, architecture_id)
        deterministic = self._deterministic_risks(workspace, architecture)
        input_data = {
            "project_id": workspace.id,
            "raw_requirement": workspace.original_prompt,
            "project_requirements": {
                "domain": workspace.requirements.domain,
                "functional": workspace.requirements.functional_requirements,
                "non_functional": workspace.requirements.non_functional_requirements,
                "constraints": workspace.requirements.constraints,
                "security": workspace.requirements.security_model.model_dump(),
                "profile": workspace.requirements.project_profile.model_dump(),
            },
            "current_architecture": self._compact_architecture(architecture),
            "deployment": self._compact_deployment(workspace),
            "deterministic_findings": [item.model_dump() for item in deterministic],
        }
        raw = None
        if include_ai:
            raw = self.ai_client.generate(
                "architecture-risk-analysis",
                input_data,
                response_schema=_ArchitectureRiskAIResult.model_json_schema(),
                num_predict=360,
                num_ctx=3072,
            )
        ai_overview = (
            "Fast structured checks completed. Run the deeper AI review for broader analysis."
        )
        ai_risks: list[ArchitectureRisk] = []
        if include_ai and raw is not None:
            try:
                parsed = _ArchitectureRiskAIResult.model_validate(raw)
                ai_overview = parsed.overview
                ai_risks = self._ground_ai_risks(workspace, architecture, parsed.risks)
            except ValidationError:
                ai_overview = (
                    "Deterministic checks completed; the AI supplement could not be validated."
                )
        elif include_ai:
            ai_overview = (
                "Deterministic checks completed; AI review was unavailable for this run."
            )

        risks = self._merge_risks([*deterministic, *ai_risks])
        risks = [risk.model_copy(update={"id": f"risk-{index:03d}"}) for index, risk in enumerate(risks, 1)]
        counts = Counter(risk.severity for risk in risks)
        summary = ArchitectureRiskSummary(
            critical=counts["critical"],
            high=counts["high"],
            medium=counts["medium"],
            low=counts["low"],
            informational=counts["informational"],
        )
        overall = max(
            (risk.severity for risk in risks),
            key=lambda severity: self._SEVERITY_ORDER[severity],
            default="informational",
        )
        return ArchitectureRiskAnalysis(
            workspace_id=workspace.id,
            architecture_id=architecture.id,
            analyzed_workspace_updated_at=workspace.updated_at,
            overall_risk=overall,
            overview=ai_overview,
            summary=summary,
            risks=risks,
        )

    def _deterministic_risks(
        self, workspace: WorkspaceResponse, architecture: ArchitectureOption
    ) -> list[ArchitectureRisk]:
        risks: list[ArchitectureRisk] = []
        component_names = {component.name for component in architecture.components}
        graph_nodes = self._component_node_ids(workspace, architecture.id)
        database_components = [
            component
            for component in architecture.components
            if self._contains_marker(
                " ".join([component.name, component.responsibility, *component.technologies]),
                self._DATABASE_MARKERS,
            )
        ]
        represented_text = self._represented_architecture_text(workspace, architecture)
        if database_components and not self._contains_marker(
            represented_text, self._REDUNDANCY_MARKERS
        ):
            names = [component.name for component in database_components]
            risks.append(
                ArchitectureRisk(
                    id="risk-db-redundancy",
                    title="Database failover is not explicitly represented",
                    category="reliability",
                    severity="high",
                    description=(
                        "Potential risk: the current architecture identifies persistent data "
                        "components but does not explicitly describe replicas or failover."
                    ),
                    evidence=(
                        f"Database-related component(s): {', '.join(names)}. No replica, "
                        "standby, multi-zone, or failover strategy is represented."
                    ),
                    affected_components=names,
                    impact="An outage in the persistence path could interrupt dependent workflows.",
                    recommendation=(
                        "Verify the availability requirement, then define tested backups and an "
                        "appropriate replication and failover strategy."
                    ),
                    confidence=0.88,
                    needs_verification=True,
                    related_node_ids=[graph_nodes[name] for name in names if name in graph_nodes],
                )
            )

        incoming = Counter[str]()
        for component in architecture.components:
            for dependency in component.dependencies:
                if dependency in component_names:
                    incoming[dependency] += 1
        if incoming:
            target, fan_in = incoming.most_common(1)[0]
            if fan_in >= 3:
                risks.append(
                    ArchitectureRisk(
                        id="risk-concentration",
                        title="Dependency concentration",
                        category="resilience",
                        severity="medium" if fan_in < 5 else "high",
                        description=(
                            f"{fan_in} components directly depend on {target}, concentrating "
                            "runtime impact in one component."
                        ),
                        evidence=(
                            "The dependencies fields of the structured component model point "
                            f"to {target} {fan_in} times."
                        ),
                        affected_components=[target],
                        impact="Failure or saturation of this component can affect several callers.",
                        recommendation=(
                            "Review isolation, capacity, timeout, retry, and fallback behavior for "
                            "the shared dependency."
                        ),
                        confidence=0.95,
                        related_node_ids=[graph_nodes[target]] if target in graph_nodes else [],
                    )
                )

        if not self._contains_marker(represented_text, self._OBSERVABILITY_MARKERS):
            risks.append(
                ArchitectureRisk(
                    id="risk-observability",
                    title="Operational telemetry is not explicitly represented",
                    category="operations",
                    severity="medium",
                    description=(
                        "Potential risk: monitoring, logs, metrics, or distributed tracing are "
                        "not explicit in this architecture option."
                    ),
                    evidence="No observability capability is present in the structured architecture fields.",
                    affected_components=[],
                    impact="Incidents may be slower to detect, diagnose, and verify.",
                    recommendation=(
                        "Confirm operational requirements and define logs, metrics, traces, alerts, "
                        "and ownership for critical paths."
                    ),
                    confidence=0.8,
                    needs_verification=True,
                )
            )
        return risks

    @staticmethod
    def _compact_architecture(architecture: ArchitectureOption) -> dict[str, Any]:
        return {
            "id": architecture.id,
            "name": architecture.name,
            "style": architecture.style,
            "overview": architecture.overview[:500],
            "components": [
                {
                    "name": component.name,
                    "responsibility": component.responsibility[:300],
                    "technologies": component.technologies[:6],
                    "interactions": component.interactions[:6],
                    "dependencies": component.dependencies[:8],
                }
                for component in architecture.components[:12]
            ],
            "data_flow": [item[:350] for item in architecture.data_flow[:5]],
            "technology_stack": architecture.technology_stack[:10],
            "database": architecture.database[:500],
            "api_style": architecture.api_style[:400],
            "deployment": architecture.deployment[:500],
            "estimated_complexity": architecture.estimated_complexity,
            "estimated_cost": architecture.estimated_cost,
        }

    @staticmethod
    def _compact_deployment(workspace: WorkspaceResponse) -> dict[str, Any]:
        plan = workspace.deployment_plan
        return ArchitectureAssistantService._known_values(
            {
                "deployment_model": plan.deployment_model,
                "replicas": plan.replicas,
                "regions": plan.regions[:4],
                "deployment_strategy": plan.deployment_strategy,
                "availability_configuration": plan.availability_configuration,
                "target_stack": plan.target_stack[:6],
                "observability": plan.observability[:5],
                "scaling_strategy": plan.scaling_strategy[:5],
                "security_controls": plan.security_controls[:5],
                "cloud_recommendation": plan.cloud_recommendation,
                "failover_mode": plan.failover_mode,
                "rto": plan.rto,
                "rpo": plan.rpo,
            }
        )

    @staticmethod
    def _known_values(values: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in values.items()
            if value not in (None, "", "unknown", [], {})
        }

    def _ground_ai_risks(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        risks: list[_ArchitectureRiskAIItem],
    ) -> list[ArchitectureRisk]:
        known = {component.name.casefold(): component.name for component in architecture.components}
        node_ids = self._component_node_ids(workspace, architecture.id)
        represented_text = self._represented_architecture_text(workspace, architecture)
        grounded: list[ArchitectureRisk] = []
        for index, risk in enumerate(risks, 1):
            if self._absence_claim_is_contradicted(risk, represented_text):
                continue
            affected = self._known_component_names(risk.affected_components, known)
            related = [node_ids[name] for name in affected if name in node_ids]
            grounded.append(
                ArchitectureRisk(
                    id=f"ai-risk-{index:03d}",
                    title=risk.title,
                    category=risk.category,
                    severity=risk.severity,
                    description=risk.description,
                    evidence=risk.evidence,
                    affected_components=affected,
                    impact=risk.impact,
                    recommendation=risk.recommendation,
                    confidence=risk.confidence,
                    needs_verification=risk.needs_verification or risk.confidence < 0.7,
                    related_node_ids=related,
                )
            )
        return grounded

    def _represented_architecture_text(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
    ) -> str:
        values = self._architecture_strings(architecture)
        if architecture.id == workspace.recommendation.recommended_architecture_id:
            values.extend(self._deployment_strings(workspace))
        return " ".join(values)

    def _absence_claim_is_contradicted(
        self,
        risk: _ArchitectureRiskAIItem,
        represented_text: str,
    ) -> bool:
        claim = " ".join([risk.title, risk.description, risk.evidence]).casefold()
        if not any(marker in claim for marker in self._ABSENCE_MARKERS):
            return False
        represented = represented_text.casefold()
        return any(
            any(marker in claim for marker in group)
            and any(marker in represented for marker in group)
            for group in self._CONTROL_MARKER_GROUPS
        )

    def _validated_patch_operations(
        self,
        architecture: ArchitectureOption,
        operations: list[ArchitecturePatchOperation],
    ) -> list[ArchitecturePatchOperation]:
        known = {component.name.casefold(): component.name for component in architecture.components}
        architecture_text = "\n".join(self._architecture_strings(architecture)).casefold()
        validated: list[ArchitecturePatchOperation] = []
        for operation in operations:
            if operation.operation in {"update_component", "remove_component"}:
                current = known.get((operation.component_name or "").casefold())
                if current is None:
                    continue
                operation = operation.model_copy(update={"component_name": current})
            elif operation.operation == "add_component" and operation.component:
                if operation.component.name.casefold() in known:
                    continue
            elif operation.operation == "replace_text":
                if (operation.from_value or "").casefold() not in architecture_text:
                    continue
            validated.append(operation)
        return validated

    def _validated_requirement_additions(
        self,
        message: str,
        additions: list[ArchitectureRequirementAddition],
    ) -> list[ArchitectureRequirementAddition]:
        source_tokens = self._meaningful_tokens(message)
        validated: list[ArchitectureRequirementAddition] = []
        for addition in additions:
            if source_tokens & self._meaningful_tokens(addition.text):
                validated.append(
                    addition.model_copy(update={"text": " ".join(addition.text.split())})
                )
        return validated

    def _direct_command_response(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
    ) -> ArchitectureChatResponse | None:
        replacement = self._explicit_replacement_operation(request.message, architecture)
        addition = self._explicit_requirement_addition(request.message)
        if replacement is None and addition is None:
            return None

        if addition is not None:
            requirement_collections = {
                "functional_requirement": workspace.requirements.functional_requirements,
                "non_functional_requirement": workspace.requirements.non_functional_requirements,
                "constraint": workspace.requirements.constraints,
                "assumption": workspace.requirements.assumptions,
            }
            if any(
                item.casefold() == addition.text.casefold()
                for item in requirement_collections[addition.target_type]
            ):
                return ArchitectureChatResponse(
                    type="question",
                    answer="That project item already exists, so no duplicate was added.",
                )
            label = addition.target_type.replace("_", " ")
            summary = f"Add {label}: {addition.text}"
            proposal = ArchitectureChangeProposal(
                proposal_id=str(uuid.uuid4()),
                architecture_id=architecture.id,
                base_updated_at=workspace.updated_at,
                request=request.message,
                summary=summary,
                reasoning="The request explicitly provides both the item type and its content.",
                requirement_additions=[addition],
                affected_components=[],
                tradeoffs=[],
                risk_level="low",
                auto_apply_safe=True,
            )
            return ArchitectureChatResponse(
                type="architecture_change",
                answer=f"Adding this {label} and refreshing its dependent project views.",
                proposal=proposal,
            )

        assert replacement is not None
        old = replacement.from_value or "existing value"
        new = replacement.to_value or "new value"
        summary = f"Replace {old} with {new} in the selected architecture."
        proposal = ArchitectureChangeProposal(
            proposal_id=str(uuid.uuid4()),
            architecture_id=architecture.id,
            base_updated_at=workspace.updated_at,
            request=request.message,
            summary=summary,
            reasoning=(
                "This is an exact replacement command and the source value exists in the "
                "selected architecture."
            ),
            architecture_changes=[replacement],
            affected_components=[old],
            tradeoffs=[
                f"Compatibility and operational differences between {old} and {new} require review."
            ],
            risk_level="medium",
            auto_apply_safe=True,
        )
        return ArchitectureChatResponse(
            type="architecture_change",
            answer=f"Replacing {old} with {new} and refreshing the affected architecture views.",
            affected_components=[old],
            proposal=proposal,
        )

    def _grounded_component_answer(
        self,
        architecture: ArchitectureOption,
        message: str,
    ) -> ArchitectureChatResponse | None:
        normalized = message.casefold()
        ownership_question = (
            ("component" in normalized or "service" in normalized)
            and any(
                marker in normalized
                for marker in ("which ", "what ", "where ", "owns", "owner", "handles", "responsible")
            )
        )
        if not ownership_question:
            return None

        ignored = {
            "answer", "component", "current", "evidence", "handle", "handles",
            "owner", "owns", "responsible", "service", "state", "support",
            "supports", "what", "where", "which",
        }
        query_tokens = self._meaningful_tokens(message) - ignored
        if not query_tokens:
            return None

        ranked: list[tuple[int, Any]] = []
        for component in architecture.components:
            name = component.name.casefold()
            responsibility = component.responsibility.casefold()
            interactions = " ".join(component.interactions).casefold()
            dependencies = " ".join(component.dependencies).casefold()
            technologies = " ".join(component.technologies).casefold()
            score = sum(
                (5 if token in name else 0)
                + (3 if token in responsibility else 0)
                + (2 if token in interactions else 0)
                + (1 if token in dependencies else 0)
                + (1 if token in technologies else 0)
                for token in query_tokens
            )
            if score:
                ranked.append((score, component))
        if not ranked:
            return None

        ranked.sort(key=lambda item: item[0], reverse=True)
        best_score, best = ranked[0]
        if best_score < 3:
            return None

        matching_interactions = [
            value
            for value in best.interactions
            if query_tokens & self._meaningful_tokens(value)
        ]
        evidence = f'Its stated responsibility is: "{best.responsibility}"'
        if matching_interactions:
            evidence += f" Matching interactions: {', '.join(matching_interactions)}."
        else:
            evidence += "."

        subject_match = re.search(
            r"(?:owns?|handles?|responsible\s+for)\s+(.+?)(?:,|\?|\band\s+what\b|$)",
            message,
            flags=re.IGNORECASE,
        )
        subject = subject_match.group(1).strip() if subject_match else "that responsibility"
        ownership_markers = ("owns", "manages", "stores", "tracks", "responsible")
        ownership_is_explicit = any(
            marker in best.responsibility.casefold() for marker in ownership_markers
        )
        uncertainty = ""
        if not ownership_is_explicit:
            uncertainty = (
                f" This is the strongest modeled match for {subject}, but explicit ownership "
                "is not stated and should be clarified before treating it as a firm boundary."
            )
        return ArchitectureChatResponse(
            type="question",
            answer=(
                f"Based on the selected architecture, {best.name} is the strongest represented "
                f"owner for {subject}. {evidence}{uncertainty}"
            ),
            affected_components=[best.name],
        )

    def _clarify_vague_quality_change(
        self,
        workspace: WorkspaceResponse,
        message: str,
    ) -> ArchitectureChatResponse | None:
        normalized = " ".join(message.casefold().split()).strip(" .!?")
        words = re.findall(r"[a-z0-9]+", normalized)
        qualities = {
            "scalability": "workload type, expected peak, and acceptable response time",
            "performance": "operation to optimize, current behavior, and target response time",
            "security": "threat, protected data, actors, and required compliance controls",
            "reliability": "failure scenario, recovery objective, and acceptable disruption",
            "availability": "availability target, critical workflow, and recovery expectations",
        }
        quality = next((name for name in qualities if name in words), None)
        asks_for_change = any(
            marker in words for marker in ("improve", "increase", "optimize", "strengthen")
        )
        contains_specifics = bool(re.search(r"\d", normalized)) or len(words) > 6
        if quality is None or not asks_for_change or contains_specifics:
            return None

        existing = next(
            (
                item
                for item in workspace.requirements.non_functional_requirements
                if quality in item.casefold()
            ),
            None,
        )
        current_context = (
            f' The current project states: "{existing}"' if existing else ""
        )
        return ArchitectureChatResponse(
            type="question",
            answer=(
                f"I need the {qualities[quality]} before making a safe {quality} change."
                f"{current_context} I will not invent numeric targets or technologies; provide "
                "the missing details and I can prepare a grounded change."
            ),
            recommendations=[
                f"Specify the {qualities[quality]}.",
                "State whether the value is measured today, required, or only an assumption.",
            ],
        )

    @staticmethod
    def _image_addition_target(
        message: str,
    ) -> Literal[
        "functional_requirement",
        "non_functional_requirement",
        "constraint",
        "assumption",
    ] | None:
        normalized = message.casefold().replace("-", " ")
        if not any(
            re.search(rf"\b{verb}\b", normalized)
            for verb in ("add", "capture", "create", "extract", "include", "record")
        ):
            return None
        targets = (
            (r"\b(?:non functional requirement|nfr)s?\b", "non_functional_requirement"),
            (r"\b(?:functional requirement|fr)s?\b", "functional_requirement"),
            (r"\bconstraints?\b", "constraint"),
            (r"\bassumptions?\b", "assumption"),
        )
        return next(
            (target for pattern, target in targets if re.search(pattern, normalized)),
            None,
        )

    @staticmethod
    def _explicit_requirement_addition(
        message: str,
    ) -> ArchitectureRequirementAddition | None:
        match = re.fullmatch(
            r"(?:please\s+)?add\s+(?:a|an)?\s*"
            r"(?P<kind>non[- ]functional requirement|nfr|functional requirement|fr|constraint|assumption)"
            r"\s*(?::|-|that\s+)?(?P<text>.+)",
            message.strip(" .!?"),
            flags=re.IGNORECASE,
        )
        if match is None:
            return None
        kind = match.group("kind").casefold().replace("-", " ")
        target = {
            "functional requirement": "functional_requirement",
            "fr": "functional_requirement",
            "non functional requirement": "non_functional_requirement",
            "nfr": "non_functional_requirement",
            "constraint": "constraint",
            "assumption": "assumption",
        }[kind]
        text = " ".join(match.group("text").split()).strip(" .!?")
        if len(text) < 3:
            return None
        return ArchitectureRequirementAddition(target_type=target, text=text)

    def _explicit_replacement_operation(
        self,
        message: str,
        architecture: ArchitectureOption,
    ) -> ArchitecturePatchOperation | None:
        command = re.sub(
            r"\s+in\s+(?:the\s+)?(?:current|selected)\s+architecture\s*[.!?]*$",
            "",
            message,
            flags=re.IGNORECASE,
        ).strip()
        patterns = (
            r"(?:please\s+)?(?:replace|swap)\s+(?:the\s+)?(?P<old>.+?)\s+with\s+(?P<new>.+)",
            r"(?:please\s+)?(?:switch|migrate)\s+(?:from\s+)?(?P<old>.+?)\s+to\s+(?P<new>.+)",
            r"(?:please\s+)?use\s+(?P<new>.+?)\s+instead\s+of\s+(?:the\s+)?(?P<old>.+)",
        )
        match = next(
            (
                match
                for pattern in patterns
                if (match := re.fullmatch(pattern, command, re.IGNORECASE))
            ),
            None,
        )
        if match is None:
            return None
        old = match.group("old").strip(" .!?")
        new = match.group("new").strip(" .!?")
        if not old or not new or len(old) > 200 or len(new) > 200:
            return None
        exact_values = {
            value.casefold(): value for value in self._architecture_strings(architecture)
        }
        grounded_old = exact_values.get(old.casefold())
        if grounded_old is None or grounded_old.casefold() == new.casefold():
            return None
        return ArchitecturePatchOperation(
            operation="replace_text",
            from_value=grounded_old,
            to_value=new,
        )

    def _repair_explicit_replacement(
        self,
        message: str,
        architecture: ArchitectureOption,
        raw: Any,
    ) -> _ArchitectureChatAIResult | None:
        """Recover a missing patch only for an unambiguous, grounded replacement command."""
        if not isinstance(raw, dict) or raw.get("type") != "architecture_change":
            return None
        if raw.get("architecture_changes") or raw.get("requirement_additions"):
            return None

        operation = self._explicit_replacement_operation(message, architecture)
        if operation is None:
            return None
        old = operation.from_value or "existing value"
        new = operation.to_value or "new value"
        summary = f"Replace {old} with {new} in the selected architecture."
        return _ArchitectureChatAIResult(
            type="architecture_change",
            answer=f"I prepared a proposal to replace {old} with {new}. Review it before applying.",
            summary=summary,
            reasoning=(
                "This is a direct replacement requested by the user. The existing value was "
                "verified against the selected architecture."
            ),
            architecture_changes=[operation],
            affected_components=[old],
            tradeoffs=[
                f"Compatibility and operational differences between {old} and {new} require review."
            ],
            risk_level="medium",
        )

    def _apply_operation(
        self, architecture: ArchitectureOption, operation: ArchitecturePatchOperation
    ) -> ArchitectureOption:
        updated = architecture.model_copy(deep=True)
        if operation.operation == "add_component" and operation.component:
            updated.components.append(operation.component)
            return updated
        if operation.operation in {"update_component", "remove_component"}:
            index = next(
                (
                    index
                    for index, component in enumerate(updated.components)
                    if component.name.casefold() == (operation.component_name or "").casefold()
                ),
                None,
            )
            if index is None:
                raise ValueError(
                    f"Component {operation.component_name!r} no longer exists in this architecture."
                )
            old_name = updated.components[index].name
            if operation.operation == "update_component" and operation.component:
                updated.components[index] = operation.component
            else:
                updated.components.pop(index)
                for component in updated.components:
                    component.dependencies = [
                        dependency
                        for dependency in component.dependencies
                        if dependency.casefold() != old_name.casefold()
                    ]
            return updated
        if operation.operation == "replace_text":
            replaced, count = self._replace_nested_text(
                updated.model_dump(), operation.from_value or "", operation.to_value or ""
            )
            if count == 0:
                raise ValueError(
                    f"{operation.from_value!r} no longer exists in this architecture."
                )
            return ArchitectureOption.model_validate(replaced)
        if operation.operation == "set_field" and operation.field:
            return updated.model_copy(update={operation.field: operation.to_value})
        raise ValueError("Unsupported architecture patch operation.")

    def _select_architecture(
        self, workspace: WorkspaceResponse, architecture_id: str | None
    ) -> ArchitectureOption:
        selected_id = architecture_id or workspace.recommendation.recommended_architecture_id
        architecture = next(
            (item for item in workspace.architectures if item.id == selected_id), None
        )
        if architecture is None:
            raise ValueError("The selected architecture option does not exist.")
        return architecture

    @staticmethod
    def _known_component_names(
        values: list[str], known: dict[str, str]
    ) -> list[str]:
        return ArchitectureAssistantService._dedupe(
            [known[value.casefold()] for value in values if value.casefold() in known]
        )

    @staticmethod
    def _mentioned_component_names(
        text: str, known: dict[str, str]
    ) -> list[str]:
        normalized = text.casefold()
        return [display for name, display in known.items() if name in normalized]

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        output: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = " ".join(value.split()).strip()
            if cleaned and cleaned.casefold() not in seen:
                output.append(cleaned)
                seen.add(cleaned.casefold())
        return output

    @staticmethod
    def _contains_marker(value: str, markers: set[str]) -> bool:
        normalized = value.casefold()
        return any(marker in normalized for marker in markers)

    @staticmethod
    def _architecture_strings(architecture: ArchitectureOption) -> list[str]:
        values: list[str] = [
            architecture.name,
            architecture.style,
            architecture.overview,
            architecture.database,
            architecture.api_style,
            architecture.deployment,
            architecture.estimated_complexity,
            architecture.estimated_cost,
            architecture.maintenance,
            *architecture.data_flow,
            *architecture.technology_stack,
            *architecture.advantages,
            *architecture.disadvantages,
            *architecture.suitable_scenarios,
        ]
        for component in architecture.components:
            values.extend(
                [
                    component.name,
                    component.responsibility,
                    *component.technologies,
                    *component.interactions,
                    *component.dependencies,
                ]
            )
        return values

    @staticmethod
    def _deployment_strings(workspace: WorkspaceResponse) -> list[str]:
        plan = workspace.deployment_plan
        values = [
            plan.deployment_model,
            plan.deployment_strategy or "",
            plan.availability_configuration or "",
            plan.cloud_recommendation,
            plan.failover_mode or "",
            plan.rto or "",
            plan.rpo or "",
            *plan.regions,
            *plan.target_stack,
            *plan.observability,
            *plan.scaling_strategy,
            *plan.security_controls,
        ]
        if plan.replicas and plan.replicas > 1:
            values.append(f"{plan.replicas} replicas")
        return values

    @staticmethod
    def _replace_nested_text(value: Any, old: str, new: str) -> tuple[Any, int]:
        if isinstance(value, str):
            replaced, count = re.subn(re.escape(old), new, value, flags=re.IGNORECASE)
            return replaced, count
        if isinstance(value, list):
            output: list[Any] = []
            total = 0
            for item in value:
                replaced, count = ArchitectureAssistantService._replace_nested_text(item, old, new)
                output.append(replaced)
                total += count
            return output, total
        if isinstance(value, dict):
            output_dict: dict[str, Any] = {}
            total = 0
            for key, item in value.items():
                replaced, count = ArchitectureAssistantService._replace_nested_text(item, old, new)
                output_dict[key] = replaced
                total += count
            return output_dict, total
        return value, 0

    @staticmethod
    def _meaningful_tokens(value: str) -> set[str]:
        ignored = {
            "about", "after", "architecture", "change", "from", "into", "make",
            "should", "system", "that", "this", "with", "would", "your",
        }
        return {
            token
            for token in re.findall(r"[a-z0-9]+", value.casefold())
            if len(token) >= 3 and token not in ignored
        }

    @staticmethod
    def _component_node_ids(
        workspace: WorkspaceResponse, architecture_id: str
    ) -> dict[str, str]:
        if workspace.causal_graph is None:
            return {}
        return {
            node.name: node.id
            for node in workspace.causal_graph.nodes
            if node.type == "architecture_component"
            and node.metadata.get("architecture_id") == architecture_id
        }

    def _merge_risks(self, risks: list[ArchitectureRisk]) -> list[ArchitectureRisk]:
        merged: list[ArchitectureRisk] = []
        seen: set[tuple[RiskCategory, str, tuple[str, ...]]] = set()
        ordered = sorted(
            risks,
            key=lambda risk: self._SEVERITY_ORDER[risk.severity],
            reverse=True,
        )
        for risk in ordered:
            key = (
                risk.category,
                risk.title.casefold(),
                tuple(sorted(component.casefold() for component in risk.affected_components)),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(risk)
        return merged
