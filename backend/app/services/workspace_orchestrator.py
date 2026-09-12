import copy
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable

from app.models.workspace import Workspace
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.domain import (
    ApiDesign,
    ArchitectureChangeProposal,
    ArchitectureChatRequest,
    ArchitectureChatResponse,
    ArchitectureDecisionRecord,
    ArchitectureOption,
    ArchitectureRiskAnalysis,
    CausalGraph,
    CausalGraphTrace,
    ClarificationPlan,
    ComparisonResult,
    DatabaseDesign,
    DeploymentPlan,
    DiagramArtifact,
    ImpactAssessment,
    RecommendationResult,
    RequirementModel,
    WorkspaceEditImpact,
    WorkspaceEditPreview,
    WorkspaceEditRequest,
    WorkspaceImpactItem,
    WorkspaceMutationResponse,
    WorkspaceCreateRequest,
    WorkspaceResponse,
    CURRENT_REQUIREMENT_MODEL_VERSION,
)
from app.services.api_generator import ApiGenerator
from app.services.architecture_generator import ArchitectureGenerator
from app.services.clarification_engine import ClarificationEngine
from app.services.causal_graph import GRAPH_VERSION, CausalGraphService
from app.services.comparison_engine import ComparisonEngine
from app.services.database_generator import DatabaseGenerator
from app.services.deployment_generator import DeploymentGenerator
from app.services.decision_config import ARCHITECTURE_DECISION_MODEL_VERSION
from app.services.diagram_generator import DiagramGenerator
from app.services.documentation_generator import DocumentationGenerator
from app.services.impact_analyzer import ImpactAnalyzer
from app.services.recommendation_engine import RecommendationEngine
from app.services.requirement_analyzer import RequirementAnalyzer
from app.services.workspace_editor import WorkspaceEditService
from app.services.architecture_assistant import ArchitectureAssistantService
from app.services.project_signals import clarification_category, hydrate_project_signals
from app.services.generation_runtime import (
    GENERATION_TELEMETRY,
    PROJECT_GENERATION_CACHE,
    CompactProjectContext,
)

ProgressCallback = Callable[[str, dict[str, Any]], None]


