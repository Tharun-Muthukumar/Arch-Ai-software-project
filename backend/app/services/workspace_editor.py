import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.schemas.domain import (
    Actor,
    ApiEndpoint,
    ArchitectureComponent,
    ConsistencyIssue,
    DatabaseEntity,
    DomainEntityHint,
    SemanticEditSuggestion,
    WorkspaceEditImpact,
    WorkspaceEditPreview,
    WorkspaceEditRequest,
    WorkspaceImpactItem,
    WorkspaceResponse,
)
from app.services.ai.client import OllamaStructuredClient
from app.services.causal_graph import CausalGraphService


class _SemanticEditResult(BaseModel):
    suggested_text: str = Field(min_length=3, max_length=500)
    rationale: str = Field(min_length=3, max_length=500)
    inferred_characteristics: list[str] = Field(default_factory=list, max_length=6)
    assumptions: list[str] = Field(default_factory=list, max_length=4)
    clarification_questions: list[str] = Field(default_factory=list, max_length=5)


@dataclass
class AppliedWorkspaceEdit:
    workspace: WorkspaceResponse
    regenerated_sections: list[str]
    impact: WorkspaceEditImpact
    description: str


class WorkspaceEditService:
    """Validate and apply edits to a copied canonical workspace model."""

    SEMANTIC_TARGETS = {
        "functional_requirement",
        "non_functional_requirement",
        "constraint",
        "assumption",
        "integration",
        "data_characteristic",
    }
    TECHNOLOGIES = {
        "aws", "azure", "cassandra", "docker", "dynamodb", "fastapi", "gcp",
        "kafka", "kubernetes", "mongodb", "mysql", "postgresql", "rabbitmq",
        "react", "redis", "terraform",
    }
    REQUIREMENT_COLLECTIONS = {
        "functional_requirement": ("functional_requirements", "FR"),
        "non_functional_requirement": ("non_functional_requirements", "NFR"),
        "constraint": ("constraints", "CON"),
        "assumption": ("assumptions", "ASM"),
        "integration": ("integrations", "INT"),
        "data_characteristic": ("data_characteristics", "DATA-CHAR"),
    }

    def __init__(self) -> None:
        self.ai_client = OllamaStructuredClient()
        self.graph_service = CausalGraphService()

    def preview(
        self, workspace: WorkspaceResponse, edit: WorkspaceEditRequest
    ) -> WorkspaceEditPreview:
        self._validate_locator(workspace, edit)
        normalized_value = self._normalize_value(edit)
        suggestion = None
        warnings: list[str] = []
        if edit.use_ai and edit.target_type in self.SEMANTIC_TARGETS and isinstance(normalized_value, str):
            suggestion, ai_warnings = self._semantic_suggestion(
                workspace, edit.target_type, normalized_value
            )
            warnings.extend(ai_warnings)
            normalized_value = suggestion.suggested_text
        elif edit.use_ai:
            warnings.append("AI assistance is only used for semantic requirement text edits.")

        normalized_edit = edit.model_copy(update={"value": normalized_value})
        impact = self._impact(workspace, normalized_edit)
        return WorkspaceEditPreview(
            edit=normalized_edit,
            normalized_value=normalized_value,
            impact=impact,
            suggestion=suggestion,
            warnings=warnings,
        )

    def apply(
        self, workspace: WorkspaceResponse, edit: WorkspaceEditRequest
    ) -> AppliedWorkspaceEdit:
        preview = self.preview(workspace, edit.model_copy(update={"use_ai": False}))
        updated = workspace.model_copy(deep=True)
        normalized = preview.normalized_value

        if edit.target_type in self.REQUIREMENT_COLLECTIONS:
            attribute, prefix = self.REQUIREMENT_COLLECTIONS[edit.target_type]
            values = list(getattr(updated.requirements, attribute))
            self._edit_list(values, edit, normalized, prefix)
            setattr(updated.requirements, attribute, self._dedupe_strings(values))
            if isinstance(normalized, str) and edit.operation in {"add", "update"}:
                updated.requirements.data_characteristics = self._dedupe_strings(
                    [
                        *updated.requirements.data_characteristics,
                        *self._infer_characteristics(normalized),
                    ]
                )
        elif edit.target_type == "actor":
            actors = list(updated.requirements.actors)
            self._edit_model_list(actors, edit, normalized, Actor, "ACTOR")
            self._ensure_unique_names(actors, "actor")
            updated.requirements.actors = actors
        elif edit.target_type == "domain_entity":
            entities = list(updated.requirements.domain_entities)
            self._edit_model_list(
                entities, edit, normalized, DomainEntityHint, "ENTITY-HINT"
            )
            self._ensure_unique_names(entities, "domain entity")
            updated.requirements.domain_entities = entities
        elif edit.target_type == "architecture_component":
            architecture = self._architecture(updated, edit.parent_id)
            components = list(architecture.components)
            deleted_name = None
            if edit.operation == "delete":
                deleted_name = components[
                    self._index(edit.target_id, "COMPONENT", len(components))
                ].name
            self._edit_model_list(
                components, edit, normalized, ArchitectureComponent, "COMPONENT"
            )
            if deleted_name:
                for component in components:
                    component.interactions = [
                        interaction
                        for interaction in component.interactions
                        if deleted_name.casefold() not in interaction.casefold()
                    ]
            self._ensure_unique_names(components, "architecture component")
            architecture.components = components
        elif edit.target_type == "api_endpoint":
            group = self._api_group(updated, edit.parent_id)
            endpoints = list(group.endpoints)
            self._edit_model_list(endpoints, edit, normalized, ApiEndpoint, "ENDPOINT")
            group.endpoints = endpoints
            self._validate_endpoints(updated)
        elif edit.target_type == "database_entity":
            entities = list(updated.database_design.entities)
            deleted_name = None
            if edit.operation == "delete":
                deleted_name = entities[self._index(edit.target_id, "ENTITY", len(entities))].name
            self._edit_model_list(entities, edit, normalized, DatabaseEntity, "ENTITY")
            self._ensure_unique_names(entities, "database entity")
            updated.database_design.entities = entities
            if deleted_name:
                updated.database_design.relationships = [
                    relation
                    for relation in updated.database_design.relationships
                    if deleted_name not in {relation.source, relation.target}
                ]
            self._validate_database(updated)
        elif edit.target_type == "deployment":
            self._edit_deployment(updated, normalized)
        elif edit.target_type == "diagram_layout":
            self._edit_diagram_layout(updated, edit, normalized)

        issues = self.consistency_issues(updated)
        errors = [issue for issue in issues if issue.severity == "error"]
        if errors:
            raise ValueError(errors[0].message)

        return AppliedWorkspaceEdit(
            workspace=updated,
            regenerated_sections=self._regeneration_sections(edit.target_type),
            impact=preview.impact,
            description=self._description(edit, normalized),
        )

    def consistency_issues(self, workspace: WorkspaceResponse) -> list[ConsistencyIssue]:
        issues: list[ConsistencyIssue] = []
        requirements = workspace.requirements
        for label, values in (
            ("functional requirement", requirements.functional_requirements),
            ("non-functional requirement", requirements.non_functional_requirements),
        ):
            normalized = [self._key(value) for value in values]
            if len(normalized) != len(set(normalized)):
                issues.append(
                    ConsistencyIssue(
                        code="duplicate-requirement",
                        severity="error",
                        message=f"Duplicate {label} text must be resolved before saving.",
                    )
                )

        entity_names = {entity.name.casefold() for entity in workspace.database_design.entities}
        for index, relation in enumerate(workspace.database_design.relationships, start=1):
            missing = [
                name
                for name in (relation.source, relation.target)
                if name.casefold() not in entity_names
            ]
            if missing:
                issues.append(
                    ConsistencyIssue(
                        code="broken-database-relationship",
                        severity="error",
                        message=f"Database relationship {index} references missing entity: {', '.join(missing)}.",
                        related_ids=[f"DB-REL-{index:03d}"],
                    )
                )

        for group_index, group in enumerate(workspace.api_design.groups, start=1):
            seen_endpoints: set[tuple[str, str]] = set()
            for endpoint_index, endpoint in enumerate(group.endpoints, start=1):
                key = (endpoint.method.upper(), endpoint.path.casefold())
                if key in seen_endpoints:
                    issues.append(
                        ConsistencyIssue(
                            code="duplicate-api-endpoint",
                            severity="error",
                            message=f"{endpoint.method.upper()} {endpoint.path} is duplicated in {group.name}.",
                            related_ids=[f"API-{group_index:03d}-EP-{endpoint_index:03d}"],
                        )
                    )
                seen_endpoints.add(key)

        if workspace.causal_graph:
            for node_id in workspace.causal_graph.orphan_node_ids:
                issues.append(
                    ConsistencyIssue(
                        code="orphan-component",
                        severity="warning",
                        message=f"{node_id} has no validated originating requirement.",
                        related_ids=[node_id],
                    )
                )
        issues.extend(self._cross_artifact_warnings(workspace))
        return issues

    def _cross_artifact_warnings(self, workspace: WorkspaceResponse) -> list[ConsistencyIssue]:
        """Cross-artifact validation from business context down to deployment.

        Every check compares generated artifacts against the validated
        requirements and reports warning-level (never blocking) findings, so
        contradictions surface instead of silently shipping.
        """
        from app.services.domain_inference import (
            auth_evidence,
            has_global_markers,
            payment_evidence_level,
            singularize,
            tokenize,
        )

        warnings: list[ConsistencyIssue] = []
        requirements = workspace.requirements
        req_text = " ".join(
            requirements.functional_requirements
            + requirements.non_functional_requirements
            + requirements.constraints
        )
        lower_text = req_text.casefold()
        entity_tokens: set[str] = set()
        for entity in workspace.database_design.entities:
            entity_tokens |= {token for token in tokenize(entity.name) if len(token) > 2}
        group_tokens: set[str] = set()
        for group in workspace.api_design.groups:
            group_tokens |= {token for token in tokenize(group.name) if len(token) > 2}

        # Major capabilities must exist as entities or API groups. Each
        # keyword maps to tokens that acceptably cover it, so related
        # concepts (production covering manufacturing) do not false-positive.
        capability_coverage: tuple[tuple[str, set[str]], ...] = (
            ("manufacturing", {"manufacturing", "production", "facility", "plant"}),
            ("production", {"production", "manufacturing", "plant"}),
            ("bottling", {"bottling", "bottler", "partner"}),
            ("facility", {"facility", "plant", "warehouse", "site"}),
            ("warehouse", {"warehouse", "storage", "inventory"}),
            ("inventory", {"inventory", "stock", "warehouse"}),
            ("shipment", {"shipment", "delivery", "distribution", "logistics"}),
            ("forecast", {"forecast", "planning", "demand"}),
            ("distributor", {"distributor", "partner", "dealer"}),
            ("retailer", {"retailer", "store", "customer"}),
        )
        model_tokens = entity_tokens | group_tokens
        req_token_set = {
            singularize(token) for token in tokenize(req_text) if len(token) > 2
        }
        uncovered = [
            keyword
            for keyword, acceptable in capability_coverage
            if singularize(keyword) in req_token_set and not (acceptable & model_tokens)
        ]
        if uncovered:
            warnings.append(
                ConsistencyIssue(
                    code="capability-without-model",
                    severity="warning",
                    message=(
                        "Capabilities mentioned in requirements have no matching "
                        f"domain entity or API group: {', '.join(uncovered)}. "
                        "Confirm whether the model is incomplete."
                    ),
                )
            )

        # Global operation requires a multi-region deployment plan.
        if has_global_markers(*requirements.constraints, *requirements.non_functional_requirements):
            if len(workspace.deployment_plan.regions) < 2:
                warnings.append(
                    ConsistencyIssue(
                        code="single-region-for-global",
                        severity="warning",
                        message=(
                            "Global or multi-region operation is required but the "
                            "deployment plan names fewer than two regions."
                        ),
                    )
                )

        # Stated identity controls must not leave anonymous surfaces.
        if auth_evidence(req_text):
            public_markers = ("login", "refresh", "signup", "token", "health", "public")
            exposed = [
                f"{endpoint.method.upper()} {endpoint.path}"
                for group in workspace.api_design.groups
                for endpoint in group.endpoints
                if endpoint.auth_required is not True
                and not any(marker in endpoint.path.lower() for marker in public_markers)
            ]
            if exposed:
                warnings.append(
                    ConsistencyIssue(
                        code="anonymous-auth-surface",
                        severity="warning",
                        message=(
                            "Identity controls are required but these endpoints allow "
                            f"anonymous access: {', '.join(exposed[:4])}."
                            + ("…" if len(exposed) > 4 else "")
                        ),
                    )
                )

        # Payment surfaces require payment evidence in the requirements.
        payment_surface = (
            any("payment" in token for token in entity_tokens | group_tokens)
            or any(
                "pay" in endpoint.path.lower() or "checkout" in endpoint.path.lower()
                for group in workspace.api_design.groups
                for endpoint in group.endpoints
            )
        )
        if payment_surface and payment_evidence_level(req_text) == 0:
            warnings.append(
                ConsistencyIssue(
                    code="unjustified-payment-surface",
                    severity="warning",
                    message=(
                        "Payment tables or endpoints exist without payment "
                        "evidence in the requirements; confirm they belong to "
                        "this domain."
                    ),
                )
            )

        # Every domain entity should resolve to an API capability, where
        # capability means a matching group, endpoint path, or endpoint purpose.
        exempt_groups = {"authentication", "users"}
        api_tokens: set[str] = set()
        for group in workspace.api_design.groups:
            if group.name.casefold() in exempt_groups:
                continue
            api_tokens |= {token for token in tokenize(group.name) if len(token) > 3}
            for endpoint in group.endpoints:
                api_tokens |= {token for token in tokenize(endpoint.path) if len(token) > 3}
                api_tokens |= {token for token in tokenize(endpoint.purpose) if len(token) > 3}
        for entity in workspace.database_design.entities:
            name_tokens = {token for token in tokenize(entity.name) if len(token) > 3}
            if not name_tokens:
                continue
            covered = bool(name_tokens & api_tokens)
            if not covered and entity.name not in {"users", "audit_logs"}:
                warnings.append(
                    ConsistencyIssue(
                        code="entity-without-api",
                        severity="warning",
                        message=(
                            f"Domain entity '{entity.name}' has no matching API "
                            "group; confirm it is reachable through the contract."
                        ),
                    )
                )

        # Every domain entity should declare an owning bounded context.
        for entity in workspace.database_design.entities:
            if not entity.bounded_context:
                warnings.append(
                    ConsistencyIssue(
                        code="entity-without-context",
                        severity="warning",
                        message=(
                            f"Domain entity '{entity.name}' has no owning "
                            "bounded context; assign one to keep ownership clear."
                        ),
                    )
                )

        # Event-driven claims require event evidence in the requirements.
        recommended_id = workspace.recommendation.recommended_architecture_id
        if any(
            marker in recommended_id
            for marker in ("event", "microservice")
        ) and not any(
            marker in lower_text
            for marker in ("real-time", "realtime", "stream", "telemetry", "event", "sensor", "async")
        ):
            warnings.append(
                ConsistencyIssue(
                    code="event-claim-without-events",
                    severity="warning",
                    message=(
                        "The recommended architecture is event-driven but no "
                        "event-driven workload is stated in the requirements."
                    ),
                )
            )
        return warnings

    def _semantic_suggestion(
        self, workspace: WorkspaceResponse, target_type: str, raw_text: str
    ) -> tuple[SemanticEditSuggestion, list[str]]:
        warnings: list[str] = []
        generated = self.ai_client.generate(
            "workspace-semantic-edit",
            {
                "raw_requirement": {
                    "raw_edit": raw_text,
                    "target_type": target_type,
                    "project_domain": workspace.requirements.domain,
                    "project_summary": workspace.requirements.summary,
                }
            },
            response_schema=_SemanticEditResult.model_json_schema(),
            num_predict=320,
            num_ctx=4096,
            minimum_timeout_seconds=60,
        )
        if generated is not None:
            try:
                result = _SemanticEditResult.model_validate(generated)
                if self._suggestion_is_grounded(raw_text, result.suggested_text):
                    characteristics = self._dedupe_strings(
                        [
                            *self._grounded_characteristics(
                                raw_text, result.inferred_characteristics
                            ),
                            *self._infer_characteristics(raw_text),
                        ]
                    )
                    return SemanticEditSuggestion(
                        suggested_text=self._clean_text(result.suggested_text),
                        rationale=self._clean_text(result.rationale),
                        inferred_characteristics=characteristics,
                        assumptions=[self._clean_text(item) for item in result.assumptions],
                        clarification_questions=[
                            self._as_question(item)
                            for item in self._dedupe_strings(
                                [
                                    *result.clarification_questions,
                                    *self._deterministic_questions(raw_text),
                                ]
                            )
                            if item.strip()
                        ],
                        source="ollama",
                    ), warnings
                warnings.append(
                    "Ollama's rewrite introduced or lost unsupported detail, so the original edit was preserved."
                )
            except ValidationError:
                warnings.append(
                    "Ollama returned a malformed suggestion, so the original edit was preserved."
                )
        else:
            warnings.append(
                "Ollama is unavailable. The edit is preserved and deterministic validation will still run."
            )

        return SemanticEditSuggestion(
            suggested_text=raw_text,
            rationale="The original wording is preserved because no validated AI rewrite is available.",
            inferred_characteristics=self._infer_characteristics(raw_text),
            clarification_questions=self._deterministic_questions(raw_text),
            source="deterministic-fallback",
        ), warnings

    def _impact(
        self, workspace: WorkspaceResponse, edit: WorkspaceEditRequest
    ) -> WorkspaceEditImpact:
        areas = self._impact_areas(edit.target_type)
        direct_ids: list[str] = []
        indirect_ids: list[str] = []
        artifacts = [item.area.casefold().replace(" ", "_") for item in areas if item.level != "none"]
        graph = workspace.causal_graph
        if graph:
            node_id = self._graph_node_id(workspace, edit)
            trace = self.graph_service.explain(graph, node_id) if node_id else None
            if trace:
                direct_ids = self._dedupe_strings(
                    [node.id for node in [*trace.upstream, *trace.downstream]][:12]
                )
                direct_set = set(direct_ids[:4])
                indirect_ids = [node_id for node_id in direct_ids[4:] if node_id not in direct_set]
                direct_ids = direct_ids[:4]
                artifacts = self._dedupe_strings([*artifacts, *trace.affected_artifacts])
            elif isinstance(edit.value, str):
                direct, indirect = self.graph_service.impacted_nodes_for_text(graph, edit.value)
                direct_ids = [node.id for node in direct[:4]]
                indirect_ids = [node.id for node in indirect[:12]]

        destructive = edit.operation == "delete"
        return WorkspaceEditImpact(
            items=areas,
            directly_affected_node_ids=direct_ids,
            indirectly_affected_node_ids=indirect_ids,
            affected_artifacts=artifacts,
            requires_confirmation=destructive or any(item.level == "major" for item in areas),
        )

    def _impact_areas(self, target_type: str) -> list[WorkspaceImpactItem]:
        definitions: dict[str, list[tuple[str, str, str]]] = {
            "functional_requirement": [
                ("Requirements", "major", "The canonical requirement set changes."),
                ("Architecture", "moderate", "Service boundaries are re-evaluated."),
                ("API", "major", "Related operations are regenerated."),
                ("Database", "moderate", "Supporting entities and relationships are re-evaluated."),
                ("Deployment", "minor", "Runtime needs are recalculated when relevant."),
                ("Diagrams", "major", "Requirement-driven diagrams are synchronized."),
            ],
            "non_functional_requirement": [
                ("Requirements", "major", "The quality requirement set changes."),
                ("Architecture", "moderate", "Architecture fitness is recalculated."),
                ("Deployment", "moderate", "Operational controls may change."),
                ("Scoring", "moderate", "Deterministic quality scores are recalculated."),
                ("Diagrams", "minor", "Affected technical views are synchronized."),
            ],
            "actor": [
                ("Requirements", "major", "Actors and responsibilities change."),
                ("API", "moderate", "Actor-facing operations are re-evaluated."),
                ("Diagrams", "major", "Use-case and sequence views are synchronized."),
                ("Permissions", "moderate", "Responsibility boundaries need review."),
            ],
            "architecture_component": [
                ("Architecture", "major", "The selected option's component model changes."),
                ("Scoring", "moderate", "Architecture comparison is recalculated."),
                ("Diagrams", "major", "Component and deployment views are synchronized."),
                ("Causal graph", "major", "Dependencies and justification paths are rebuilt."),
            ],
            "api_endpoint": [
                ("API", "major", "The canonical API contract changes."),
                ("Documentation", "moderate", "API documentation is synchronized."),
                ("Causal graph", "moderate", "Endpoint ownership links are revalidated."),
            ],
            "database_entity": [
                ("Database", "major", "The canonical data model changes."),
                ("API", "moderate", "Endpoints using this entity require review."),
                ("Diagrams", "major", "Class and ER views are synchronized."),
                ("Causal graph", "major", "Persistence links are rebuilt."),
            ],
            "deployment": [
                ("Deployment", "major", "The runtime plan changes."),
                ("Cost", "moderate", "Deterministic estimates use the new deployment inputs."),
                ("Resilience", "moderate", "Failure and availability analysis must be refreshed."),
                ("Diagrams", "moderate", "The deployment view is synchronized."),
            ],
            "diagram_layout": [
                ("Diagram layout", "visual", "Only saved positions and notes change."),
                ("Architecture", "none", "The underlying architecture is unchanged."),
            ],
        }
        requirement_default = [
            ("Requirements", "major", "The structured project model changes."),
            ("Architecture", "moderate", "Relevant architecture decisions are re-evaluated."),
            ("Diagrams", "moderate", "Dependent views are synchronized."),
            ("Causal graph", "major", "Dependency paths are rebuilt."),
        ]
        source = definitions.get(target_type, requirement_default)
        return [WorkspaceImpactItem(area=area, level=level, summary=summary) for area, level, summary in source]

    def _regeneration_sections(self, target_type: str) -> list[str]:
        if target_type == "diagram_layout":
            return []
        if target_type == "architecture_component":
            return ["comparison", "recommendation", "diagrams", "causal_graph", "documentation"]
        if target_type == "api_endpoint":
            return ["causal_graph", "documentation"]
        if target_type == "database_entity":
            return ["diagrams", "causal_graph", "documentation"]
        if target_type == "deployment":
            return ["diagrams", "causal_graph", "documentation"]
        if target_type == "non_functional_requirement":
            return [
                "clarifications", "architectures", "comparison", "recommendation",
                "deployment", "diagrams", "causal_graph", "documentation",
            ]
        return [
            "clarifications", "architectures", "comparison", "recommendation",
            "database", "api", "deployment", "diagrams", "causal_graph", "documentation",
        ]

    def _validate_locator(self, workspace: WorkspaceResponse, edit: WorkspaceEditRequest) -> None:
        if edit.operation == "add":
            if edit.target_type == "architecture_component":
                self._architecture(workspace, edit.parent_id)
            elif edit.target_type == "api_endpoint":
                self._api_group(workspace, edit.parent_id)
            return
        if edit.target_type in self.REQUIREMENT_COLLECTIONS:
            attribute, prefix = self.REQUIREMENT_COLLECTIONS[edit.target_type]
            self._index(edit.target_id, prefix, len(getattr(workspace.requirements, attribute)))
        elif edit.target_type == "actor":
            self._index(edit.target_id, "ACTOR", len(workspace.requirements.actors))
        elif edit.target_type == "domain_entity":
            self._index(edit.target_id, "ENTITY-HINT", len(workspace.requirements.domain_entities))
        elif edit.target_type == "architecture_component":
            architecture = self._architecture(workspace, edit.parent_id)
            self._index(edit.target_id, "COMPONENT", len(architecture.components))
        elif edit.target_type == "api_endpoint":
            group = self._api_group(workspace, edit.parent_id)
            self._index(edit.target_id, "ENDPOINT", len(group.endpoints))
        elif edit.target_type == "database_entity":
            self._index(edit.target_id, "ENTITY", len(workspace.database_design.entities))

    def _normalize_value(self, edit: WorkspaceEditRequest) -> str | dict[str, Any] | None:
        if isinstance(edit.value, str):
            value = self._clean_text(edit.value)
            if not value:
                raise ValueError("The edited value cannot be empty.")
            if len(value) > 2000:
                raise ValueError("The edited value is too long.")
            return value
        if isinstance(edit.value, dict):
            return edit.value
        return None

    def _edit_list(
        self,
        values: list[str],
        edit: WorkspaceEditRequest,
        normalized: str | dict[str, Any] | None,
        prefix: str,
    ) -> None:
        if edit.operation == "add":
            if not isinstance(normalized, str):
                raise ValueError("A text value is required.")
            values.append(normalized)
            return
        index = self._index(edit.target_id, prefix, len(values))
        if edit.operation == "update":
            if not isinstance(normalized, str):
                raise ValueError("A text value is required.")
            values[index] = normalized
        elif edit.operation == "delete":
            values.pop(index)
        else:
            item = values.pop(index)
            values.insert(min(edit.destination_index or 0, len(values)), item)

    def _edit_model_list(
        self,
        values: list[Any],
        edit: WorkspaceEditRequest,
        normalized: str | dict[str, Any] | None,
        model: type[BaseModel],
        prefix: str,
    ) -> None:
        if edit.operation == "add":
            if not isinstance(normalized, dict):
                raise ValueError("A structured value is required.")
            values.append(model.model_validate(normalized))
            return
        index = self._index(edit.target_id, prefix, len(values))
        if edit.operation == "update":
            if not isinstance(normalized, dict):
                raise ValueError("A structured value is required.")
            values[index] = model.model_validate(normalized)
        elif edit.operation == "delete":
            values.pop(index)
        else:
            item = values.pop(index)
            values.insert(min(edit.destination_index or 0, len(values)), item)

    def _edit_deployment(
        self, workspace: WorkspaceResponse, normalized: str | dict[str, Any] | None
    ) -> None:
        if not isinstance(normalized, dict):
            raise ValueError("Deployment edits require a structured value.")
        allowed = {
            "deployment_model", "replicas", "regions", "deployment_strategy",
            "availability_configuration", "target_stack", "docker_services", "kubernetes_modules",
            "cicd_pipeline", "observability", "scaling_strategy", "security_controls",
            "cloud_recommendation", "stack_rationale",
        }
        unknown = set(normalized) - allowed
        if unknown:
            raise ValueError(f"Unsupported deployment fields: {', '.join(sorted(unknown))}.")
        payload = workspace.deployment_plan.model_dump()
        payload.update(normalized)
        workspace.deployment_plan = type(workspace.deployment_plan).model_validate(payload)

    def _edit_diagram_layout(
        self,
        workspace: WorkspaceResponse,
        edit: WorkspaceEditRequest,
        normalized: str | dict[str, Any] | None,
    ) -> None:
        if not edit.target_id or not isinstance(normalized, dict):
            raise ValueError("Diagram layout edits require a diagram key and layout object.")
        if edit.target_id not in workspace.diagrams and not edit.target_id.startswith("architecture:"):
            raise ValueError("The selected diagram does not exist.")
        layouts = dict(workspace.diagram_layouts)
        layouts[edit.target_id] = normalized
        workspace.diagram_layouts = layouts

    def _architecture(self, workspace: WorkspaceResponse, architecture_id: str | None):
        architecture = next(
            (item for item in workspace.architectures if item.id == architecture_id), None
        )
        if architecture is None:
            raise ValueError("The selected architecture option does not exist.")
        return architecture

    def _api_group(self, workspace: WorkspaceResponse, parent_id: str | None):
        if parent_id is None:
            raise ValueError("An API group is required.")
        try:
            index = int(parent_id)
        except ValueError as exc:
            raise ValueError("The API group identifier is invalid.") from exc
        if index < 0 or index >= len(workspace.api_design.groups):
            raise ValueError("The selected API group does not exist.")
        return workspace.api_design.groups[index]

    def _validate_endpoints(self, workspace: WorkspaceResponse) -> None:
        allowed_methods = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
        valid_requirement_ids = {
            *[f"FR-{index:03d}" for index in range(1, len(workspace.requirements.functional_requirements) + 1)],
            *[f"NFR-{index:03d}" for index in range(1, len(workspace.requirements.non_functional_requirements) + 1)],
            *[f"CON-{index:03d}" for index in range(1, len(workspace.requirements.constraints) + 1)],
            *[f"ASM-{index:03d}" for index in range(1, len(workspace.requirements.assumptions) + 1)],
        }
        recommended = next(
            (
                item for item in workspace.architectures
                if item.id == workspace.recommendation.recommended_architecture_id
            ),
            None,
        )
        component_names = {item.name for item in recommended.components} if recommended else set()
        for group in workspace.api_design.groups:
            seen: set[tuple[str, str]] = set()
            for endpoint in group.endpoints:
                endpoint.method = endpoint.method.upper()
                if endpoint.method not in allowed_methods:
                    raise ValueError(f"Unsupported HTTP method: {endpoint.method}.")
                if not endpoint.path.startswith("/") or " " in endpoint.path:
                    raise ValueError("API paths must start with / and cannot contain spaces.")
                key = (endpoint.method, endpoint.path.casefold())
                if key in seen:
                    raise ValueError(f"Duplicate API endpoint: {endpoint.method} {endpoint.path}.")
                seen.add(key)
                unknown_requirements = set(endpoint.requirement_ids) - valid_requirement_ids
                if unknown_requirements:
                    raise ValueError(
                        "API requirement associations must reference existing IDs: "
                        + ", ".join(sorted(unknown_requirements))
                        + "."
                    )
                if endpoint.service and endpoint.service not in component_names:
                    raise ValueError(
                        f"API owner {endpoint.service} is not a component in the recommended architecture."
                    )

    def _validate_database(self, workspace: WorkspaceResponse) -> None:
        names = {entity.name for entity in workspace.database_design.entities}
        for relation in workspace.database_design.relationships:
            if relation.source not in names or relation.target not in names:
                raise ValueError("Database relationships must reference existing entities.")
        for entity in workspace.database_design.entities:
            if not entity.fields:
                raise ValueError(f"Database entity {entity.name} must contain at least one field.")
            field_names = [field.name.casefold() for field in entity.fields]
            if len(field_names) != len(set(field_names)):
                raise ValueError(f"Database entity {entity.name} contains duplicate fields.")

    def _graph_node_id(self, workspace: WorkspaceResponse, edit: WorkspaceEditRequest) -> str | None:
        if edit.target_type in self.REQUIREMENT_COLLECTIONS:
            _, prefix = self.REQUIREMENT_COLLECTIONS[edit.target_type]
            if prefix in {"FR", "NFR", "CON", "ASM"}:
                index = self._index(edit.target_id, prefix, 100000) + 1 if edit.target_id else 0
                return f"{prefix}-{index:03d}" if index else None
        if edit.target_type == "database_entity" and edit.target_id:
            index = self._index(edit.target_id, "ENTITY", 100000) + 1
            return f"DATA-{index:03d}"
        if edit.target_type == "deployment":
            return "INFRA-DEPLOYMENT"
        if edit.target_type == "architecture_component" and edit.parent_id and edit.target_id:
            architecture = self._architecture(workspace, edit.parent_id)
            index = self._index(edit.target_id, "COMPONENT", len(architecture.components))
            name = architecture.components[index].name
            if workspace.causal_graph:
                match = next(
                    (
                        node for node in workspace.causal_graph.nodes
                        if node.name == name and node.metadata.get("architecture_id") == edit.parent_id
                    ),
                    None,
                )
                return match.id if match else None
        if edit.target_type == "api_endpoint" and edit.parent_id and workspace.causal_graph:
            group = self._api_group(workspace, edit.parent_id)
            match = next(
                (node for node in workspace.causal_graph.nodes if node.type == "api" and node.name == group.name),
                None,
            )
            return match.id if match else None
        return None

    def _index(self, target_id: str | None, prefix: str, length: int) -> int:
        if not target_id:
            raise ValueError("A target identifier is required.")
        match = re.search(r"(\d+)$", target_id)
        if not match:
            raise ValueError(f"Invalid {prefix} identifier.")
        raw = int(match.group(1))
        index = raw - 1 if target_id.upper().startswith(prefix.upper() + "-") else raw
        if index < 0 or index >= length:
            raise ValueError(f"The selected {prefix.lower()} item does not exist.")
        return index

    def _ensure_unique_names(self, values: list[Any], label: str) -> None:
        names = [item.name.strip().casefold() for item in values]
        if any(not name for name in names):
            raise ValueError(f"Every {label} requires a name.")
        if len(names) != len(set(names)):
            raise ValueError(f"{label.title()} names must be unique.")

    def _suggestion_is_grounded(self, raw: str, suggestion: str) -> bool:
        raw_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", raw))
        suggestion_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", suggestion))
        if suggestion_numbers - raw_numbers:
            return False
        raw_lower = raw.casefold()
        suggestion_lower = suggestion.casefold()
        for technology in self.TECHNOLOGIES:
            if technology in suggestion_lower and technology not in raw_lower:
                return False
        raw_tokens = self._significant_tokens(raw)
        suggestion_tokens = self._significant_tokens(suggestion)
        return not raw_tokens or len(raw_tokens & suggestion_tokens) / len(raw_tokens) >= 0.45

    def _grounded_characteristics(self, raw: str, values: list[str]) -> list[str]:
        inferred = self._infer_characteristics(raw)
        categories = {value.split(":", 1)[0].casefold() for value in inferred}
        return [
            self._clean_text(value)
            for value in values
            if any(category in value.casefold() for category in categories)
        ]

    def _infer_characteristics(self, value: str) -> list[str]:
        lower = value.casefold()
        result: list[str] = []
        if any(marker in lower for marker in ("real-time", "realtime", "live", "immediate")):
            result.append("Real-time behavior: live updates are explicitly required; the acceptable update interval remains unknown.")
        if any(marker in lower for marker in ("location", "geospatial", "coordinates", "nearby", "map")):
            result.append("Geospatial data: the requirement explicitly uses location-aware information.")
        if any(marker in lower for marker in ("telemetry", "event stream", "streaming")):
            result.append("Event processing: the requirement explicitly describes streaming or telemetry data.")
        if any(marker in lower for marker in ("offline", "disconnected", "without connectivity")):
            result.append("Offline operation: behavior during lost connectivity must be defined.")
        return result

    def _deterministic_questions(self, value: str) -> list[str]:
        lower = value.casefold()
        questions: list[str] = []
        if any(marker in lower for marker in ("real-time", "realtime", "live")) and not re.search(r"\b\d+\s*(ms|millisecond|second|minute)", lower):
            questions.append("What update interval is acceptable for the live behavior?")
        if "monitor" in lower and len(self._significant_tokens(value)) < 5:
            questions.append("What should be monitored, and who needs to respond to it?")
        return questions

    def _description(
        self, edit: WorkspaceEditRequest, value: str | dict[str, Any] | None
    ) -> str:
        subject = edit.target_type.replace("_", " ")
        if isinstance(value, str):
            detail = value[:80]
        elif isinstance(value, dict):
            detail = str(value.get("name") or value.get("path") or subject)
        else:
            detail = edit.target_id or subject
        return f"{edit.operation.title()} {subject}: {detail}"

    def _clean_text(self, value: str) -> str:
        return " ".join(value.strip().split())

    def _as_question(self, value: str) -> str:
        cleaned = self._clean_text(value).rstrip(".?")
        return f"{cleaned}?"

    def _key(self, value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))

    def _significant_tokens(self, value: str) -> set[str]:
        stop = {
            "able", "allow", "and", "are", "can", "for", "from", "into", "should",
            "system", "that", "the", "their", "them", "they", "this", "to", "with",
        }
        return {
            token for token in re.findall(r"[a-z][a-z0-9-]+", value.casefold())
            if token not in stop and len(token) > 2
        }

    def _dedupe_strings(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            clean = self._clean_text(value)
            key = clean.casefold()
            if clean and key not in seen:
                seen.add(key)
                result.append(clean)
        return result
