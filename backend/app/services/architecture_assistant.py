import logging
import re
import uuid
from time import perf_counter
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
    ProjectAction,
    RiskCategory,
    RiskSeverity,
    WorkspaceResponse,
)
from app.services.ai.client import OllamaStructuredClient
from app.services.assistant_intel import (
    DeterministicAssistant,
    normalize_requirement_text,
    strip_politeness,
    strip_query_noise,
    truncate,
)

logger = logging.getLogger(__name__)



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


class _ArchitectureQuestionAIResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=3, max_length=1800)
    affected_components: list[str] = Field(default_factory=list, max_length=8)
    recommendations: list[str] = Field(default_factory=list, max_length=5)


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
        self.deterministic = DeterministicAssistant()

    # A model attempt shorter than this is not worth starting.
    _MIN_ATTEMPT_SECONDS = 3.0

    def _generate_resilient(
        self,
        stage: str,
        input_data: dict[str, Any],
        *,
        response_schema: dict[str, Any] | None,
        num_predict: int,
        num_ctx: int,
        timeout_seconds: int,
        budget_seconds: int | None = None,
    ) -> dict[str, Any] | None:
        """Ask the model within a hard total budget.

        The turn gets ``budget_seconds`` in total, not per attempt. Inside it:

        1. the assistant model, bounded by ``timeout_seconds``;
        2. the same model again ONLY if the first attempt failed fast — a
           timeout will time out again, whereas malformed output or a dropped
           connection usually will not;
        3. the smaller fallback model, which is cheaper and often enough.

        Whatever happens, this returns within the budget and the caller still
        has a grounded deterministic answer to fall back on.
        """
        settings = self.ai_client.settings
        budget = float(
            budget_seconds
            if budget_seconds is not None
            else settings.assistant_total_budget_seconds
        )
        started_at = perf_counter()

        def remaining() -> float:
            return budget - (perf_counter() - started_at)

        def attempt(model: str, deadline: float, context_window: int):
            window = max(self._MIN_ATTEMPT_SECONDS, min(deadline, remaining()))
            began = perf_counter()
            result = self.ai_client.generate(
                stage,
                input_data,
                response_schema=response_schema,
                num_predict=num_predict,
                num_ctx=context_window,
                timeout_seconds=int(window),
                model=model,
            )
            return result, (perf_counter() - began) >= window * 0.9

        primary = settings.ollama_assistant_model
        result, timed_out = attempt(primary, timeout_seconds, num_ctx)
        if result is not None:
            return result

        if (
            settings.assistant_retry_once
            and not timed_out
            and remaining() >= self._MIN_ATTEMPT_SECONDS
        ):
            result, _ = attempt(primary, timeout_seconds, num_ctx)
            if result is not None:
                logger.info("Assistant stage %s succeeded on retry", stage)
                return result

        fallback = (settings.assistant_fallback_model or "").strip()
        if (
            fallback
            and fallback != primary
            and remaining() >= self._MIN_ATTEMPT_SECONDS
        ):
            result, _ = attempt(
                fallback,
                settings.assistant_fallback_timeout_seconds,
                min(num_ctx, 1536),
            )
            if result is not None:
                logger.info("Assistant stage %s answered by fallback model %s", stage, fallback)
                return result

        logger.info(
            "Assistant stage %s produced nothing within %.0fs; answering deterministically",
            stage,
            budget,
        )
        return None

    def chat(
        self, workspace: WorkspaceResponse, request: ArchitectureChatRequest
    ) -> ArchitectureChatResponse:
        """Answer one turn, always within a bounded amount of work."""
        started_at = perf_counter()
        response = self._chat(workspace, request)
        category = response.category
        if response.proposal is not None and category == "QUESTION":
            # The exact-command layer predates the taxonomy and does not label
            # itself; a proposal is an action whichever layer produced it.
            category = "ACTION"
        return response.model_copy(
            update={
                "category": category,
                "elapsed_ms": round((perf_counter() - started_at) * 1000, 2),
            }
        )

    def _chat(
        self, workspace: WorkspaceResponse, request: ArchitectureChatRequest
    ) -> ArchitectureChatResponse:
        architecture = self._select_architecture(workspace, request.architecture_id)
        if request.images:
            return self._chat_with_image(workspace, architecture, request)

        # Match commands against the de-politened text. Every pattern anchors at
        # the start of the message, so a "can you …" wrapper used to defeat all
        # of them and push a simple edit onto the slowest path there is.
        command_text = strip_politeness(request.message)
        request = (
            request
            if command_text == request.message
            else request.model_copy(update={"message": command_text})
        )
        direct_response = self._direct_command_response(workspace, architecture, request)
        if direct_response is not None:
            return direct_response
        # Resolve the common turns — list, count, overview, explain, suggest,
        # reword, delete-by-description — from the canonical model. These used
        # to fall through to Ollama, which is where the seconds went.
        deterministic = self.deterministic.respond(workspace, architecture, request)
        if deterministic is not None:
            return deterministic
        project_answer = self._project_question_response(workspace, architecture, request)
        if project_answer is not None:
            return project_answer
        clarification = self._clarify_vague_quality_change(workspace, request.message)
        if clarification is not None:
            return clarification
        grounded_response = self._grounded_component_answer(architecture, request.message)
        if grounded_response is not None:
            return grounded_response
        input_data = {
            "project_id": workspace.id,
            "raw_requirement": request.message,
            "project": self._retrieve_project_context(workspace, request),
            "current_architecture": self._compact_architecture(architecture),
            "current_deployment": self._compact_deployment(workspace),
            "conversation": [item.model_dump() for item in request.history[-8:]],
            "attached_images": [image.name for image in request.images],
        }
        if self._is_informational_request(request.message):
            raw_question = self._generate_resilient(
                "architecture-chat-question",
                input_data,
                response_schema=_ArchitectureQuestionAIResult.model_json_schema(),
                num_predict=160,
                num_ctx=1536,
                timeout_seconds=self.ai_client.settings.assistant_question_timeout_seconds,
            )
            if raw_question is None:
                return self._evidence_fallback_response(workspace, architecture, request)
            try:
                result = _ArchitectureQuestionAIResult.model_validate(raw_question)
            except ValidationError:
                return self._evidence_fallback_response(workspace, architecture, request)
            known_names = {
                component.name.casefold(): component.name for component in architecture.components
            }
            affected = self._known_component_names(result.affected_components, known_names)
            return ArchitectureChatResponse(
                type="question",
                answer=result.answer,
                affected_components=affected,
                recommendations=self._dedupe(result.recommendations),
                category="ANALYSIS",
                resolved_by="model",
                confidence="medium",
            )

        raw = self._generate_resilient(
            "architecture-chat",
            input_data,
            response_schema=_ArchitectureChatAIResult.model_json_schema(),
            num_predict=220,
            num_ctx=2048,
            timeout_seconds=self.ai_client.settings.assistant_change_timeout_seconds,
        )
        if raw is None:
            if request.images:
                raise ArchitectureAssistantUnavailableError(
                    "Image analysis is unavailable. Install the configured vision model "
                    f"with: ollama pull {self.ai_client.settings.ollama_vision_model}"
                )
            return self._evidence_fallback_response(workspace, architecture, request)
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
            # This used to run with no explicit deadline, which resolved to the
            # global 180s request timeout and left the Risk view spinning for
            # three minutes. It is now bounded like every other assistant call,
            # and the deterministic findings are already computed either way.
            raw = self._generate_resilient(
                "architecture-risk-analysis",
                input_data,
                response_schema=_ArchitectureRiskAIResult.model_json_schema(),
                num_predict=700,
                num_ctx=2560,
                timeout_seconds=self.ai_client.settings.assistant_risk_timeout_seconds,
                budget_seconds=self.ai_client.settings.assistant_risk_budget_seconds,
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
                "Deterministic checks completed. The deeper AI review did not return within "
                f"{self.ai_client.settings.assistant_risk_budget_seconds}s, so these findings "
                "come from the structured checks alone — they are complete in their own right, "
                "not a partial result."
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

        risks.extend(self._critique_risks(workspace, architecture, graph_nodes))

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

    def _critique_risks(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        graph_nodes: dict[str, str],
    ) -> list[ArchitectureRisk]:
        """Reuse the architecture critic so the risk view is never empty.

        The three original rules only fire on larger architectures, so a small
        project produced zero risks and looked broken. The critic finds
        uncovered requirements, untraceable components, single points of
        failure and unmotivated technology from the same recorded facts.
        """
        from app.services.assistant_intel import ProjectIndex

        index = ProjectIndex(workspace)
        findings = self.deterministic.analysis.critique(workspace, architecture, index)
        converted: list[ArchitectureRisk] = []
        for position, finding in enumerate(findings, start=1):
            components = [
                name for name in finding.components if name in {
                    component.name for component in architecture.components
                }
            ]
            converted.append(
                ArchitectureRisk(
                    id=f"risk-critique-{position:03d}",
                    title=finding.title[:140],
                    category=finding.category,  # type: ignore[arg-type]
                    severity=finding.severity,  # type: ignore[arg-type]
                    description=f"{finding.label}: {finding.detail}"[:1000],
                    evidence=(
                        f"Derived from the recorded project model. Related items: "
                        f"{', '.join(finding.evidence)}."
                        if finding.evidence
                        else "Derived from the recorded project model."
                    )[:1000],
                    affected_components=components[:12],
                    impact=(
                        "Left as-is, this weakens traceability between the requirements and "
                        "the implemented design."
                    ),
                    recommendation=(
                        finding.recommendation
                        or "Review this against the requirement model before building."
                    )[:1000],
                    confidence=0.9 if finding.label == "Confirmed issue" else 0.7,
                    needs_verification=finding.needs_verification,
                    related_node_ids=[
                        graph_nodes[name] for name in components if name in graph_nodes
                    ][:20],
                )
            )
        return converted

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
        project_response = self._explicit_project_action_response(
            workspace, architecture, request
        )
        if project_response is not None:
            return project_response
        replacement = self._explicit_replacement_operation(request.message, architecture)
        addition = self._explicit_requirement_addition(request.message)
        if replacement is None and addition is None:
            return None

        if addition is not None:
            addition = self._normalized_addition(addition)
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
            answer = f"Adding this {label} and refreshing its dependent project views."
            note = self._wording_note(addition.target_type, addition.text)
            if note:
                answer = f"{answer} {note}"
            return ArchitectureChatResponse(
                type="architecture_change",
                answer=answer,
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

    def _explicit_project_action_response(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
    ) -> ArchitectureChatResponse | None:
        message = " ".join(request.message.strip(" .!?").split())
        lowered = message.casefold()
        action: ProjectAction | None = None
        summary = ""
        risk: Literal["low", "medium", "high"] = "low"
        auto_apply = True
        requirement_additions: list[ArchitectureRequirementAddition] = []

        if re.fullmatch(r"(?:please\s+)?undo(?:\s+(?:my\s+)?last\s+change)?", lowered):
            action = ProjectAction(action="undo", rationale="The user explicitly requested undo.")
            summary = "Undo the last canonical workspace change."
        elif re.fullmatch(r"(?:please\s+)?redo(?:\s+(?:my\s+)?last\s+change)?", lowered):
            action = ProjectAction(action="redo", rationale="The user explicitly requested redo.")
            summary = "Redo the last canonical workspace change."
        else:
            requirement_match = re.fullmatch(
                r"(?:please\s+)?(?:delete|remove)\s+(?P<kind>fr|nfr)-(?P<index>\d{1,3})",
                lowered,
            )
            if requirement_match:
                kind = requirement_match.group("kind").upper()
                target_id = f"{kind}-{int(requirement_match.group('index')):03d}"
                values = (
                    workspace.requirements.functional_requirements
                    if kind == "FR"
                    else workspace.requirements.non_functional_requirements
                )
                index = int(requirement_match.group("index")) - 1
                if index < 0 or index >= len(values):
                    return ArchitectureChatResponse(
                        type="question",
                        answer=f"{target_id} does not exist in the current canonical requirement model.",
                    )
                action = ProjectAction(
                    action="delete_requirement",
                    target_id=target_id,
                    requirement_type=(
                        "functional_requirement" if kind == "FR" else "non_functional_requirement"
                    ),
                    rationale=f"The user explicitly requested deletion of {target_id}.",
                )
                summary = f"Delete {target_id}: {values[index]}"
                risk = "high"
                auto_apply = False

        if action is None and request.selection and re.fullmatch(
            r"(?:please\s+)?(?:delete|remove)\s+(?:this|the\s+selected\s+(?:item|object))",
            lowered,
        ):
            selected_action = self._selected_delete_action(workspace, architecture, request)
            if selected_action is None:
                return ArchitectureChatResponse(
                    type="question",
                    answer="The selected item cannot be removed through a validated project action.",
                )
            action, selected_label = selected_action
            summary = f"Delete selected {selected_label}."
            risk = "high"
            auto_apply = False

        actor_rename = re.fullmatch(
            r"(?:please\s+)?(?:rename|change|update)\s+(?:the\s+)?actor"
            r"(?:\s+name)?\s+(?:from\s+)?(?P<old>.+?)\s+(?:to|as)\s+(?P<new>.+)",
            message,
            re.IGNORECASE,
        )
        if action is None and actor_rename:
            old_name = actor_rename.group("old").strip(" .!?\"'")
            new_name = actor_rename.group("new").strip(" .!?\"'")
            index = next(
                (
                    index
                    for index, actor in enumerate(workspace.requirements.actors)
                    if actor.name.casefold() == old_name.casefold()
                ),
                None,
            )
            if index is None:
                # Let the deterministic rename resolver handle it: it matches a
                # differently-cased or near-miss name and, failing that, reports
                # which actors do exist instead of a bare "does not exist".
                return None
            if workspace.requirements.actors[index].name.casefold() == new_name.casefold():
                return ArchitectureChatResponse(
                    type="question",
                    answer=(
                        f"Confirmed: ACTOR-{index + 1:03d} is already named "
                        f"'{workspace.requirements.actors[index].name}', so no change was prepared."
                    ),
                )
            if not new_name:
                return ArchitectureChatResponse(
                    type="question",
                    answer="Provide the new actor name after 'to'.",
                )
            duplicate = next(
                (
                    actor.name
                    for actor_index, actor in enumerate(workspace.requirements.actors)
                    if actor_index != index and actor.name.casefold() == new_name.casefold()
                ),
                None,
            )
            if duplicate:
                return ArchitectureChatResponse(
                    type="question",
                    answer=f"Actor {duplicate} already exists, so the rename was not applied.",
                )
            actor = workspace.requirements.actors[index]
            value = actor.model_dump(mode="json")
            value["name"] = new_name
            value["source_evidence"] = [
                *value.get("source_evidence", []),
                {
                    "source_id": "AI-USER-ACTOR-RENAME",
                    "source": "explicit assistant command",
                    "status": "user-edited",
                    "excerpt": request.message,
                },
            ]
            action = ProjectAction(
                action="update_actor",
                target_id=f"ACTOR-{index + 1:03d}",
                value=value,
                rationale=(
                    f"The user explicitly renamed actor {actor.name} to {new_name}; "
                    "all other actor facts are preserved."
                ),
            )
            summary = f"Rename actor {actor.name} to {new_name}."

        actor_remove = re.fullmatch(
            r"(?:please\s+)?(?:delete|remove)\s+(?:the\s+)?actor\s+(?P<name>.+)",
            message,
            re.IGNORECASE,
        )
        if action is None and actor_remove:
            name = actor_remove.group("name").strip(" .!?")
            index = next(
                (index for index, actor in enumerate(workspace.requirements.actors) if actor.name.casefold() == name.casefold()),
                None,
            )
            if index is None:
                return ArchitectureChatResponse(type="question", answer=f"Actor {name} does not exist.")
            action = ProjectAction(
                action="delete_actor",
                target_id=f"ACTOR-{index + 1:03d}",
                rationale=f"The user explicitly requested removal of actor {workspace.requirements.actors[index].name}.",
            )
            summary = f"Delete actor {workspace.requirements.actors[index].name}."
            risk = "high"
            auto_apply = False

        database_entity_remove = re.fullmatch(
            r"(?:please\s+)?(?:delete|remove)\s+(?:the\s+)?(?:database|db)\s+entity\s+(?P<name>.+)",
            message,
            re.IGNORECASE,
        )
        if action is None and database_entity_remove:
            name = database_entity_remove.group("name").strip(" .!?")
            index = next(
                (index for index, entity in enumerate(workspace.database_design.entities) if entity.name.casefold() == name.casefold()),
                None,
            )
            if index is None:
                return ArchitectureChatResponse(type="question", answer=f"Database entity {name} does not exist.")
            action = ProjectAction(
                action="delete_database_entity",
                target_id=f"ENTITY-{index + 1:03d}",
                rationale=f"The user explicitly requested removal of database entity {workspace.database_design.entities[index].name}.",
            )
            summary = f"Delete database entity {workspace.database_design.entities[index].name}."
            risk = "high"
            auto_apply = False

        entity_remove = re.fullmatch(
            r"(?:please\s+)?(?:delete|remove)\s+(?:the\s+)?(?:domain\s+)?entity\s+(?P<name>.+)",
            message,
            re.IGNORECASE,
        )
        if action is None and entity_remove:
            name = entity_remove.group("name").strip(" .!?")
            index = next(
                (index for index, entity in enumerate(workspace.requirements.domain_entities) if entity.name.casefold() == name.casefold()),
                None,
            )
            if index is None:
                return ArchitectureChatResponse(type="question", answer=f"Domain entity {name} does not exist.")
            action = ProjectAction(
                action="delete_entity",
                target_id=f"ENTITY-HINT-{index + 1:03d}",
                rationale=f"The user explicitly requested removal of domain entity {workspace.requirements.domain_entities[index].name}.",
            )
            summary = f"Delete domain entity {workspace.requirements.domain_entities[index].name}."
            risk = "high"
            auto_apply = False

        component_remove = re.fullmatch(
            r"(?:please\s+)?(?:delete|remove)\s+(?:the\s+)?(?P<name>.+?)\s+(?:service|component)",
            message,
            re.IGNORECASE,
        )
        if action is None and component_remove:
            name = component_remove.group("name").strip(" .!?")
            index = next(
                (index for index, component in enumerate(architecture.components) if component.name.casefold() in {name.casefold(), f"{name} service".casefold(), f"{name} component".casefold()}),
                None,
            )
            if index is None:
                return ArchitectureChatResponse(type="question", answer=f"Architecture component {name} does not exist in {architecture.name}.")
            component = architecture.components[index]
            action = ProjectAction(
                action="delete_architecture_component",
                target_id=f"COMPONENT-{index + 1:03d}",
                parent_id=architecture.id,
                rationale=f"The user explicitly requested removal of architecture component {component.name}.",
            )
            summary = f"Delete architecture component {component.name}."
            risk = "high"
            auto_apply = False

        api_remove = re.fullmatch(
            r"(?:please\s+)?(?:delete|remove)\s+(?:the\s+)?(?:api\s+)?(?:endpoint\s+)?(?:(?P<method>get|post|put|patch|delete)\s+)?(?P<path>/\S+)",
            message,
            re.IGNORECASE,
        )
        if action is None and api_remove:
            method = api_remove.group("method")
            path = api_remove.group("path").rstrip(".!?")
            matches = [
                (group_index, endpoint_index, endpoint)
                for group_index, group in enumerate(workspace.api_design.groups)
                for endpoint_index, endpoint in enumerate(group.endpoints)
                if endpoint.path.casefold() == path.casefold()
                and (method is None or endpoint.method.casefold() == method.casefold())
            ]
            if len(matches) != 1:
                qualifier = "does not exist" if not matches else "is ambiguous; include the HTTP method"
                return ArchitectureChatResponse(type="question", answer=f"API endpoint {path} {qualifier}.")
            group_index, endpoint_index, endpoint = matches[0]
            action = ProjectAction(
                action="delete_api_endpoint",
                target_id=f"ENDPOINT-{endpoint_index + 1:03d}",
                parent_id=str(group_index),
                rationale=f"The user explicitly requested removal of {endpoint.method} {endpoint.path}.",
            )
            summary = f"Delete API endpoint {endpoint.method} {endpoint.path}."
            risk = "high"
            auto_apply = False

        availability_change = re.fullmatch(
            r"(?:please\s+)?(?:change|set|update)\s+(?:the\s+)?availability(?:\s+(?:target|sla))?\s+(?:to\s+)?(?P<value>\d{2,3}(?:\.\d+)?)%?",
            message,
            re.IGNORECASE,
        )
        if action is None and availability_change:
            value = float(availability_change.group("value"))
            if value < 90 or value > 100:
                return ArchitectureChatResponse(
                    type="question",
                    answer="Availability targets must be between 90% and 100%. Confirm a valid target.",
                )
            action = ProjectAction(
                action="update_deployment",
                target_id="deployment",
                value={
                    "availability_target_percent": value,
                    "availability_configuration": f"User-specified availability target: {value:g}%.",
                },
                rationale=f"The user explicitly specified an availability target of {value:g}%.",
            )
            summary = f"Set the deployment availability target to {value:g}%."
            risk = "medium"
            auto_apply = False

        actor_add = re.fullmatch(
            r"(?:please\s+)?add\s+(?:an?\s+)?actor(?:\s+(?:called|named))?\s+(?P<name>.+)",
            message,
            re.IGNORECASE,
        )
        if action is None and actor_add:
            name = actor_add.group("name").strip(" .!?")
            if any(actor.name.casefold() == name.casefold() for actor in workspace.requirements.actors):
                return ArchitectureChatResponse(type="question", answer=f"Actor {name} already exists.")
            action = ProjectAction(
                action="add_actor",
                value={
                    "id": f"ACT-{len(workspace.requirements.actors) + 1:03d}",
                    "name": name,
                    "description": "User-requested actor; responsibilities require confirmation.",
                    "actor_type": "unknown",
                    "responsibilities": [],
                    "permissions": [],
                    "source_evidence": [{
                        "source_id": "AI-USER-ACTOR",
                        "source": "explicit assistant command",
                        "status": "user-edited",
                        "excerpt": request.message,
                    }],
                },
                rationale="The actor name is explicitly supplied; responsibilities remain unknown.",
            )
            summary = f"Add actor {name} without inventing responsibilities."

        entity_add = re.fullmatch(
            r"(?:please\s+)?(?:add|create)\s+(?:an?\s+)?entity(?:\s+(?:for|called|named))?\s+(?P<name>.+)",
            message,
            re.IGNORECASE,
        )
        if action is None and entity_add:
            name = entity_add.group("name").strip(" .!?")
            if any(entity.name.casefold() == name.casefold() for entity in workspace.requirements.domain_entities):
                return ArchitectureChatResponse(type="question", answer=f"Entity {name} already exists.")
            action = ProjectAction(
                action="add_entity",
                value={
                    "id": f"ENT-{len(workspace.requirements.domain_entities) + 1:03d}",
                    "name": name,
                    "description": "User-requested domain entity; attributes require confirmation.",
                    "attributes": [],
                    "lifecycle_fields": [],
                    "source_evidence": [{
                        "source_id": "AI-USER-ENTITY",
                        "source": "explicit assistant command",
                        "status": "user-edited",
                        "excerpt": request.message,
                    }],
                },
                rationale="The entity is explicit; no fields or lifecycle facts were inferred.",
            )
            summary = f"Add domain entity {name} with unknown attributes."

        screen_remove = re.fullmatch(
            r"(?:please\s+)?(?:remove|delete)\s+(?:the\s+)?(?:prototype\s+)?(?:screen|page)\s+(?P<name>.+)",
            message,
            re.IGNORECASE,
        )
        if action is None and screen_remove:
            name = screen_remove.group("name").strip(" .!?")
            screen = next(
                (item for item in workspace.prototype.screens if item.name.casefold() == name.casefold()),
                None,
            )
            if screen is None:
                return ArchitectureChatResponse(
                    type="question",
                    answer=f"No prototype screen named {name} exists in the current workspace.",
                )
            action = ProjectAction(
                action="remove_prototype_screen",
                target_id=screen.id,
                rationale="The user explicitly requested a prototype-only screen removal.",
            )
            summary = f"Remove prototype screen {screen.name}."
            auto_apply = False

        screen_add = re.fullmatch(
            r"(?:please\s+)?add\s+(?:another\s+|a\s+)?(?:prototype\s+)?(?:screen|page)\s+(?:for\s+)?(?P<name>.+)",
            message,
            re.IGNORECASE,
        )
        if action is None and screen_add:
            name = screen_add.group("name").strip(" .!?")
            action = ProjectAction(
                action="regenerate_affected",
                rationale="Generate the screen only after its product behavior is accepted as a canonical requirement.",
            )
            requirement_text = f"Users can access {name}."
            requirement_additions = [ArchitectureRequirementAddition(
                target_type="functional_requirement",
                text=requirement_text,
            )]
            summary = f"Add {name} as a functional requirement and prototype screen."
            risk = "medium"
            auto_apply = False

        if action is None:
            return None
        proposal = ArchitectureChangeProposal(
            proposal_id=str(uuid.uuid4()),
            architecture_id=architecture.id,
            base_updated_at=workspace.updated_at,
            request=request.message,
            summary=summary,
            reasoning=action.rationale,
            requirement_additions=requirement_additions,
            project_actions=[action],
            affected_components=[],
            tradeoffs=(
                ["Dependent requirements, prototype screens, APIs, diagrams, and traceability will be revalidated."]
                if risk != "low" else []
            ),
            risk_level=risk,
            auto_apply_safe=auto_apply,
        )
        return ArchitectureChatResponse(
            type="architecture_change",
            answer=f"I prepared a structured project action: {summary}",
            proposal=proposal,
        )

    def _selected_delete_action(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
    ) -> tuple[ProjectAction, str] | None:
        selection = request.selection
        if selection is None:
            return None
        if selection.object_type == "requirement":
            match = re.fullmatch(r"(FR|NFR)-(\d{3})", selection.object_id, re.IGNORECASE)
            if not match:
                return None
            kind = match.group(1).upper()
            return ProjectAction(
                action="delete_requirement",
                target_id=f"{kind}-{match.group(2)}",
                requirement_type="functional_requirement" if kind == "FR" else "non_functional_requirement",
                rationale="The user explicitly requested removal of the selected requirement.",
            ), selection.name or selection.object_id
        if selection.object_type == "actor":
            index = next((index for index, actor in enumerate(workspace.requirements.actors) if selection.object_id in {actor.id, f"ACTOR-{index + 1:03d}"}), None)
            if index is not None:
                return ProjectAction(action="delete_actor", target_id=f"ACTOR-{index + 1:03d}", rationale="The user explicitly requested removal of the selected actor."), selection.name or workspace.requirements.actors[index].name
        if selection.object_type == "entity":
            index = next((index for index, entity in enumerate(workspace.requirements.domain_entities) if selection.object_id in {entity.id, f"ENTITY-HINT-{index + 1:03d}"}), None)
            if index is not None:
                return ProjectAction(action="delete_entity", target_id=f"ENTITY-HINT-{index + 1:03d}", rationale="The user explicitly requested removal of the selected domain entity."), selection.name or workspace.requirements.domain_entities[index].name
        if selection.object_type == "architecture_component":
            match = re.fullmatch(r"COMPONENT-(\d{3})", selection.object_id)
            if match and int(match.group(1)) <= len(architecture.components):
                return ProjectAction(action="delete_architecture_component", target_id=selection.object_id, parent_id=architecture.id, rationale="The user explicitly requested removal of the selected architecture component."), selection.name or selection.object_id
        if selection.object_type == "database_entity":
            match = re.fullmatch(r"ENTITY-(\d{3})", selection.object_id)
            if match and int(match.group(1)) <= len(workspace.database_design.entities):
                return ProjectAction(action="delete_database_entity", target_id=selection.object_id, rationale="The user explicitly requested removal of the selected database entity."), selection.name or selection.object_id
        if selection.object_type == "api_endpoint":
            match = re.fullmatch(r"API-GROUP-(\d+)-ENDPOINT-(\d+)", selection.object_id)
            if match:
                group_index, endpoint_index = int(match.group(1)), int(match.group(2))
                if group_index < len(workspace.api_design.groups) and endpoint_index < len(workspace.api_design.groups[group_index].endpoints):
                    return ProjectAction(action="delete_api_endpoint", target_id=f"ENDPOINT-{endpoint_index + 1:03d}", parent_id=str(group_index), rationale="The user explicitly requested removal of the selected API endpoint."), selection.name or selection.object_id
        if selection.object_type == "prototype_screen" and any(screen.id == selection.object_id for screen in workspace.prototype.screens):
            return ProjectAction(action="remove_prototype_screen", target_id=selection.object_id, rationale="The user explicitly requested removal of the selected prototype screen."), selection.name or selection.object_id
        return None

    def _project_question_response(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
    ) -> ArchitectureChatResponse | None:
        message = request.message.casefold()
        if request.selection and any(marker in message for marker in ("this", "selected", "why is")):
            selection = request.selection
            if selection.object_type == "prototype_screen":
                screen = next((item for item in workspace.prototype.screens if item.id == selection.object_id), None)
                if screen:
                    evidence = ", ".join(screen.source_requirement_ids) or "no validated requirement"
                    return ArchitectureChatResponse(
                        type="question",
                        answer=(
                            f"Confirmed: {screen.name} exists to {screen.purpose} "
                            f"Traceability: {evidence}. "
                            + ("This is a prototype-only screen and should be validated." if not screen.source_requirement_ids else "")
                        ),
                    )
            if selection.object_type == "requirement":
                match = re.fullmatch(r"(FR|NFR)-(\d{3})", selection.object_id, re.IGNORECASE)
                if match:
                    values = (
                        workspace.requirements.functional_requirements
                        if match.group(1).upper() == "FR"
                        else workspace.requirements.non_functional_requirements
                    )
                    index = int(match.group(2)) - 1
                    if 0 <= index < len(values):
                        downstream = []
                        if workspace.causal_graph:
                            linked = {
                                edge.target_node_id
                                for edge in workspace.causal_graph.edges
                                if edge.source_node_id == selection.object_id.upper()
                            }
                            downstream = [node.name for node in workspace.causal_graph.nodes if node.id in linked]
                        return ArchitectureChatResponse(
                            type="question",
                            answer=(
                                f"Confirmed: {selection.object_id.upper()} states '{values[index]}'. "
                                f"Its direct implementation path includes: {', '.join(downstream[:8]) or 'no validated downstream artifact yet'}."
                            ),
                        )
            if selection.object_type == "actor":
                actor = next(
                    (item for index, item in enumerate(workspace.requirements.actors) if selection.object_id in {item.id, f"ACTOR-{index + 1:03d}"}),
                    None,
                )
                if actor:
                    responsibilities = ", ".join(actor.responsibilities) or "responsibilities are not yet confirmed"
                    return ArchitectureChatResponse(
                        type="question",
                        answer=f"Confirmed actor: {actor.name}. {actor.description} Responsibilities: {responsibilities}.",
                    )
            if selection.object_type == "entity":
                entity = next(
                    (item for index, item in enumerate(workspace.requirements.domain_entities) if selection.object_id in {item.id, f"ENTITY-HINT-{index + 1:03d}"}),
                    None,
                )
                if entity:
                    attributes = ", ".join(entity.attributes) or "attributes remain unknown"
                    return ArchitectureChatResponse(
                        type="question",
                        answer=f"Confirmed domain entity: {entity.name}. {entity.description} Known attributes: {attributes}.",
                    )
            if selection.object_type == "architecture_component":
                match = re.fullmatch(r"COMPONENT-(\d{3})", selection.object_id)
                index = int(match.group(1)) - 1 if match else -1
                if 0 <= index < len(architecture.components):
                    component = architecture.components[index]
                    return ArchitectureChatResponse(
                        type="question",
                        answer=(
                            f"Confirmed component: {component.name}. {component.responsibility} "
                            f"Dependencies: {', '.join(component.dependencies) or 'none recorded'}."
                        ),
                        affected_components=[component.name],
                    )
            if selection.object_type == "api_endpoint":
                match = re.fullmatch(r"API-GROUP-(\d+)-ENDPOINT-(\d+)", selection.object_id)
                if match:
                    group_index, endpoint_index = int(match.group(1)), int(match.group(2))
                    if group_index < len(workspace.api_design.groups) and endpoint_index < len(workspace.api_design.groups[group_index].endpoints):
                        endpoint = workspace.api_design.groups[group_index].endpoints[endpoint_index]
                        return ArchitectureChatResponse(
                            type="question",
                            answer=(
                                f"Confirmed API: {endpoint.method} {endpoint.path}. {endpoint.purpose} "
                                f"Owner: {endpoint.owner or endpoint.service or 'unknown'}. Requirement trace: "
                                f"{', '.join(endpoint.requirement_ids) or 'none recorded'}."
                            ),
                            affected_components=[endpoint.owner or endpoint.service] if endpoint.owner or endpoint.service else [],
                        )
            if selection.object_type == "database_entity":
                match = re.fullmatch(r"ENTITY-(\d{3})", selection.object_id)
                index = int(match.group(1)) - 1 if match else -1
                if 0 <= index < len(workspace.database_design.entities):
                    entity = workspace.database_design.entities[index]
                    return ArchitectureChatResponse(
                        type="question",
                        answer=(
                            f"Confirmed database entity: {entity.name}. {entity.description} "
                            f"Fields: {', '.join(field.name for field in entity.fields) or 'none defined'}."
                        ),
                    )

        if "actor" in message and any(marker in message for marker in ("no actor", "missing actor", "suggest", "who should")):
            if workspace.requirements.actors:
                facts = "; ".join(
                    f"{actor.name}: {actor.description}" for actor in workspace.requirements.actors
                )
                return ArchitectureChatResponse(
                    type="question",
                    answer=f"Confirmed actors in the canonical model: {facts}",
                )
            candidates: dict[str, list[str]] = {}
            for index, requirement in enumerate(workspace.requirements.functional_requirements, start=1):
                match = re.match(r"(?:the\s+)?([A-Za-z][A-Za-z -]{1,40}?)\s+(?:can|must|should)\b", requirement)
                if match:
                    name = match.group(1).strip().title()
                    candidates.setdefault(name, []).append(f"FR-{index:03d}")
            for workflow in workspace.requirements.domain_workflows:
                actor = workflow.primary_actor.strip()
                if actor and "clarif" not in actor.casefold() and actor.casefold() != "unknown":
                    candidates.setdefault(actor, []).append(workflow.name)
            if not candidates:
                return ArchitectureChatResponse(
                    type="question",
                    answer=(
                        "Confirmed: the canonical model has no validated actors. Inference: the current "
                        "requirements do not name a participant clearly enough to propose one safely. "
                        "Clarify who initiates the main workflow and who administers it."
                    ),
                )
            suggestions = [
                f"Inference: {name}, supported by {', '.join(evidence)} (high confidence from explicit wording)."
                for name, evidence in candidates.items()
            ]
            return ArchitectureChatResponse(
                type="question",
                answer=(
                    "Confirmed: no actors are currently validated. " + " ".join(suggestions)
                    + " Recommendation: review these candidates before adding them."
                ),
                recommendations=[f"Add actor {name}" for name in candidates],
            )

        requirement_match = re.search(r"\b(fr|nfr)-(\d{1,3})\b", message)
        if requirement_match and any(marker in message for marker in ("delete", "remove", "what happens", "depend")):
            requirement_id = f"{requirement_match.group(1).upper()}-{int(requirement_match.group(2)):03d}"
            graph = workspace.causal_graph
            if graph and any(node.id == requirement_id for node in graph.nodes):
                trace = next((node for node in graph.nodes if node.id == requirement_id), None)
                downstream = [
                    edge.target_node_id for edge in graph.edges if edge.source_node_id == requirement_id
                ]
                names = [node.name for node in graph.nodes if node.id in downstream]
                return ArchitectureChatResponse(
                    type="question",
                    answer=(
                        f"Confirmed: {requirement_id} is '{trace.description if trace else ''}'. "
                        f"Deleting it would require revalidation of: {', '.join(names[:10]) or 'no linked artifacts'}. "
                        "Recommendation: preview the deletion before applying it."
                    ),
                )

        if "api" in message and any(marker in message for marker in ("which", "handles", "where", "why")):
            query = self._meaningful_tokens(request.message) - {"api", "which", "handles", "where", "why"}
            matches = []
            for group in workspace.api_design.groups:
                for endpoint in group.endpoints:
                    represented = " ".join([endpoint.path, endpoint.purpose, endpoint.resource or ""])
                    score = len(query & self._meaningful_tokens(represented))
                    if score:
                        matches.append((score, endpoint, group.name))
            if matches:
                matches.sort(key=lambda item: item[0], reverse=True)
                _, endpoint, group = matches[0]
                requirements = ", ".join(endpoint.requirement_ids) or "no requirement trace"
                return ArchitectureChatResponse(
                    type="question",
                    answer=(
                        f"Confirmed: {endpoint.method.upper()} {endpoint.path} in {group} handles the strongest "
                        f"matching operation. Its purpose is '{endpoint.purpose}'. Traceability: {requirements}."
                    ),
                )

        if any(marker in message for marker in ("why did", "why choose", "why this architecture", "do we need microservices")):
            reasons = " ".join(workspace.recommendation.why[:4])
            alternatives = ", ".join(workspace.recommendation.why_not.keys()) or "none recorded"
            return ArchitectureChatResponse(
                type="question",
                answer=(
                    f"Confirmed: ArchAI recommends {workspace.recommendation.recommended_architecture_name}. "
                    f"Recorded rationale: {reasons} Alternatives evaluated: {alternatives}."
                ),
                affected_components=[component.name for component in architecture.components[:4]],
            )

        if any(marker in message for marker in ("what is missing", "what's missing", "wrong here")):
            findings = [issue.message for issue in workspace.consistency_issues[:5]]
            questions = workspace.requirements.open_questions[:4]
            if findings or questions:
                return ArchitectureChatResponse(
                    type="question",
                    answer=(
                        "Confirmed validation findings: "
                        + ("; ".join(findings) if findings else "none")
                        + ". Unknowns requiring clarification: "
                        + ("; ".join(questions) if questions else "none")
                        + "."
                    ),
                )

        if any(marker in message for marker in ("balance", "tradeoff", "trade-off", "versus", " vs ", "against")):
            query = self._meaningful_tokens(request.message)
            candidates = [
                (len(query & self._meaningful_tokens(text)), f"FR-{index:03d}", text)
                for index, text in enumerate(workspace.requirements.functional_requirements, start=1)
            ] + [
                (len(query & self._meaningful_tokens(text)), f"NFR-{index:03d}", text)
                for index, text in enumerate(workspace.requirements.non_functional_requirements, start=1)
            ]
            evidence = sorted(
                (item for item in candidates if item[0] > 0),
                key=lambda item: item[0],
                reverse=True,
            )[:4]
            if evidence:
                evidence_text = "; ".join(f"{item_id}: {text}" for _, item_id, text in evidence)
                transactional = any(
                    marker in message
                    for marker in ("book", "reserv", "order", "payment", "transfer", "transaction")
                )
                freshness = any(
                    marker in message
                    for marker in ("availability", "current", "fresh", "live", "realtime", "real-time")
                )
                if transactional and freshness:
                    recommendation = (
                        "Recommendation: treat the confirmed transaction as the authoritative write, "
                        "recheck the current resource state before committing it, and publish the updated "
                        "read state only after that commit."
                    )
                else:
                    recommendation = (
                        "Recommendation: preserve both confirmed outcomes, define which one is authoritative "
                        "during a conflict, and validate the decision against the linked architecture path."
                    )
                return ArchitectureChatResponse(
                    type="question",
                    answer=(
                        f"Confirmed project evidence: {evidence_text} {recommendation} "
                        "Unknown: the acceptable staleness, conflict policy, and failure behavior are not "
                        "specified unless they appear above; clarify them before treating this advice as a requirement."
                    ),
                )
        return None

    def _evidence_fallback_response(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        request: ArchitectureChatRequest,
    ) -> ArchitectureChatResponse:
        """Answer from the project itself when nothing else could.

        This is the last thing that runs, and it used to be an apology. It now
        searches every recorded artifact for what the question is about and
        reports what it found, so an unrecognised turn still ends in something
        the user can act on.
        """
        from app.services.assistant_intel import ProjectIndex

        index = ProjectIndex(workspace)
        matches = self.deterministic.analysis.search_project(
            workspace, architecture, index, request.message
        )

        if not self.ai_client.settings.ollama_enabled:
            reason = (
                "The local AI model is turned off, so no change was applied and I answered "
                "from the recorded project instead."
            )
        else:
            reason = (
                "I could not match that to a project action and the local AI model did not "
                "answer in time, so no change was applied and I answered from the recorded "
                "project instead."
            )

        if matches:
            found = "\n".join(
                f"  {label}  {truncate(text, 130)}" for _, label, text in matches
            )
            return ArchitectureChatResponse(
                type="question",
                category="QUESTION",
                confidence="medium",
                resolved_by="fallback",
                answer=(
                    f"{reason}\n\n"
                    f"RELATED ITEMS IN {workspace.title.upper()}\n{found}\n\n"
                    "Unknown: I have not interpreted these for you — they are the recorded "
                    "items closest to your wording. Ask about one of them by identifier and "
                    "I can explain it, trace what depends on it, or change it."
                ),
                evidence_ids=[
                    label for _, label, _ in matches if not label.startswith(("component:", "api:", "table:", "adr:", "screen:"))
                ][:20],
                affected_components=[
                    label.split(":", 1)[1]
                    for _, label, _ in matches
                    if label.startswith("component:")
                ][:12],
                recommendations=[
                    "explain everything",
                    "find problems with my architecture",
                    "what am I missing",
                ],
            )

        counts = ", ".join(
            index.count_phrase(target_type)
            for target_type in ("functional_requirement", "non_functional_requirement", "actor")
        )
        # Name the terms that were actually searched for. "There is no record of
        # 'login'" is a real answer to "explain the login function"; "nothing
        # matches that wording" is not.
        subject = strip_query_noise(request.message)
        searched = [term for term in subject.split() if term][:4]
        if searched:
            quoted = ", ".join(f"'{term}'" for term in searched)
            finding = (
                f"Confirmed: nothing recorded in {workspace.title} mentions {quoted}. I "
                f"searched every requirement, actor, entity, component, endpoint, table, "
                f"decision and prototype screen. The project holds {counts}, on the "
                f"{architecture.name} option."
            )
        else:
            finding = (
                f"Unknown: I could not tell what that question is about. {workspace.title} "
                f"holds {counts}, on the {architecture.name} option."
            )
        return ArchitectureChatResponse(
            type="question",
            category="CLARIFICATION",
            confidence="low",
            resolved_by="fallback",
            answer=(
                f"{reason}\n\n"
                f"{finding}\n\n"
                "If it should exist, tell me to add it and I will propose the requirement "
                "first so it stays traceable. Otherwise name an item directly — an "
                "identifier such as FR-002, an actor name, or a component name all work."
            ),
            recommendations=[
                "explain everything",
                "list the functional requirements",
                "suggest missing actors",
                "find problems with my architecture",
                "change the name of actor <old name> to <new name>",
                "add a functional requirement: <who> can <do what>",
            ],
        )

    @staticmethod
    def _is_informational_request(message: str) -> bool:
        lowered = " ".join(message.casefold().split())
        mutation = re.search(
            r"\b(?:add|change|create|delete|migrate|modify|remove|rename|replace|set|switch|update)\b",
            lowered,
        )
        if mutation:
            return False
        return "?" in lowered or bool(re.match(
            r"^(?:analyze|assess|compare|discuss|do|does|explain|how|is|are|summarize|tell|what|when|where|which|who|why|would|could|can|should)\b",
            lowered,
        ))

    def _retrieve_project_context(
        self,
        workspace: WorkspaceResponse,
        request: ArchitectureChatRequest,
    ) -> dict[str, Any]:
        """Retrieve compact current-state evidence relevant to one assistant turn."""
        query = self._meaningful_tokens(
            " ".join(filter(None, [request.message, request.page_context]))
        )

        def ranked(values: list[str], limit: int) -> list[dict[str, str]]:
            scored = [
                (len(query & self._meaningful_tokens(value)), index, value)
                for index, value in enumerate(values, start=1)
            ]
            scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
            return [
                {"id": f"{prefix}-{index:03d}", "text": value}
                for _score, index, value in scored[:limit]
                for prefix in ["FR" if values is workspace.requirements.functional_requirements else "NFR"]
            ]

        context: dict[str, Any] = {
            "title": workspace.title,
            "domain": workspace.requirements.domain,
            "page_context": request.page_context or "unknown",
            "selection": request.selection.model_dump() if request.selection else None,
            "functional_requirements": ranked(
                workspace.requirements.functional_requirements, 8
            ),
            "non_functional_requirements": ranked(
                workspace.requirements.non_functional_requirements, 5
            ),
            "constraints": workspace.requirements.constraints[:5],
            "assumptions": workspace.requirements.assumptions[:4],
            "open_questions": workspace.requirements.open_questions[:4],
            "consistency_issues": [
                issue.model_dump() for issue in workspace.consistency_issues[:4]
            ],
        }
        if query & {"actor", "actors", "role", "roles", "who", "permission"}:
            context["actors"] = [
                self._known_values(actor.model_dump())
                for actor in workspace.requirements.actors[:8]
            ]
            context["workflows"] = [
                workflow.model_dump() for workflow in workspace.requirements.domain_workflows[:8]
            ]
        if query & {"entity", "entities", "database", "data", "record", "table"}:
            context["entities"] = [
                self._known_values(entity.model_dump())
                for entity in workspace.requirements.domain_entities[:8]
            ]
            context["database_entities"] = [
                {"name": entity.name, "description": entity.description}
                for entity in workspace.database_design.entities[:8]
            ]
        if query & {"api", "endpoint", "interface", "request", "route"}:
            context["api_endpoints"] = [
                {
                    "method": endpoint.method,
                    "path": endpoint.path,
                    "purpose": endpoint.purpose,
                    "requirement_ids": endpoint.requirement_ids,
                }
                for group in workspace.api_design.groups
                for endpoint in group.endpoints
                if query & self._meaningful_tokens(
                    " ".join([endpoint.path, endpoint.purpose, endpoint.resource or ""])
                )
            ][:10]
        if query & {"prototype", "screen", "page", "ui", "view"} or request.page_context == "/prototype":
            context["prototype_screens"] = [
                {
                    "id": screen.id,
                    "name": screen.name,
                    "purpose": screen.purpose,
                    "source_requirement_ids": screen.source_requirement_ids,
                    "actor_ids": screen.actor_ids,
                }
                for screen in workspace.prototype.screens[:12]
            ]
        return context

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
            r"(?:please\s+)?add\s+(?:an|a)?\s*"
            r"(?P<kind>non[- ]functional requirement|nfr|functional requirement|fr|constraint|assumption)"
            # Connectors people actually use. Without "for"/"about"/"saying",
            # "add an NFR for audit logging" stored the preposition as the
            # requirement text.
            r"\s*(?::|-|–|—|that\s+|which\s+|for\s+|about\s+|saying\s+|stating\s+|covering\s+|to\s+say\s+)?"
            r"(?P<text>.+)",
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

    @staticmethod
    def _wording_note(target_type: str, text: str) -> str:
        """Flag a requirement that names a topic instead of a capability.

        The item is still added exactly as asked — this only says what is weak
        about the wording, without inventing an actor or an action to fix it.
        """
        if target_type not in {"functional_requirement", "non_functional_requirement"}:
            return ""
        if re.search(
            r"\b(?:can|must|shall|should|will|is|are|has|have|allows?|enables?|provides?|"
            r"supports?|sends?|creates?|updates?|deletes?|views?|manages?)\b",
            text,
            re.IGNORECASE,
        ):
            return ""
        if len(text.split()) > 8:
            return ""
        return (
            f"Note: '{text}' names a topic rather than a capability, so it is not testable "
            "as written. A functional requirement usually reads '<who> can <do what>'. Tell "
            "me who uses it and what they do there and I will reword it — I have not guessed."
        )

    @staticmethod
    def _normalized_addition(
        addition: ArchitectureRequirementAddition,
    ) -> ArchitectureRequirementAddition:
        """Store the item the way the collection reads, without adding words."""
        text = normalize_requirement_text(addition.text)
        if len(text) < 3:
            return addition
        return addition.model_copy(update={"text": text})

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
            "about", "after", "and", "architecture", "are", "change", "current",
            "design", "does", "evidence", "for", "from", "how", "into", "make",
            "only", "project", "should", "system", "that", "the", "this", "using",
            "what", "where", "which", "who", "why", "with", "would", "your",
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
