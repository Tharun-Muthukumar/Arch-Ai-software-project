import uuid
from datetime import datetime, timezone

from app.models.workspace import Workspace
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.domain import (
    ApiDesign,
    ArchitectureDecisionRecord,
    ArchitectureOption,
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
    WorkspaceCreateRequest,
    WorkspaceResponse,
)
from app.services.api_generator import ApiGenerator
from app.services.architecture_generator import ArchitectureGenerator
from app.services.clarification_engine import ClarificationEngine
from app.services.causal_graph import GRAPH_VERSION, CausalGraphService
from app.services.comparison_engine import ComparisonEngine
from app.services.database_generator import DatabaseGenerator
from app.services.deployment_generator import DeploymentGenerator
from app.services.diagram_generator import DiagramGenerator
from app.services.documentation_generator import DocumentationGenerator
from app.services.impact_analyzer import ImpactAnalyzer
from app.services.recommendation_engine import RecommendationEngine
from app.services.requirement_analyzer import RequirementAnalyzer


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

    def list_workspaces(self) -> list[WorkspaceResponse]:
        return [self._to_response(workspace) for workspace in self.repository.list()]

    def get_workspace(self, workspace_id: str) -> WorkspaceResponse | None:
        workspace = self.repository.get(workspace_id)
        if workspace is None:
            return None
        return self._to_response(workspace)

    def create_workspace(self, payload: WorkspaceCreateRequest) -> WorkspaceResponse:
        answers = self._seed_answers(payload)
        requirements = self.requirement_analyzer.analyze(
            title=payload.title,
            description=payload.description,
            business_context=payload.business_context,
            answers=answers,
            constraints=payload.constraints,
        )
        generated = self._generate_all(payload.title, payload.description, payload.business_context, answers, requirements)

        workspace = Workspace(
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
            documentation_markdown=generated["documentation_markdown"],
            impact_history_json=[],
        )
        return self._to_response(self.repository.add(workspace))

    def answer_clarifications(
        self, workspace_id: str, answers: dict[str, str]
    ) -> WorkspaceResponse | None:
        workspace = self.repository.get(workspace_id)
        if workspace is None:
            return None

        merged_answers = {**(workspace.answers_json or {}), **answers}
        requirements = RequirementModel.model_validate(workspace.requirements_json)
        question_text = {
            item.get("key", ""): item.get("question", "")
            for item in (workspace.clarification_json or {}).get("questions", [])
            if item.get("key")
        }
        requirements = self.requirement_analyzer.apply_clarifications(
            requirements,
            answers,
            question_text,
        )
        generated = self._generate_all(
            workspace.title,
            workspace.original_prompt,
            workspace.business_context,
            merged_answers,
            requirements,
            refine_architecture=False,
            existing_adrs=self._load_adrs(workspace),
        )

        workspace.answers_json = merged_answers
        self._apply_generated_content(workspace, generated)
        return self._to_response(self.repository.save(workspace))

    def apply_change_request(
        self, workspace_id: str, change_request: str
    ) -> WorkspaceResponse | None:
        workspace = self.repository.get(workspace_id)
        if workspace is None:
            return None

        requirements = RequirementModel.model_validate(workspace.requirements_json)
        updated_requirements = self.requirement_analyzer.append_change(requirements, change_request)

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
        impact = ImpactAssessment(
            change_request=change_request,
            impacted_modules=impacted_modules,
            reasoning=[
                *graph_impact.reasoning,
                *(keyword_impact.reasoning if use_keyword_extensions else []),
            ],
            regenerated_sections=impacted_modules.copy(),
            directly_affected_node_ids=graph_impact.directly_affected_node_ids,
            indirectly_affected_node_ids=graph_impact.indirectly_affected_node_ids,
            affected_artifacts=graph_impact.affected_artifacts,
        )

        if "architectures" in impact.impacted_modules:
            architectures = self.architecture_generator.generate(updated_requirements, workspace.answers_json)
        if "comparison" in impact.impacted_modules or "architectures" in impact.impacted_modules:
            comparison = self.comparison_engine.compare(updated_requirements, architectures, workspace.answers_json)
        if "recommendation" in impact.impacted_modules or "architectures" in impact.impacted_modules:
            recommendation = self.recommendation_engine.recommend(updated_requirements, architectures, comparison)
        if "database" in impact.impacted_modules:
            database_design = self.database_generator.generate(updated_requirements)
        if "api" in impact.impacted_modules:
            api_design = self.api_generator.generate(updated_requirements, database_design)
        if "deployment" in impact.impacted_modules:
            deployment_plan = self.deployment_generator.generate(
                updated_requirements, recommendation, workspace.answers_json
            )

        diagram_models = current_diagrams
        if "diagrams" in impact.impacted_modules:
            diagram_models = self.diagram_generator.generate(
                updated_requirements,
                architectures,
                recommendation,
                database_design,
                deployment_plan,
            )

        workspace.requirements_json = updated_requirements.model_dump()
        workspace.architectures_json = [item.model_dump() for item in architectures]
        workspace.comparison_json = comparison.model_dump()
        workspace.recommendation_json = recommendation.model_dump()
        workspace.database_design_json = database_design.model_dump()
        workspace.api_design_json = api_design.model_dump()
        workspace.deployment_plan_json = deployment_plan.model_dump()
        workspace.diagrams_json = {
            key: value.model_dump() for key, value in diagram_models.items()
        }

        history = list(workspace.impact_history_json or [])
        history.append(impact.model_dump())
        workspace.impact_history_json = history

        adr = self._build_adr(
            title=change_request[:80],
            context=change_request,
            recommendation=recommendation,
            changed_modules=impact.impacted_modules,
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
    ) -> dict:
        clarification = self.clarification_engine.generate(requirements, answers)
        architectures = self.architecture_generator.generate(
            requirements,
            answers,
            refine_with_ai=refine_architecture,
        )
        comparison = self.comparison_engine.compare(requirements, architectures, answers)
        recommendation = self.recommendation_engine.recommend(requirements, architectures, comparison)
        database_design = self.database_generator.generate(requirements)
        api_design = self.api_generator.generate(requirements, database_design)
        deployment_plan = self.deployment_generator.generate(requirements, recommendation, answers)
        diagrams = self.diagram_generator.generate(
            requirements,
            architectures,
            recommendation,
            database_design,
            deployment_plan,
        )

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
            created_at=workspace.created_at,
            updated_at=workspace.updated_at,
        )

    def _to_response(self, workspace: Workspace) -> WorkspaceResponse:
        response = self._workspace_response_from_parts(workspace)
        if not response.documentation_markdown:
            response.documentation_markdown = self.documentation_generator.build_markdown(response)
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
        if payload.budget:
            answers["budget"] = payload.budget
        if payload.preferred_cloud:
            answers["preferred_cloud"] = payload.preferred_cloud
        if payload.constraints:
            answers["constraints"] = "; ".join(payload.constraints)
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