class WorkspaceOrchestrator:
    def __init__(self, repository: WorkspaceRepository) -> None:
        self.repository = repository
        self.requirement_analyzer = RequirementAnalyzer()
        self.clarification_engine = ClarificationEngine()
        self.causal_graph_service = CausalGraphService()
        self.architecture_generator = ArchitectureGenerator()
        self.comparison_engine = ComparisonEngine()
        self.recommendation_engine = RecommendationEngine()
        self.database_generator = DatabaseGenerator()
        self.api_generator = ApiGenerator()
        self.deployment_generator = DeploymentGenerator()
        self.diagram_generator = DiagramGenerator()
        self.documentation_generator = DocumentationGenerator()
        self.impact_analyzer = ImpactAnalyzer()
        self.workspace_editor = WorkspaceEditService()
        self.architecture_assistant = ArchitectureAssistantService()

    def list_workspaces(
        self, active_workspace_id: str | None = None
    ) -> list[WorkspaceResponse]:
        """List quickly and migrate at most the workspace being viewed.

        Requirement-model migrations can legitimately invoke extraction.
        Running that work for every saved project during a sidebar refresh
        made a 38-project account perform 38 unrelated generations. The
        active project upgrades now; the rest upgrade lazily when selected.
        """
        workspaces = self.repository.list()
        upgrade_id = active_workspace_id or (workspaces[0].id if workspaces else None)
        return [
            self._to_response(
                self._upgrade_legacy_workspace(workspace)
                if workspace.id == upgrade_id
                else workspace
            )
            for workspace in workspaces
        ]

    def get_workspace(self, workspace_id: str) -> WorkspaceResponse | None:
        workspace = self.repository.get(workspace_id)
        if workspace is None:
            return None
        workspace = self._upgrade_legacy_workspace(workspace)
        return self._to_response(workspace)

    def architecture_chat(
        self, workspace_id: str, request: ArchitectureChatRequest
    ) -> ArchitectureChatResponse | None:
        workspace = self.get_workspace(workspace_id)
        if workspace is None:
            return None
        return self.architecture_assistant.chat(workspace, request)

    def analyze_architecture_risks(
        self,
        workspace_id: str,
        architecture_id: str | None = None,
        *,
        include_ai: bool = False,
    ) -> ArchitectureRiskAnalysis | None:
        workspace = self.get_workspace(workspace_id)
        if workspace is None:
            return None
        return self.architecture_assistant.analyze_risks(
            workspace,
            architecture_id,
            include_ai=include_ai,
        )

    def apply_architecture_proposal(
        self, workspace_id: str, proposal: ArchitectureChangeProposal
    ) -> WorkspaceMutationResponse | None:
        workspace = self.repository.get(workspace_id)
        if workspace is None:
            return None
        self._check_expected_updated_at(workspace, proposal.base_updated_at)
        current = self._to_response(workspace)
        if not any(item.id == proposal.architecture_id for item in current.architectures):
            raise ValueError("The proposal references an architecture that no longer exists.")

        requirement_sections: list[str] = []
        impact_items: list[WorkspaceImpactItem] = []
        changed = False
        for addition in proposal.requirement_additions:
            collections = {
                "functional_requirement": current.requirements.functional_requirements,
                "non_functional_requirement": current.requirements.non_functional_requirements,
                "constraint": current.requirements.constraints,
                "assumption": current.requirements.assumptions,
            }
            collection = collections[addition.target_type]
            if any(value.casefold() == addition.text.casefold() for value in collection):
                continue
            edit = WorkspaceEditRequest(
                target_type=addition.target_type,
                operation="add",
                value=addition.text,
            )
            applied = self.workspace_editor.apply(current, edit)
            current = applied.workspace
            requirement_sections.extend(applied.regenerated_sections)
            impact_items.extend(applied.impact.items)
            changed = True

        if not changed and not proposal.architecture_changes:
            raise ValueError("This proposal no longer contains an applicable change.")

        self._record_revision(workspace, proposal.summary)
        regenerated_sections: list[str] = []
        if changed:
            self._copy_response_state(workspace, current)
            workspace.requirements_json = hydrate_project_signals(
                RequirementModel.model_validate(workspace.requirements_json),
                workspace.answers_json or {},
            ).model_dump()
            requirement_regeneration = self._expand_regeneration_sections(
                requirement_sections
            )
            self._regenerate_sections(workspace, requirement_regeneration)
            regenerated_sections.extend(requirement_regeneration)
            current = self._to_response(workspace)

        if proposal.architecture_changes:
            current = self.architecture_assistant.apply_patch(current, proposal)
            self._copy_response_state(workspace, current)
            architecture_regeneration = self._expand_regeneration_sections(
                ["comparison", "recommendation", "deployment", "diagrams"]
            )
            self._regenerate_sections(workspace, architecture_regeneration)
            regenerated_sections.extend(architecture_regeneration)
            impact_items.extend(
                [
                    WorkspaceImpactItem(
                        area="Architecture",
                        level="major",
                        summary="The selected architecture option is updated by the approved proposal.",
                    ),
                    WorkspaceImpactItem(
                        area="Downstream artifacts",
                        level="major",
                        summary="Scoring, deployment, diagrams, causal links, and documentation are synchronized.",
                    ),
                ]
            )
        regenerated_sections = list(dict.fromkeys(regenerated_sections))

        impact = WorkspaceEditImpact(
            items=self._dedupe_impact_items(impact_items),
            affected_artifacts=[
                "architectures",
                *regenerated_sections,
                "causal_graph",
                "documentation",
            ],
            requires_confirmation=False,
        )
        assessment = ImpactAssessment(
            change_request=proposal.request,
            impacted_modules=regenerated_sections,
            reasoning=[item.summary for item in impact.items],
            regenerated_sections=regenerated_sections,
            affected_artifacts=impact.affected_artifacts,
        )
        workspace.impact_history_json = [
            *(workspace.impact_history_json or []),
            assessment.model_dump(),
        ]
        recommendation = RecommendationResult.model_validate(workspace.recommendation_json)
        adrs = self._load_adrs(workspace)
        adrs.append(
            self._build_adr(
                title=proposal.summary[:80],
                context=proposal.request,
                recommendation=recommendation,
                changed_modules=regenerated_sections,
            )
        )
        workspace.adrs_json = [item.model_dump() for item in adrs]
        self._rebuild_graph_and_documentation(workspace)
        response = self._to_response(self.repository.save(workspace))
        return WorkspaceMutationResponse(
            workspace=response,
            impact=impact,
            consistency_issues=response.consistency_issues,
            message="Architecture proposal applied and dependent artifacts synchronized.",
        )

    def create_workspace(
        self,
        payload: WorkspaceCreateRequest,
        on_progress: ProgressCallback | None = None,
        project_id: str | None = None,
    ) -> WorkspaceResponse:
        project_id = project_id or str(uuid.uuid4())
        GENERATION_TELEMETRY.start(project_id)
        answers = self._seed_answers(payload)
        requirements, cache_hit, duration_ms = PROJECT_GENERATION_CACHE.get_or_compute(
            project_id,
            "requirements-actors-constraints-integrations",
            payload.model_dump(mode="json"),
            lambda: self.requirement_analyzer.analyze(
                title=payload.title,
                description=payload.description,
                business_context=payload.business_context,
                answers=answers,
                constraints=payload.constraints,
                project_id=project_id,
            ),
        )
        GENERATION_TELEMETRY.section(project_id, "requirements", duration_ms, cache_hit)
        self._emit_progress(on_progress, "requirements", requirements)
        generated = self._generate_all(
            payload.title,
            payload.description,
            payload.business_context,
            answers,
            requirements,
            project_id=project_id,
            on_progress=on_progress,
        )

        workspace = Workspace(
            id=project_id,
            title=payload.title,
            original_prompt=payload.description,
            business_context=payload.business_context,
            answers_json=answers,
            requirements_json=generated["requirements"].model_dump(),
            clarification_json=generated["clarification"].model_dump(),
            architectures_json=[item.model_dump() for item in generated["architectures"]],
            comparison_json=generated["comparison"].model_dump(),
            recommendation_json=generated["recommendation"].model_dump(),
            diagrams_json={key: value.model_dump() for key, value in generated["diagrams"].items()},
            database_design_json=generated["database_design"].model_dump(),
            api_design_json=generated["api_design"].model_dump(),
            deployment_plan_json=generated["deployment_plan"].model_dump(),
            causal_graph_json=generated["causal_graph"].model_dump(),
            adrs_json=[item.model_dump() for item in generated["adrs"]],
            diagram_layouts_json={},
            edit_history_json={"past": [], "future": []},
            documentation_markdown=generated["documentation_markdown"],
            impact_history_json=[],
        )
        response = self._to_response(self.repository.add(workspace))
        GENERATION_TELEMETRY.finish(project_id)
        return response

    def answer_clarifications(
        self, workspace_id: str, answers: dict[str, str]
    ) -> WorkspaceResponse | None:
        workspace = self.repository.get(workspace_id)
        if workspace is None:
            return None

        merged_answers = {**(workspace.answers_json or {}), **answers}
        if merged_answers == (workspace.answers_json or {}):
            return self._to_response(workspace)
        requirements = RequirementModel.model_validate(workspace.requirements_json)
        question_text = {
            item.get("key", ""): item.get("question", "")
            for item in (workspace.clarification_json or {}).get("questions", [])
            if item.get("key")
        }
        requirements = self.requirement_analyzer.apply_clarifications(
            requirements,
            merged_answers,
            question_text,
        )
        workspace.answers_json = merged_answers
        workspace.requirements_json = requirements.model_dump()
        sections = self._clarification_sections(answers, question_text)
        self._regenerate_sections(workspace, sections)
        self._rebuild_graph_and_documentation(workspace)
        return self._to_response(self.repository.save(workspace))

    @staticmethod
    def _clarification_sections(
        answers: dict[str, str], questions: dict[str, str]
    ) -> list[str]:
        """Map changed canonical facts to their actual downstream consumers."""
        sections = {"clarifications"}
        for key in answers:
            category = clarification_category(key, questions.get(key, ""))
            if category in {"availability", "scale", "regional"}:
                sections.update({
                    "architectures", "comparison", "recommendation",
                    "deployment", "diagrams",
                })
            elif category == "security":
                sections.update({
                    "architectures", "comparison", "recommendation", "api",
                    "deployment", "diagrams",
                })
            elif category == "integrations":
                sections.update({
                    "architectures", "comparison", "recommendation", "database",
                    "api", "deployment", "diagrams",
                })
            elif category in {"technical-data", "retention"}:
                sections.update({
                    "architectures", "comparison", "recommendation", "database",
                    "api", "deployment", "diagrams",
                })
            else:
                sections.update({
                    "architectures", "comparison", "recommendation", "database",
                    "api", "deployment", "diagrams",
                })
        order = (
            "clarifications", "architectures", "comparison", "recommendation",
            "database", "api", "deployment", "diagrams",
        )
        return [section for section in order if section in sections]

    def preview_edit(
        self, workspace_id: str, edit: WorkspaceEditRequest
    ) -> WorkspaceEditPreview | None:
        workspace = self.repository.get(workspace_id)
        if workspace is None:
            return None
        self._check_edit_version(workspace, edit)
        return self.workspace_editor.preview(self._to_response(workspace), edit)

    def apply_workspace_edit(
        self, workspace_id: str, edit: WorkspaceEditRequest
    ) -> WorkspaceMutationResponse | None:
        workspace = self.repository.get(workspace_id)
        if workspace is None:
            return None
        self._check_edit_version(workspace, edit)
        current = self._to_response(workspace)
        applied = self.workspace_editor.apply(current, edit)

        self._record_revision(workspace, applied.description)
        self._copy_response_state(workspace, applied.workspace)
        workspace.requirements_json = hydrate_project_signals(
            RequirementModel.model_validate(workspace.requirements_json),
            workspace.answers_json or {},
        ).model_dump()
        self._regenerate_sections(workspace, applied.regenerated_sections)

        if applied.regenerated_sections:
            impact = ImpactAssessment(
                change_request=applied.description,
                impacted_modules=applied.regenerated_sections,
                reasoning=[item.summary for item in applied.impact.items if item.level != "none"],
                regenerated_sections=applied.regenerated_sections,
                directly_affected_node_ids=applied.impact.directly_affected_node_ids,
                indirectly_affected_node_ids=applied.impact.indirectly_affected_node_ids,
                affected_artifacts=applied.impact.affected_artifacts,
            )
            workspace.impact_history_json = [
                *(workspace.impact_history_json or []),
                impact.model_dump(),
            ]
            recommendation = RecommendationResult.model_validate(workspace.recommendation_json)
            adrs = self._load_adrs(workspace)
            adrs.append(
                self._build_adr(
                    title=applied.description[:80],
                    context=applied.description,
                    recommendation=recommendation,
                    changed_modules=applied.regenerated_sections,
                )
            )
            workspace.adrs_json = [item.model_dump() for item in adrs]
            self._rebuild_graph_and_documentation(workspace)

        saved = self.repository.save(workspace)
        response = self._to_response(saved)
        return WorkspaceMutationResponse(
            workspace=response,
            impact=applied.impact,
            consistency_issues=response.consistency_issues,
            message="Workspace updated and dependent artifacts synchronized.",
        )

    def undo_workspace_edit(self, workspace_id: str) -> WorkspaceMutationResponse | None:
        return self._restore_revision(workspace_id, direction="undo")

    def redo_workspace_edit(self, workspace_id: str) -> WorkspaceMutationResponse | None:
        return self._restore_revision(workspace_id, direction="redo")

    def apply_change_request(
        self, workspace_id: str, change_request: str
    ) -> WorkspaceResponse | None:
        workspace = self.repository.get(workspace_id)
        if workspace is None:
            return None

        requirements = RequirementModel.model_validate(workspace.requirements_json)
        updated_requirements = hydrate_project_signals(
            self.requirement_analyzer.append_change(requirements, change_request),
            workspace.answers_json or {},
        )

        architectures = [
            ArchitectureOption.model_validate(item) for item in workspace.architectures_json
        ]
        comparison = ComparisonResult.model_validate(workspace.comparison_json)
        recommendation = RecommendationResult.model_validate(workspace.recommendation_json)
        database_design = DatabaseDesign.model_validate(workspace.database_design_json)
        api_design = ApiDesign.model_validate(workspace.api_design_json)
        deployment_plan = DeploymentPlan.model_validate(workspace.deployment_plan_json)

        existing_adrs = self._load_adrs(workspace)
        current_diagrams = {
            key: DiagramArtifact.model_validate(value)
            for key, value in (workspace.diagrams_json or {}).items()
        }
        provisional_graph = self.causal_graph_service.build(
            original_prompt=workspace.original_prompt,
            requirements=updated_requirements,
            architectures=architectures,
            recommendation=recommendation,
            api_design=api_design,
            database_design=database_design,
            deployment_plan=deployment_plan,
            diagrams=current_diagrams,
            adrs=existing_adrs,
        )
        changed_requirement_id = f"FR-{len(updated_requirements.functional_requirements):03d}"
        graph_impact = self.causal_graph_service.impact_for_requirement(
            provisional_graph, changed_requirement_id
        )
        keyword_impact = self.impact_analyzer.assess(change_request)
        use_keyword_extensions = any(
            reason.startswith("Detected `") for reason in keyword_impact.reasoning
        )
        impacted_modules = list(graph_impact.impacted_modules)
        if use_keyword_extensions:
            impacted_modules.extend(keyword_impact.impacted_modules)
        impacted_modules = list(dict.fromkeys(impacted_modules))
        regenerated_sections = self._expand_regeneration_sections(
            ["clarifications", *impacted_modules]
        )
        impact = ImpactAssessment(
            change_request=change_request,
            impacted_modules=impacted_modules,
            reasoning=[
                *graph_impact.reasoning,
                *(keyword_impact.reasoning if use_keyword_extensions else []),
            ],
            regenerated_sections=regenerated_sections,
            directly_affected_node_ids=graph_impact.directly_affected_node_ids,
            indirectly_affected_node_ids=graph_impact.indirectly_affected_node_ids,
            affected_artifacts=graph_impact.affected_artifacts,
        )

        workspace.requirements_json = updated_requirements.model_dump()
        self._regenerate_sections(workspace, impact.regenerated_sections)
        architectures = [
            ArchitectureOption.model_validate(item) for item in workspace.architectures_json
        ]
        comparison = ComparisonResult.model_validate(workspace.comparison_json)
        recommendation = RecommendationResult.model_validate(workspace.recommendation_json)
        database_design = DatabaseDesign.model_validate(workspace.database_design_json)
        api_design = ApiDesign.model_validate(workspace.api_design_json)
        deployment_plan = DeploymentPlan.model_validate(workspace.deployment_plan_json)
        diagram_models = {
            key: DiagramArtifact.model_validate(value)
            for key, value in (workspace.diagrams_json or {}).items()
        }

        history = list(workspace.impact_history_json or [])
        history.append(impact.model_dump())
        workspace.impact_history_json = history

        adr = self._build_adr(
            title=change_request[:80],
            context=change_request,
            recommendation=recommendation,
            changed_modules=impact.regenerated_sections,
        )
        adrs = [*existing_adrs, adr]
        workspace.adrs_json = [item.model_dump() for item in adrs]
        graph = self.causal_graph_service.build(
            original_prompt=workspace.original_prompt,
            requirements=updated_requirements,
            architectures=architectures,
            recommendation=recommendation,
            api_design=api_design,
            database_design=database_design,
            deployment_plan=deployment_plan,
            diagrams=diagram_models,
            adrs=adrs,
        )
        workspace.causal_graph_json = graph.model_dump()

        response = self._workspace_response_from_parts(workspace)
        response.consistency_issues = self.workspace_editor.consistency_issues(response)
        workspace.documentation_markdown = self.documentation_generator.build_markdown(response)

        return self._to_response(self.repository.save(workspace))

    def export_pdf(self, workspace_id: str) -> bytes | None:
        workspace = self.repository.get(workspace_id)
        if workspace is None:
            return None
        return self.documentation_generator.render_pdf(
            workspace.title,
            workspace.documentation_markdown,
        )

    @staticmethod
    def _cached_section(
        project_id: str,
        section: str,
        payload: Any,
        producer: Callable[[], Any],
    ) -> Any:
        value, cache_hit, duration_ms = PROJECT_GENERATION_CACHE.get_or_compute(
            project_id, section, payload, producer
        )
        GENERATION_TELEMETRY.section(project_id, section, duration_ms, cache_hit)
        return value

    @staticmethod
    def _emit_progress(
        callback: ProgressCallback | None,
        section: str,
        value: Any,
    ) -> None:
        if callback is None:
            return
        if isinstance(value, list):
            count = len(value)
            preview = [getattr(item, "name", str(item)) for item in value[:3]]
        elif isinstance(value, dict):
            count = len(value)
            preview = [getattr(item, "title", str(key)) for key, item in list(value.items())[:3]]
        elif isinstance(value, RequirementModel):
            count = len(value.functional_requirements)
            preview = [value.domain, value.summary]
        elif isinstance(value, ClarificationPlan):
            count = len(value.questions)
            preview = [item.question for item in value.questions[:2]]
        elif isinstance(value, ComparisonResult):
            count = len(value.scorecards)
            preview = [
                f"{item.architecture_name}: {item.weighted_score:.1f}"
                for item in sorted(
                    value.scorecards,
                    key=lambda scorecard: scorecard.weighted_score,
                    reverse=True,
                )[:3]
            ]
        elif isinstance(value, RecommendationResult):
            count = 1
            preview = [value.recommended_architecture_name]
        elif isinstance(value, DatabaseDesign):
            count = len(value.entities)
            preview = [item.name for item in value.entities[:4]]
        elif isinstance(value, ApiDesign):
            count = len(value.groups)
            preview = [item.name for item in value.groups[:4]]
        elif isinstance(value, DeploymentPlan):
            count = 1
            preview = [value.deployment_model, *value.regions[:2]]
        elif hasattr(value, "groups"):
            count = len(value.groups)
            preview = []
        elif hasattr(value, "entities"):
            count = len(value.entities)
            preview = []
        elif hasattr(value, "questions"):
            count = len(value.questions)
            preview = []
        elif hasattr(value, "scorecards"):
            count = len(value.scorecards)
            preview = []
        else:
            count = 1
            preview = []
        callback(section, {
            "section": section,
            "status": "complete",
            "item_count": count,
            "preview": [item for item in preview if item],
        })

    def _generate_all(
        self,
        title: str,
        description: str,
        business_context: str | None,
        answers: dict[str, str],
        requirements: RequirementModel,
        *,
        refine_architecture: bool = False,
        existing_adrs: list[ArchitectureDecisionRecord] | None = None,
        project_id: str = "preview",
        on_progress: ProgressCallback | None = None,
    ) -> dict:
        del refine_architecture
        compact = CompactProjectContext.build(project_id, requirements, answers)
        context_payload = compact.cache_payload()

        # Phase 1 has no cross-dependencies. These deterministic generators can
        # run concurrently immediately after the single bundled extraction.
        phase_one: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="archai-phase1") as executor:
            futures = {
                executor.submit(
                    self._cached_section,
                    project_id,
                    "clarification",
                    context_payload,
                    lambda: self.clarification_engine.generate(requirements, answers),
                ): "clarification",
                executor.submit(
                    self._cached_section,
                    project_id,
                    "architectures",
                    context_payload,
                    lambda: self.architecture_generator.generate(requirements, answers),
                ): "architectures",
                executor.submit(
                    self._cached_section,
                    project_id,
                    "database",
                    context_payload,
                    lambda: self.database_generator.generate(requirements),
                ): "database",
            }
            for future in as_completed(futures):
                section = futures[future]
                phase_one[section] = future.result()
                self._emit_progress(on_progress, section, phase_one[section])

        clarification = phase_one["clarification"]
        architectures = phase_one["architectures"]
        database_design = phase_one["database"]

        # Comparison only needs architectures; API design only needs the data
        # model. They therefore form a second independent phase.
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="archai-phase2") as executor:
            futures = {
                executor.submit(
                    self._cached_section,
                    project_id,
                    "comparison",
                    {
                        "context": context_payload,
                        "architectures": [item.model_dump() for item in architectures],
                    },
                    lambda: self.comparison_engine.compare(
                        requirements, architectures, answers
                    ),
                ): "comparison",
                executor.submit(
                    self._cached_section,
                    project_id,
                    "api",
                    {"context": context_payload, "database": database_design.model_dump()},
                    lambda: self.api_generator.generate(requirements, database_design),
                ): "api",
            }
            phase_two: dict[str, Any] = {}
            for future in as_completed(futures):
                section = futures[future]
                phase_two[section] = future.result()
                self._emit_progress(on_progress, section, phase_two[section])
            comparison = phase_two["comparison"]
            api_design = phase_two["api"]

        recommendation = self._cached_section(
            project_id,
            "recommendation",
            {
                "context": context_payload,
                "architectures": [item.model_dump() for item in architectures],
                "comparison": comparison.model_dump(),
            },
            lambda: self.recommendation_engine.recommend(
                requirements, architectures, comparison, answers
            ),
        )
        self._emit_progress(on_progress, "recommendation", recommendation)
        deployment_plan = self._cached_section(
            project_id,
            "deployment",
            {"context": context_payload, "recommendation": recommendation.model_dump()},
            lambda: self.deployment_generator.generate(requirements, recommendation, answers),
        )
        self._emit_progress(on_progress, "deployment", deployment_plan)
        diagrams = self._cached_section(
            project_id,
            "diagrams",
            {
                "context": context_payload,
                "architectures": [item.model_dump() for item in architectures],
                "recommendation": recommendation.model_dump(),
                "database": database_design.model_dump(),
                "deployment": deployment_plan.model_dump(),
            },
            lambda: self.diagram_generator.generate(
                requirements,
                architectures,
                recommendation,
                database_design,
                deployment_plan,
            ),
        )
        self._emit_progress(on_progress, "diagrams", diagrams)

        adr = None
        if existing_adrs is None:
            adr = self._build_adr(
                title="Initial Analysis",
                context=description,
                recommendation=recommendation,
                changed_modules=["requirements", "architectures", "comparison", "recommendation",
                                 "diagrams", "database", "api", "deployment", "documentation"],
            )
            adrs = [adr]
        else:
            adrs = list(existing_adrs)

        causal_graph = self.causal_graph_service.build(
            original_prompt=description,
            requirements=requirements,
            architectures=architectures,
            recommendation=recommendation,
            api_design=api_design,
            database_design=database_design,
            deployment_plan=deployment_plan,
            diagrams=diagrams,
            adrs=adrs,
        )

        response = WorkspaceResponse(
            id="preview",
            title=title,
            original_prompt=description,
            business_context=business_context,
            answers=answers,
            requirements=requirements,
            clarification_plan=clarification,
            architectures=architectures,
            comparison=comparison,
            recommendation=recommendation,
            diagrams=diagrams,
            database_design=database_design,
            api_design=api_design,
            deployment_plan=deployment_plan,
            documentation_markdown="",
            impact_history=[],
            adr=adr,
            adrs=adrs,
            causal_graph=causal_graph,
            created_at=self._placeholder_datetime(),
            updated_at=self._placeholder_datetime(),
        )
        # Consistency findings are computed before the markdown so the stored
        # report includes the Consistency Review section.
        response.consistency_issues = self.workspace_editor.consistency_issues(response)
        documentation_markdown = self.documentation_generator.build_markdown(response)
        return {
            "requirements": requirements,
            "clarification": clarification,
            "architectures": architectures,
            "comparison": comparison,
            "recommendation": recommendation,
            "database_design": database_design,
            "api_design": api_design,
            "deployment_plan": deployment_plan,
            "diagrams": diagrams,
            "documentation_markdown": documentation_markdown,
            "adr": adr,
            "adrs": adrs,
            "causal_graph": causal_graph,
        }

    def _upgrade_legacy_workspace(self, workspace: Workspace) -> Workspace:
        """Replace stale pre-signal artifacts when an older workspace is opened.

        Old records only contain string lists, so their derived API/deployment
        views cannot reflect the canonical confirmation model.  A workspace is
        upgraded once, detected from the persisted requirements payload; all
        replacements remain scoped to that workspace ID and use its own saved
        answers.  Workspaces created by this version already carry the marker.
        """
        raw = workspace.requirements_json or {}
        answers = dict(workspace.answers_json or {})
        removed_legacy_input = answers.pop("budget", None) is not None
        if removed_legacy_input:
            workspace.answers_json = answers
        scorecards = (workspace.comparison_json or {}).get("scorecards", [])
        current_decision_model = bool(scorecards) and all(
            item.get("decision_model") == ARCHITECTURE_DECISION_MODEL_VERSION
            for item in scorecards
        )
        current_requirement_model = (
            raw.get("requirement_model_version") == CURRENT_REQUIREMENT_MODEL_VERSION
        )
        if (
            raw.get("project_profile")
            and raw.get("integration_details") is not None
            and not removed_legacy_input
            and current_decision_model
            and current_requirement_model
        ):
            return workspace
        GENERATION_TELEMETRY.start(workspace.id)
        if not current_decision_model or not current_requirement_model:
            # Semantic model upgrades must re-run extraction from this
            # workspace's own source text. Merely hydrating an old snapshot
            # would preserve stale actors/entities and context boundaries.
            requirements = self.requirement_analyzer.analyze(
                title=workspace.title,
                description=workspace.original_prompt,
                business_context=workspace.business_context,
                answers=answers,
                # Persisted requirement constraints include prior derived
                # classifications. Feeding them back into a new semantic
                # model preserves stale duplicates and clarification wrappers;
                # confirmed user constraints are rebuilt from saved answers.
                constraints=[],
                project_id=workspace.id,
            )
        else:
            requirements = hydrate_project_signals(
                RequirementModel.model_validate(raw), answers
            )
        generated = self._generate_all(
            workspace.title,
            workspace.original_prompt,
            workspace.business_context,
            answers,
            requirements,
            existing_adrs=self._load_adrs(workspace),
            project_id=workspace.id,
        )
        self._apply_generated_content(workspace, generated)
        saved = self.repository.save(workspace)
        GENERATION_TELEMETRY.finish(workspace.id)
        return saved

    def _apply_generated_content(self, workspace: Workspace, generated: dict) -> None:
        workspace.requirements_json = generated["requirements"].model_dump()
        workspace.clarification_json = generated["clarification"].model_dump()
        workspace.architectures_json = [item.model_dump() for item in generated["architectures"]]
        workspace.comparison_json = generated["comparison"].model_dump()
        workspace.recommendation_json = generated["recommendation"].model_dump()
        workspace.diagrams_json = {key: value.model_dump() for key, value in generated["diagrams"].items()}
        workspace.database_design_json = generated["database_design"].model_dump()
        workspace.api_design_json = generated["api_design"].model_dump()
        workspace.deployment_plan_json = generated["deployment_plan"].model_dump()
        workspace.causal_graph_json = generated["causal_graph"].model_dump()
        workspace.adrs_json = [item.model_dump() for item in generated["adrs"]]
        workspace.documentation_markdown = generated["documentation_markdown"]

    def _copy_response_state(
        self, workspace: Workspace, response: WorkspaceResponse
    ) -> None:
        workspace.requirements_json = response.requirements.model_dump()
        workspace.architectures_json = [item.model_dump() for item in response.architectures]
        workspace.comparison_json = response.comparison.model_dump()
        workspace.recommendation_json = response.recommendation.model_dump()
        workspace.diagrams_json = {
            key: value.model_dump() for key, value in response.diagrams.items()
        }
        workspace.database_design_json = response.database_design.model_dump()
        workspace.api_design_json = response.api_design.model_dump()
        workspace.deployment_plan_json = response.deployment_plan.model_dump()
        workspace.diagram_layouts_json = copy.deepcopy(response.diagram_layouts)
        # Source traceability: causal graph and ADRs are downstream artifacts
        # and must travel with the response state, otherwise edits leave stale
        # graphs/docs behind.
        if getattr(response, "causal_graph", None) is not None:
            workspace.causal_graph_json = response.causal_graph.model_dump()
        if getattr(response, "adrs", None) is not None:
            workspace.adrs_json = [item.model_dump() for item in response.adrs]

    @staticmethod
    def _expand_regeneration_sections(sections: list[str]) -> list[str]:
        """Return the minimal dependency closure in a stable execution order."""
        expanded = set(sections)
        dependencies = {
            "architectures": {"comparison", "recommendation", "deployment", "diagrams"},
            "comparison": {"recommendation", "deployment", "diagrams"},
            "recommendation": {"deployment", "diagrams"},
            "database": {"api", "diagrams"},
            "deployment": {"diagrams"},
        }
        changed = True
        while changed:
            changed = False
            for source, dependents in dependencies.items():
                if source in expanded and not dependents.issubset(expanded):
                    expanded.update(dependents)
                    changed = True
        order = [
            "clarifications",
            "architectures",
            "database",
            "comparison",
            "api",
            "recommendation",
            "deployment",
            "diagrams",
        ]
        return [section for section in order if section in expanded]

    def _regenerate_sections(
        self, workspace: Workspace, sections: list[str]
    ) -> None:
        section_set = set(self._expand_regeneration_sections(sections))
        requirements = RequirementModel.model_validate(workspace.requirements_json)
        answers = workspace.answers_json or {}
        context_payload = CompactProjectContext.build(
            workspace.id, requirements, answers
        ).cache_payload()
        architectures = [
            ArchitectureOption.model_validate(item) for item in workspace.architectures_json
        ]
        comparison = ComparisonResult.model_validate(workspace.comparison_json)
        recommendation = RecommendationResult.model_validate(workspace.recommendation_json)
        database_design = DatabaseDesign.model_validate(workspace.database_design_json)
        api_design = ApiDesign.model_validate(workspace.api_design_json)
        deployment_plan = DeploymentPlan.model_validate(workspace.deployment_plan_json)

        GENERATION_TELEMETRY.start(workspace.id)
        try:
            phase_one: dict[str, Any] = {}
            phase_one_jobs: dict[str, Callable[[], Any]] = {}
            if "clarifications" in section_set:
                phase_one_jobs["clarifications"] = lambda: self._cached_section(
                    workspace.id,
                    "clarification",
                    context_payload,
                    lambda: self.clarification_engine.generate(requirements, answers),
                )
            if "architectures" in section_set:
                phase_one_jobs["architectures"] = lambda: self._cached_section(
                    workspace.id,
                    "architectures",
                    context_payload,
                    lambda: self.architecture_generator.generate(requirements, answers),
                )
            if "database" in section_set:
                phase_one_jobs["database"] = lambda: self._cached_section(
                    workspace.id,
                    "database",
                    context_payload,
                    lambda: self.database_generator.generate(requirements),
                )
            if phase_one_jobs:
                with ThreadPoolExecutor(
                    max_workers=len(phase_one_jobs),
                    thread_name_prefix="archai-refresh1",
                ) as executor:
                    futures = {
                        executor.submit(job): section
                        for section, job in phase_one_jobs.items()
                    }
                    for future in as_completed(futures):
                        phase_one[futures[future]] = future.result()

            if "clarifications" in phase_one:
                workspace.clarification_json = phase_one["clarifications"].model_dump()
            architectures = phase_one.get("architectures", architectures)
            database_design = phase_one.get("database", database_design)

            phase_two: dict[str, Any] = {}
            phase_two_jobs: dict[str, Callable[[], Any]] = {}
            if "comparison" in section_set:
                phase_two_jobs["comparison"] = lambda: self._cached_section(
                    workspace.id,
                    "comparison",
                    {
                        "context": context_payload,
                        "architectures": [item.model_dump() for item in architectures],
                    },
                    lambda: self.comparison_engine.compare(
                        requirements, architectures, answers
                    ),
                )
            if "api" in section_set:
                phase_two_jobs["api"] = lambda: self._cached_section(
                    workspace.id,
                    "api",
                    {
                        "context": context_payload,
                        "database": database_design.model_dump(),
                    },
                    lambda: self.api_generator.generate(requirements, database_design),
                )
            if phase_two_jobs:
                with ThreadPoolExecutor(
                    max_workers=len(phase_two_jobs),
                    thread_name_prefix="archai-refresh2",
                ) as executor:
                    futures = {
                        executor.submit(job): section
                        for section, job in phase_two_jobs.items()
                    }
                    for future in as_completed(futures):
                        phase_two[futures[future]] = future.result()

            comparison = phase_two.get("comparison", comparison)
            api_design = phase_two.get("api", api_design)
            if "recommendation" in section_set:
                recommendation = self._cached_section(
                    workspace.id,
                    "recommendation",
                    {
                        "context": context_payload,
                        "architectures": [item.model_dump() for item in architectures],
                        "comparison": comparison.model_dump(),
                    },
                    lambda: self.recommendation_engine.recommend(
                        requirements, architectures, comparison, answers
                    ),
                )
            if "deployment" in section_set:
                deployment_plan = self._cached_section(
                    workspace.id,
                    "deployment",
                    {
                        "context": context_payload,
                        "recommendation": recommendation.model_dump(),
                    },
                    lambda: self.deployment_generator.generate(
                        requirements, recommendation, answers
                    ),
                )
            if "diagrams" in section_set:
                diagrams = self._cached_section(
                    workspace.id,
                    "diagrams",
                    {
                        "context": context_payload,
                        "architectures": [item.model_dump() for item in architectures],
                        "recommendation": recommendation.model_dump(),
                        "database": database_design.model_dump(),
                        "deployment": deployment_plan.model_dump(),
                    },
                    lambda: self.diagram_generator.generate(
                        requirements,
                        architectures,
                        recommendation,
                        database_design,
                        deployment_plan,
                    ),
                )
                workspace.diagrams_json = {
                    key: value.model_dump() for key, value in diagrams.items()
                }
        finally:
            GENERATION_TELEMETRY.finish(workspace.id)

        workspace.architectures_json = [item.model_dump() for item in architectures]
        workspace.comparison_json = comparison.model_dump()
        workspace.recommendation_json = recommendation.model_dump()
        workspace.database_design_json = database_design.model_dump()
        workspace.api_design_json = api_design.model_dump()
        workspace.deployment_plan_json = deployment_plan.model_dump()

    def _rebuild_graph_and_documentation(self, workspace: Workspace) -> None:
        requirements = RequirementModel.model_validate(workspace.requirements_json)
        architectures = [
            ArchitectureOption.model_validate(item) for item in workspace.architectures_json
        ]
        recommendation = RecommendationResult.model_validate(workspace.recommendation_json)
        diagrams = {
            key: DiagramArtifact.model_validate(value)
            for key, value in (workspace.diagrams_json or {}).items()
        }
        graph = self.causal_graph_service.build(
            original_prompt=workspace.original_prompt,
            requirements=requirements,
            architectures=architectures,
            recommendation=recommendation,
            api_design=ApiDesign.model_validate(workspace.api_design_json),
            database_design=DatabaseDesign.model_validate(workspace.database_design_json),
            deployment_plan=DeploymentPlan.model_validate(workspace.deployment_plan_json),
            diagrams=diagrams,
            adrs=self._load_adrs(workspace),
        )
        workspace.causal_graph_json = graph.model_dump()
        response = self._workspace_response_from_parts(workspace)
        response.consistency_issues = self.workspace_editor.consistency_issues(response)
        workspace.documentation_markdown = self.documentation_generator.build_markdown(response)

    def _check_edit_version(
        self, workspace: Workspace, edit: WorkspaceEditRequest
    ) -> None:
        self._check_expected_updated_at(workspace, edit.expected_updated_at)

    @staticmethod
    def _check_expected_updated_at(
        workspace: Workspace, expected_updated_at: datetime | None
    ) -> None:
        if expected_updated_at is None or workspace.updated_at is None:
            return
        requested = expected_updated_at.replace(tzinfo=None)
        stored = workspace.updated_at.replace(tzinfo=None)
        if abs((requested - stored).total_seconds()) > 0.001:
            raise ValueError(
                "This workspace changed after you opened it. Refresh before applying the edit."
            )

    @staticmethod
    def _dedupe_impact_items(
        items: list[WorkspaceImpactItem],
    ) -> list[WorkspaceImpactItem]:
        output: list[WorkspaceImpactItem] = []
        seen: set[tuple[str, str]] = set()
        for item in items:
            key = (item.area.casefold(), item.summary.casefold())
            if key not in seen:
                output.append(item)
                seen.add(key)
        return output

    def _record_revision(self, workspace: Workspace, description: str) -> None:
        history = copy.deepcopy(workspace.edit_history_json or {})
        past = list(history.get("past", []))
        past.append(self._snapshot(workspace, description))
        workspace.edit_history_json = {"past": past[-12:], "future": []}

    def _restore_revision(
        self, workspace_id: str, *, direction: str
    ) -> WorkspaceMutationResponse | None:
        workspace = self.repository.get(workspace_id)
        if workspace is None:
            return None
        history = copy.deepcopy(workspace.edit_history_json or {})
        source_key = "past" if direction == "undo" else "future"
        destination_key = "future" if direction == "undo" else "past"
        source = list(history.get(source_key, []))
        destination = list(history.get(destination_key, []))
        if not source:
            raise ValueError(f"There is no workspace change to {direction}.")

        snapshot = source.pop()
        destination.append(self._snapshot(workspace, f"Before {direction}"))
        self._restore_snapshot(workspace, snapshot)
        history[source_key] = source[-12:]
        history[destination_key] = destination[-12:]
        workspace.edit_history_json = history
        saved = self.repository.save(workspace)
        response = self._to_response(saved)
        impact = WorkspaceEditImpact(
            items=[
                WorkspaceImpactItem(
                    area="Workspace",
                    level="major",
                    summary=f"The previous canonical workspace revision was {direction}ne.",
                )
            ],
            affected_artifacts=["workspace"],
        )
        return WorkspaceMutationResponse(
            workspace=response,
            impact=impact,
            consistency_issues=response.consistency_issues,
            message=f"Workspace change {direction}ne.",
        )

    def _snapshot(self, workspace: Workspace, description: str) -> dict:
        fields = (
            "answers_json", "requirements_json", "clarification_json",
            "architectures_json", "comparison_json", "recommendation_json",
            "diagrams_json", "database_design_json", "api_design_json",
            "deployment_plan_json", "causal_graph_json", "adrs_json",
            "diagram_layouts_json", "impact_history_json",
        )
        return {
            "description": description,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "documentation_markdown": workspace.documentation_markdown,
            "state": {
                field: copy.deepcopy(getattr(workspace, field, None)) for field in fields
            },
        }

    def _restore_snapshot(self, workspace: Workspace, snapshot: dict) -> None:
        state = snapshot.get("state", {})
        for field, value in state.items():
            if hasattr(workspace, field):
                setattr(workspace, field, copy.deepcopy(value))
        workspace.documentation_markdown = snapshot.get("documentation_markdown", "")

    def _workspace_response_from_parts(self, workspace: Workspace) -> WorkspaceResponse:
        requirements = RequirementModel.model_validate(workspace.requirements_json)
        architectures = [
            ArchitectureOption.model_validate(item) for item in workspace.architectures_json
        ]
        recommendation = RecommendationResult.model_validate(workspace.recommendation_json)
        diagrams = {
            key: DiagramArtifact.model_validate(value)
            for key, value in (workspace.diagrams_json or {}).items()
        }
        database_design = DatabaseDesign.model_validate(workspace.database_design_json)
        api_design = ApiDesign.model_validate(workspace.api_design_json)
        deployment_plan = DeploymentPlan.model_validate(workspace.deployment_plan_json)
        adrs = self._load_adrs(workspace)
        stored_graph = getattr(workspace, "causal_graph_json", None) or {}
        causal_graph = (
            CausalGraph.model_validate(stored_graph)
            if stored_graph.get("nodes") and stored_graph.get("version") == GRAPH_VERSION
            else self.causal_graph_service.build(
                original_prompt=workspace.original_prompt,
                requirements=requirements,
                architectures=architectures,
                recommendation=recommendation,
                api_design=api_design,
                database_design=database_design,
                deployment_plan=deployment_plan,
                diagrams=diagrams,
                adrs=adrs,
            )
        )
        return WorkspaceResponse(
            id=workspace.id,
            title=workspace.title,
            original_prompt=workspace.original_prompt,
            business_context=workspace.business_context,
            answers=workspace.answers_json or {},
            requirements=requirements,
            clarification_plan=ClarificationPlan.model_validate(workspace.clarification_json),
            architectures=architectures,
            comparison=ComparisonResult.model_validate(workspace.comparison_json),
            recommendation=recommendation,
            diagrams=diagrams,
            database_design=database_design,
            api_design=api_design,
            deployment_plan=deployment_plan,
            documentation_markdown=workspace.documentation_markdown,
            impact_history=[
                ImpactAssessment.model_validate(item) for item in (workspace.impact_history_json or [])
            ],
            adr=adrs[-1] if adrs else None,
            adrs=adrs,
            causal_graph=causal_graph,
            diagram_layouts=copy.deepcopy(
                getattr(workspace, "diagram_layouts_json", None) or {}
            ),
            consistency_issues=[],
            can_undo=bool(
                (getattr(workspace, "edit_history_json", None) or {}).get("past")
            ),
            can_redo=bool(
                (getattr(workspace, "edit_history_json", None) or {}).get("future")
            ),
            created_at=workspace.created_at,
            updated_at=workspace.updated_at,
        )

    def _to_response(self, workspace: Workspace) -> WorkspaceResponse:
        response = self._workspace_response_from_parts(workspace)
        if not response.documentation_markdown:
            response.documentation_markdown = self.documentation_generator.build_markdown(response)
        response.consistency_issues = self.workspace_editor.consistency_issues(response)
        return response

    def get_causal_graph(self, workspace_id: str) -> CausalGraph | None:
        workspace = self.get_workspace(workspace_id)
        return workspace.causal_graph if workspace else None

    def explain_causal_node(
        self, workspace_id: str, node_id: str
    ) -> CausalGraphTrace | None:
        graph = self.get_causal_graph(workspace_id)
        if graph is None:
            return None
        return self.causal_graph_service.explain(graph, node_id)

    def _load_adrs(self, workspace: Workspace) -> list[ArchitectureDecisionRecord]:
        return [
            ArchitectureDecisionRecord.model_validate(item)
            for item in (getattr(workspace, "adrs_json", None) or [])
        ]

    def _seed_answers(self, payload: WorkspaceCreateRequest) -> dict[str, str]:
        answers: dict[str, str] = {}
        if payload.preferred_cloud:
            answers["preferred_cloud"] = payload.preferred_cloud
        if payload.constraints:
            answers["constraints"] = "; ".join(payload.constraints)
        if payload.team_size:
            answers["team_size"] = str(payload.team_size)
        return answers

    def _placeholder_datetime(self):
        from datetime import datetime, timezone

        return datetime.now(timezone.utc)

    def _build_adr(
        self,
        title: str,
        context: str,
        recommendation: RecommendationResult,
        changed_modules: list[str],
    ) -> ArchitectureDecisionRecord:
        """Construct an ArchitectureDecisionRecord from the current state.

        This is a pure data-assembly step with no LLM involvement.
        The title is derived from the change_request text or defaults
        to 'Initial Analysis'. Consequences are summarised from the
        recommendation's why_not data.
        """
        now = datetime.now(timezone.utc).isoformat()
        why_not_summary = "; ".join(
            f"{name}: {reasons[0]}"
            for name, reasons in (recommendation.why_not or {}).items()
            if reasons
        ) or "No alternatives were shortlisted."

        consequences = (
            f"Accepted trade-offs: {why_not_summary} "
            f"Confidence: {recommendation.confidence}."
        )

        return ArchitectureDecisionRecord(
            id=str(uuid.uuid4()),
            timestamp=now,
            title=title,
            context=context,
            decision=recommendation.recommended_architecture_name,
            status="accepted",
            consequences=consequences,
            changed_modules=changed_modules,
        )
