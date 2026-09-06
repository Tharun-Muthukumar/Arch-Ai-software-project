import hashlib
import re
from collections import deque
from collections.abc import Iterable

from app.schemas.domain import (
    ApiDesign,
    ArchitectureDecisionRecord,
    ArchitectureOption,
    CausalGraph,
    CausalGraphEdge,
    CausalGraphNode,
    CausalGraphTrace,
    DatabaseDesign,
    DeploymentPlan,
    DiagramArtifact,
    ImpactAssessment,
    RecommendationResult,
    RequirementModel,
)


REQUIREMENT_TYPES = {
    "user_requirement",
    "functional_requirement",
    "non_functional_requirement",
    "constraint",
    "assumption",
}
COMPONENT_TYPES = {"architecture_component", "service_module"}
ARTIFACT_TYPES = {
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
}
GRAPH_VERSION = "6"

STOP_WORDS = {
    "about", "after", "also", "and", "are", "because", "been", "before",
    "being", "build", "can", "could", "does", "each", "for", "from", "have",
    "into", "must", "need", "only", "other", "should", "system", "that", "the",
    "their", "them", "then", "there", "these", "they", "this", "through", "use",
    "user", "users", "using", "when", "where", "which", "while", "with", "would",
}


class CausalGraphService:
    """Build and traverse a validated graph from existing ArchAI artifacts.

    The service deliberately does not call an LLM. It links validated artifacts using
    stable ownership relationships and conservative lexical/technical similarity.
    """

    def build(
        self,
        *,
        original_prompt: str,
        requirements: RequirementModel,
        architectures: list[ArchitectureOption],
        recommendation: RecommendationResult,
        api_design: ApiDesign,
        database_design: DatabaseDesign,
        deployment_plan: DeploymentPlan,
        diagrams: dict[str, DiagramArtifact],
        adrs: list[ArchitectureDecisionRecord],
    ) -> CausalGraph:
        nodes: list[CausalGraphNode] = []
        edges: list[CausalGraphEdge] = []
        node_ids: set[str] = set()
        edge_keys: set[tuple[str, str, str]] = set()

        def add_node(node: CausalGraphNode) -> None:
            if node.id not in node_ids:
                nodes.append(node)
                node_ids.add(node.id)

        def add_edge(
            source: str,
            target: str,
            relationship: str,
            reason: str,
            confidence: float | None = None,
        ) -> None:
            key = (source, target, relationship)
            if source == target or key in edge_keys:
                return
            edge_keys.add(key)
            digest = hashlib.sha1("|".join(key).encode("utf-8")).hexdigest()[:12]
            edges.append(
                CausalGraphEdge(
                    id=f"EDGE-{digest}",
                    source_node_id=source,
                    target_node_id=target,
                    relationship=relationship,
                    reason=reason,
                    confidence=confidence,
                )
            )

        raw_id = "REQ-RAW"
        add_node(
            CausalGraphNode(
                id=raw_id,
                type="user_requirement",
                name="Original project brief",
                description=original_prompt,
                source="user",
                metadata={"artifact": "requirements"},
            )
        )

        requirement_nodes: list[CausalGraphNode] = []
        technical_nodes: list[CausalGraphNode] = []
        requirement_groups = (
            ("FR", "functional_requirement", requirements.functional_requirements),
            ("NFR", "non_functional_requirement", requirements.non_functional_requirements),
            ("CON", "constraint", requirements.constraints),
            ("ASM", "assumption", requirements.assumptions),
        )
        for prefix, node_type, values in requirement_groups:
            for index, value in enumerate(values, start=1):
                node_id = f"{prefix}-{index:03d}"
                node = CausalGraphNode(
                    id=node_id,
                    type=node_type,
                    name=value,
                    description=value,
                    source="requirement-analysis",
                    metadata={
                        "artifact": "requirements",
                        "analysis_source": requirements.analysis_source,
                        "requirement_index": index - 1,
                    },
                )
                add_node(node)
                requirement_nodes.append(node)
                add_edge(
                    raw_id,
                    node_id,
                    "requires",
                    f'The project brief explicitly establishes {node_id}: "{value}"',
                    1.0 if requirements.analysis_source == "predefined-blueprint" else 0.9,
                )

                characteristic = self._technical_characteristic(value, node_type)
                technical_id = f"TECH-{node_id}"
                technical_node = CausalGraphNode(
                    id=technical_id,
                    type="technical_characteristic",
                    name=characteristic[0],
                    description=characteristic[1],
                    source="deterministic-requirement-mapping",
                    confidence=characteristic[2],
                    metadata={
                        "artifact": "requirements",
                        "category": characteristic[3],
                        "requirement_id": node_id,
                        "requirement_text": value,
                    },
                )
                add_node(technical_node)
                technical_nodes.append(technical_node)
                add_edge(
                    node_id,
                    technical_id,
                    "requires",
                    f'"{value}" creates the technical need "{characteristic[0]}": {characteristic[1]}',
                    characteristic[2],
                )

        for index, characteristic in enumerate(requirements.data_characteristics, start=1):
            technical_id = f"TECH-DATA-{index:03d}"
            name, separator, _ = characteristic.partition(":")
            technical_node = CausalGraphNode(
                id=technical_id,
                type="technical_characteristic",
                name=name.strip() if separator else characteristic,
                description=characteristic,
                source="requirement-analysis",
                confidence=1.0,
                metadata={
                    "artifact": "requirements",
                    "category": "data_characteristic",
                    "data_characteristic_index": index - 1,
                },
            )
            add_node(technical_node)
            technical_nodes.append(technical_node)
            add_edge(
                raw_id,
                technical_id,
                "requires",
                f'The project brief establishes this data characteristic: "{characteristic}"',
                1.0,
            )

        selected_architecture_id = recommendation.recommended_architecture_id
        technical_nodes_by_id = {node.id: node for node in technical_nodes}
        component_nodes_by_architecture: dict[str, list[CausalGraphNode]] = {}
        decision_ids: dict[str, str] = {}

        for architecture in architectures:
            decision_id = f"DEC-{self._slug(architecture.id).upper()}"
            decision_ids[architecture.id] = decision_id
            add_node(
                CausalGraphNode(
                    id=decision_id,
                    type="architecture_decision",
                    name=architecture.name,
                    description=architecture.overview,
                    source="architecture-generation",
                    metadata={
                        "artifact": "architectures",
                        "architecture_id": architecture.id,
                        "recommended": architecture.id == selected_architecture_id,
                        "style": architecture.style,
                    },
                )
            )

            for requirement in requirement_nodes:
                technical_id = f"TECH-{requirement.id}"
                technical_name = technical_nodes_by_id[technical_id].name
                add_edge(
                    technical_id,
                    decision_id,
                    "requires",
                    f'{architecture.name} must respond to the requirement "{requirement.name}" and its technical consequence "{technical_name}". The generated option is a candidate design; implementation verification is still required.',
                    0.75 if architecture.id == selected_architecture_id else 0.6,
                )
                if requirement.type == "constraint":
                    add_edge(
                        requirement.id,
                        decision_id,
                        "constrained_by",
                        f'{architecture.name} must respect the explicit constraint: "{requirement.name}"',
                        1.0,
                    )
                if (
                    requirement.type == "non_functional_requirement"
                    and architecture.id == selected_architecture_id
                ):
                    add_edge(
                        requirement.id,
                        decision_id,
                        "satisfies",
                        f'{architecture.name} was scored against the quality requirement: "{requirement.name}" Verification is still required in implementation.',
                        0.8,
                    )

            for technical_node in technical_nodes:
                if technical_node.id.startswith("TECH-DATA-"):
                    add_edge(
                        technical_node.id,
                        decision_id,
                        "requires",
                        "This architecture option must account for the extracted data characteristic.",
                        0.75 if architecture.id == selected_architecture_id else 0.6,
                    )

            architecture_components: list[CausalGraphNode] = []
            for index, component in enumerate(architecture.components, start=1):
                component_id = f"CMP-{self._slug(architecture.id).upper()}-{index:02d}"
                node_type = self._component_type(component.name)
                component_node = CausalGraphNode(
                    id=component_id,
                    type=node_type,
                    name=component.name,
                    description=component.responsibility,
                    source="architecture-generation",
                    metadata={
                        "artifact": "architectures",
                        "architecture_id": architecture.id,
                        "technologies": component.technologies,
                        "interactions": component.interactions,
                    },
                )
                add_node(component_node)
                architecture_components.append(component_node)
                add_edge(
                    decision_id,
                    component_id,
                    "implemented_by",
                    f'{component.name} implements part of {architecture.name}: {component.responsibility}',
                    1.0,
                )

                component_text = " ".join(
                    [component.name, component.responsibility, *component.technologies, *component.interactions]
                )
                for matched, score in self._rank_requirements(
                    component_text, requirement_nodes, limit=3
                ):
                    add_edge(
                        matched.id,
                        component_id,
                        "implemented_by",
                        f'{component.name} exists to support the requirement: "{matched.name}" Its responsibility is: {component.responsibility}',
                        score,
                    )

            component_nodes_by_architecture[architecture.id] = architecture_components

            for index, risk in enumerate(architecture.disadvantages, start=1):
                risk_id = f"RISK-{self._slug(architecture.id).upper()}-{index:02d}"
                add_node(
                    CausalGraphNode(
                        id=risk_id,
                        type="risk",
                        name=risk,
                        description=risk,
                        source="architecture-comparison",
                        metadata={"artifact": "comparison", "architecture_id": architecture.id},
                    )
                )
                add_edge(
                    decision_id,
                    risk_id,
                    "affects",
                    f"Selecting {architecture.name} introduces this documented trade-off.",
                    1.0,
                )

            cost_id = f"COST-{self._slug(architecture.id).upper()}"
            add_node(
                CausalGraphNode(
                    id=cost_id,
                    type="cost",
                    name=f"{architecture.name} cost profile",
                    description=architecture.estimated_cost,
                    source="architecture-generation",
                    metadata={"artifact": "comparison", "architecture_id": architecture.id},
                )
            )
            add_edge(
                decision_id,
                cost_id,
                "affects",
                f"The architecture style determines its relative cost profile: {architecture.estimated_cost}.",
                1.0,
            )

        selected_components = component_nodes_by_architecture.get(selected_architecture_id, [])
        selected_decision_id = decision_ids.get(selected_architecture_id)

        for index, integration in enumerate(requirements.integrations, start=1):
            integration_id = f"INT-{index:03d}"
            integration_node = CausalGraphNode(
                id=integration_id,
                type="integration",
                name=integration,
                description=integration,
                source="requirement-analysis",
                metadata={"artifact": "architectures"},
            )
            add_node(integration_node)
            for matched, score in self._rank_requirements(integration, requirement_nodes, limit=2):
                add_edge(
                    matched.id,
                    integration_id,
                    "requires",
                    f'The integration "{integration}" is needed by the requirement: "{matched.name}"',
                    score,
                )
            for component in self._rank_nodes(integration, selected_components, limit=1):
                add_edge(
                    component.id,
                    integration_id,
                    "depends_on",
                    f'{component.name} owns the boundary for the confirmed integration "{integration}".',
                    0.8,
                )

        api_nodes: list[CausalGraphNode] = []
        for index, group in enumerate(api_design.groups, start=1):
            api_id = f"API-{index:03d}"
            api_text = " ".join(
                [group.name, group.description, *[endpoint.purpose for endpoint in group.endpoints]]
            )
            api_node = CausalGraphNode(
                id=api_id,
                type="api",
                name=group.name,
                description=group.description,
                source="api-generation",
                metadata={
                    "artifact": "api",
                    "style": api_design.style,
                    "endpoints": [f"{endpoint.method} {endpoint.path}" for endpoint in group.endpoints],
                    "endpoint_details": [
                        {
                            "method": endpoint.method,
                            "path": endpoint.path,
                            "purpose": endpoint.purpose,
                            "auth_required": endpoint.auth_required,
                        }
                        for endpoint in group.endpoints
                    ],
                },
            )
            add_node(api_node)
            api_nodes.append(api_node)
            for matched, score in self._rank_requirements(api_text, requirement_nodes, limit=3):
                add_edge(
                    matched.id,
                    api_id,
                    "exposed_by",
                    f'{group.name} API exists to expose the behavior: "{matched.name}"',
                    score,
                )
            for component in self._rank_nodes(api_text, selected_components, limit=2):
                add_edge(
                    component.id,
                    api_id,
                    "exposed_by",
                    f'{component.name} owns or coordinates the {group.name} API because {component.description}',
                    0.8,
                )

        database_nodes: list[CausalGraphNode] = []
        for index, entity in enumerate(database_design.entities, start=1):
            entity_id = f"DATA-{index:03d}"
            entity_text = " ".join(
                [entity.name, entity.description, *[field.name for field in entity.fields]]
            )
            entity_node = CausalGraphNode(
                id=entity_id,
                type="database_entity",
                name=entity.name,
                description=entity.description,
                source="database-generation",
                metadata={
                    "artifact": "database",
                    "database_engine": database_design.database_engine,
                    "fields": [field.name for field in entity.fields],
                },
            )
            add_node(entity_node)
            database_nodes.append(entity_node)
            for matched, score in self._rank_requirements(entity_text, requirement_nodes, limit=3):
                add_edge(
                    matched.id,
                    entity_id,
                    "requires",
                    f'The {entity.name} entity represents data needed by the requirement: "{matched.name}"',
                    score,
                )
            for component in self._rank_nodes(entity_text, selected_components, limit=2):
                add_edge(
                    component.id,
                    entity_id,
                    "stores_in",
                    f"{component.name} reads or writes {entity.name} data.",
                    0.75,
                )
            for api_node in self._rank_nodes(entity_text, api_nodes, limit=1):
                add_edge(
                    api_node.id,
                    entity_id,
                    "stores_in",
                    f"The {api_node.name} API operates on {entity.name} data.",
                    0.75,
                )

        infrastructure_id = "INFRA-DEPLOYMENT"
        add_node(
            CausalGraphNode(
                id=infrastructure_id,
                type="infrastructure",
                name=deployment_plan.deployment_model,
                description=deployment_plan.cloud_recommendation,
                source="deployment-generation",
                metadata={
                    "artifact": "deployment",
                    "target_stack": deployment_plan.target_stack,
                    "docker_services": deployment_plan.docker_services,
                    "kubernetes_modules": deployment_plan.kubernetes_modules,
                    "security_controls": deployment_plan.security_controls,
                    "scaling_strategy": deployment_plan.scaling_strategy,
                },
            )
        )
        if selected_decision_id:
            add_edge(
                selected_decision_id,
                infrastructure_id,
                "deployed_on",
                f'The {deployment_plan.deployment_model} deployment plan hosts the recommended architecture using the generated target stack.',
                1.0,
            )
        for component in selected_components:
            add_edge(
                component.id,
                infrastructure_id,
                "deployed_on",
                f"{component.name} is hosted by the generated deployment plan.",
                1.0,
            )

        diagram_nodes: dict[str, CausalGraphNode] = {}
        for key, diagram in diagrams.items():
            diagram_id = f"DIAG-{self._slug(key).upper()}"
            diagram_node = CausalGraphNode(
                id=diagram_id,
                type="diagram",
                name=diagram.title,
                description=diagram.description,
                source="diagram-generation",
                metadata={"artifact": "diagrams", "diagram_key": key},
            )
            add_node(diagram_node)
            diagram_nodes[key] = diagram_node

        for component in selected_components:
            for key in ("component", "sequence"):
                if key in diagram_nodes:
                    add_edge(
                        component.id,
                        diagram_nodes[key].id,
                        "affects",
                        f"{component.name} is represented in the generated {key} diagram.",
                        1.0,
                    )
        for entity in database_nodes:
            for key in ("er", "class"):
                if key in diagram_nodes:
                    add_edge(
                        entity.id,
                        diagram_nodes[key].id,
                        "affects",
                        f"{entity.name} contributes to the generated {key} diagram.",
                        1.0,
                    )
        if "deployment" in diagram_nodes:
            add_edge(
                infrastructure_id,
                diagram_nodes["deployment"].id,
                "affects",
                "The deployment diagram visualizes the generated infrastructure plan.",
                1.0,
            )
        for requirement in requirement_nodes:
            for key in ("use_case", "activity"):
                if key in diagram_nodes:
                    add_edge(
                        requirement.id,
                        diagram_nodes[key].id,
                        "affects",
                        f'The {key} diagram visualizes behavior from the requirement: "{requirement.name}"',
                        0.9,
                    )

        for adr in adrs:
            adr_id = f"ADR-{self._slug(adr.id).upper()}"
            add_node(
                CausalGraphNode(
                    id=adr_id,
                    type="adr",
                    name=adr.title,
                    description=adr.decision,
                    source="architecture-decision-record",
                    metadata={
                        "artifact": "documentation",
                        "adr_id": adr.id,
                        "status": adr.status,
                        "timestamp": adr.timestamp,
                        "changed_modules": adr.changed_modules,
                    },
                )
            )
            matched_requirements = self._rank_requirements(
                f"{adr.title} {adr.context}", requirement_nodes, limit=4
            )
            if not matched_requirements and adr.title == "Initial Analysis":
                matched_requirements = [(item, 0.7) for item in requirement_nodes]
            for requirement, score in matched_requirements:
                add_edge(
                    requirement.id,
                    adr_id,
                    "caused_by",
                    f'This ADR records a decision influenced by the requirement: "{requirement.name}"',
                    score,
                )
            if selected_decision_id:
                add_edge(
                    selected_decision_id,
                    adr_id,
                    "caused_by",
                    "This ADR records the accepted architecture decision and its trade-offs.",
                    1.0,
                )

        graph = CausalGraph(version=GRAPH_VERSION, nodes=nodes, edges=edges)
        graph.orphan_node_ids = self.find_orphan_components(graph)
        return CausalGraph.model_validate(graph.model_dump())

    def downstream(self, graph: CausalGraph, node_id: str) -> list[CausalGraphNode]:
        return self._walk(graph, node_id, reverse=False)

    def upstream(self, graph: CausalGraph, node_id: str) -> list[CausalGraphNode]:
        return self._walk(graph, node_id, reverse=True)

    def requirements_for_component(
        self, graph: CausalGraph, component_id: str
    ) -> list[CausalGraphNode]:
        node = next((item for item in graph.nodes if item.id == component_id), None)
        direct = self._direct_requirements(graph, component_id)
        if direct and node is not None and node.type in COMPONENT_TYPES:
            return direct
        return [
            node
            for node in self.upstream(graph, component_id)
            if node.type in REQUIREMENT_TYPES and node.type != "user_requirement"
        ]

    def find_orphan_components(self, graph: CausalGraph) -> list[str]:
        orphan_ids: list[str] = []
        for node in graph.nodes:
            if node.type not in COMPONENT_TYPES:
                continue
            if not any(item.type in REQUIREMENT_TYPES for item in self.upstream(graph, node.id)):
                orphan_ids.append(node.id)
        return orphan_ids

    def explain(self, graph: CausalGraph, node_id: str) -> CausalGraphTrace | None:
        node_by_id = {node.id: node for node in graph.nodes}
        selected = node_by_id.get(node_id)
        if selected is None:
            return None

        upstream = self.upstream(graph, node_id)
        downstream = self.downstream(graph, node_id)
        requirements = self._direct_requirements(graph, node_id)
        if not requirements:
            requirements = [
                node
                for node in upstream
                if node.type in REQUIREMENT_TYPES and node.type != "user_requirement"
            ]
        if selected.type in REQUIREMENT_TYPES:
            requirements = [selected, *requirements]

        related = [*upstream, *downstream]
        related_adrs = [node for node in related if node.type == "adr"]
        incoming = [edge for edge in graph.edges if edge.target_node_id == node_id]
        why = self._dedupe([edge.reason for edge in incoming])
        if not why:
            why = ["No upstream causal relationship has been recorded for this node."]

        artifacts = self._dedupe(
            [
                str(item.metadata.get("artifact"))
                for item in [selected, *downstream]
                if item.type in ARTIFACT_TYPES and item.metadata.get("artifact")
            ]
        )
        return CausalGraphTrace(
            selected_node=selected,
            why_it_exists=why,
            requirements=self._dedupe_nodes(requirements),
            upstream=upstream,
            downstream=downstream,
            related_adrs=self._dedupe_nodes(related_adrs),
            affected_artifacts=artifacts,
        )

    def impact_for_requirement(self, graph: CausalGraph, requirement_id: str) -> ImpactAssessment:
        node_by_id = {node.id: node for node in graph.nodes}
        if requirement_id not in node_by_id:
            return ImpactAssessment(change_request="", impacted_modules=["requirements", "documentation"])

        outgoing = [edge for edge in graph.edges if edge.source_node_id == requirement_id]
        direct_ids = self._dedupe([edge.target_node_id for edge in outgoing])
        directly_linked_components = {
            node_id for node_id in direct_ids if node_by_id[node_id].type in COMPONENT_TYPES
        }

        seen = {requirement_id, *direct_ids}
        queue = deque(direct_ids)
        indirect_ids: list[str] = []
        adjacency = self._adjacency(graph, reverse=False)
        while queue:
            current = queue.popleft()
            for target in adjacency.get(current, []):
                target_node = node_by_id[target]
                current_node = node_by_id[current]
                if (
                    current_node.type == "architecture_decision"
                    and target_node.type in COMPONENT_TYPES
                    and directly_linked_components
                    and target not in directly_linked_components
                ):
                    continue
                if target in seen:
                    continue
                seen.add(target)
                indirect_ids.append(target)
                queue.append(target)

        affected_nodes = [node_by_id[node_id] for node_id in [*direct_ids, *indirect_ids]]
        artifacts = self._dedupe(
            [
                str(node.metadata.get("artifact"))
                for node in affected_nodes
                if node.metadata.get("artifact")
            ]
        )
        modules = self._dedupe(
            ["requirements", *artifacts, "documentation"]
        )
        if "architectures" in modules:
            modules.extend(["comparison", "recommendation"])
        elif "comparison" in modules:
            modules.append("recommendation")
        if "database" in modules:
            modules.append("api")
        if any(
            module in modules
            for module in ("architectures", "database", "api", "deployment")
        ):
            modules.append("diagrams")
        modules = self._dedupe(modules)
        modules = [module for module in modules if module in self._known_modules()]
        artifacts = self._dedupe(
            [
                *artifacts,
                *[
                    module
                    for module in modules
                    if module not in {"requirements", "documentation"}
                ],
            ]
        )
        return ImpactAssessment(
            change_request=node_by_id[requirement_id].name,
            impacted_modules=modules,
            reasoning=[
                f"Causal traversal from {requirement_id} found {len(direct_ids)} direct and {len(indirect_ids)} indirect dependencies."
            ],
            regenerated_sections=modules.copy(),
            directly_affected_node_ids=direct_ids,
            indirectly_affected_node_ids=indirect_ids,
            affected_artifacts=artifacts,
        )

    def impacted_nodes_for_text(
        self, graph: CausalGraph, text: str
    ) -> tuple[list[CausalGraphNode], list[CausalGraphNode]]:
        """Trace a hypothetical statement without adding it to the persisted graph."""
        categories = self._technical_categories(text)
        requirement_nodes = [
            node
            for node in graph.nodes
            if node.type in REQUIREMENT_TYPES and node.type != "user_requirement"
        ]
        technical_nodes = [
            node for node in graph.nodes if node.type == "technical_characteristic"
        ]
        architecture_nodes = [
            node
            for node in graph.nodes
            if node.type in {"architecture_decision", *COMPONENT_TYPES, "infrastructure"}
        ]
        ranked_requirements = [
            node for node, _ in self._rank_requirements(text, requirement_nodes, limit=4)
        ]
        category_nodes = [
            node
            for node in technical_nodes
            if str(node.metadata.get("category", "")) in categories
        ]
        lexical_nodes = self._rank_nodes(text, technical_nodes, limit=4)
        architecture_matches = self._rank_nodes(text, architecture_nodes, limit=4)
        direct = self._dedupe_nodes(
            [*ranked_requirements, *category_nodes, *lexical_nodes, *architecture_matches]
        )

        seen = {node.id for node in direct}
        indirect: list[CausalGraphNode] = []
        for node in direct:
            for downstream in self.downstream(graph, node.id):
                if downstream.id in seen:
                    continue
                seen.add(downstream.id)
                indirect.append(downstream)
        return direct, indirect

    def _walk(
        self, graph: CausalGraph, start_id: str, *, reverse: bool
    ) -> list[CausalGraphNode]:
        node_by_id = {node.id: node for node in graph.nodes}
        if start_id not in node_by_id:
            return []
        adjacency = self._adjacency(graph, reverse=reverse)
        queue = deque(adjacency.get(start_id, []))
        seen = {start_id}
        result: list[CausalGraphNode] = []
        while queue:
            node_id = queue.popleft()
            if node_id in seen:
                continue
            seen.add(node_id)
            result.append(node_by_id[node_id])
            queue.extend(adjacency.get(node_id, []))
        return result

    def _direct_requirements(
        self, graph: CausalGraph, target_id: str
    ) -> list[CausalGraphNode]:
        node_by_id = {node.id: node for node in graph.nodes}
        result: list[CausalGraphNode] = []
        for edge in graph.edges:
            source = node_by_id.get(edge.source_node_id)
            if (
                edge.target_node_id == target_id
                and source is not None
                and source.type in REQUIREMENT_TYPES
                and source.type != "user_requirement"
            ):
                result.append(source)
        return self._dedupe_nodes(result)

    def _adjacency(self, graph: CausalGraph, *, reverse: bool) -> dict[str, list[str]]:
        adjacency: dict[str, list[str]] = {}
        for edge in graph.edges:
            source = edge.target_node_id if reverse else edge.source_node_id
            target = edge.source_node_id if reverse else edge.target_node_id
            adjacency.setdefault(source, []).append(target)
        return adjacency

    def _rank_requirements(
        self,
        text: str,
        requirements: list[CausalGraphNode],
        *,
        limit: int,
    ) -> list[tuple[CausalGraphNode, float]]:
        text_tokens = self._tokens(text)
        text_categories = self._technical_categories(text)
        ranked: list[tuple[int, int, CausalGraphNode]] = []
        for order, requirement in enumerate(requirements):
            if requirement.type == "assumption":
                continue
            overlap = len(text_tokens & self._tokens(requirement.description))
            category_overlap = len(text_categories & self._technical_categories(requirement.description))
            semantic_score = overlap * 3 + category_overlap * 2
            if semantic_score == 0:
                continue
            role_score = self._role_affinity(text, requirement.type)
            score = semantic_score + role_score
            if score > 0:
                ranked.append((score, -order, requirement))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        if not ranked:
            return []
        top_score = ranked[0][0]
        minimum_score = max(5, (top_score + 1) // 2)
        matches: list[tuple[CausalGraphNode, float]] = []
        seen_text: set[str] = set()
        for score, _, item in ranked:
            normalized_text = " ".join(re.findall(r"[a-z0-9]+", item.description.lower()))
            if score < minimum_score or normalized_text in seen_text:
                continue
            seen_text.add(normalized_text)
            confidence = round(
                min(0.98, 0.55 + (score / max(12, top_score * 2))), 2
            )
            matches.append((item, confidence))
            if len(matches) == limit:
                break
        return matches

    def _rank_nodes(
        self, text: str, nodes: Iterable[CausalGraphNode], *, limit: int
    ) -> list[CausalGraphNode]:
        text_tokens = self._tokens(text)
        ranked: list[tuple[int, int, CausalGraphNode]] = []
        for order, node in enumerate(nodes):
            node_text = " ".join(
                [node.name, node.description, " ".join(map(str, node.metadata.values()))]
            )
            score = len(text_tokens & self._tokens(node_text))
            if score > 0:
                ranked.append((score, -order, node))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item for _, _, item in ranked[:limit]]

    def _technical_characteristic(
        self, text: str, requirement_type: str
    ) -> tuple[str, str, float, str]:
        categories = self._technical_categories(text)
        catalog = {
            "realtime": ("Real-time data delivery", "The design must propagate time-sensitive state changes without batch-only delays."),
            "event_processing": ("Event and telemetry processing", "The design must ingest and process events or device-originated observations."),
            "geospatial": ("Geospatial data handling", "The design must model or query location, distance, routes, or spatial state."),
            "transactional": ("Transactional integrity", "The design must preserve valid state across financially or operationally sensitive changes."),
            "security": ("Identity and data protection", "The design must enforce access boundaries and protect sensitive information."),
            "availability": ("Resilience and availability", "The design must continue operating within the stated availability or recovery expectation."),
            "performance": ("Low-latency processing", "The design must keep relevant operations within the stated responsiveness expectation."),
            "scalability": ("Elastic capacity", "The design must accommodate the stated growth, traffic, concurrency, or data-volume expectation."),
            "audit": ("Auditability and governance", "The design must preserve evidence needed to trace important actions and changes."),
            "integration": ("External integration boundary", "The design must isolate and validate communication with an external system."),
            "offline": ("Offline synchronization", "The design must reconcile work performed without continuous network connectivity."),
            "media": ("Binary media handling", "The design must safely ingest, store, or deliver file and media content."),
        }
        for category in (
            "realtime", "event_processing", "geospatial", "transactional", "security",
            "availability", "performance", "scalability", "audit", "integration", "offline", "media",
        ):
            if category in categories:
                name, description = catalog[category]
                return name, description, 0.9, category

        defaults = {
            "functional_requirement": (
                "Business capability support",
                "The architecture must provide an implementation boundary for this stated behavior.",
                "capability",
            ),
            "non_functional_requirement": (
                "Quality attribute enforcement",
                "The architecture must make this stated quality expectation measurable or enforceable.",
                "quality",
            ),
            "constraint": (
                "Design constraint compliance",
                "Architecture choices must remain within this explicit project constraint.",
                "constraint",
            ),
            "assumption": (
                "Assumption validation",
                "The design depends on this assumption and should revisit it when evidence changes.",
                "assumption",
            ),
        }
        name, description, category = defaults[requirement_type]
        return name, description, 0.7, category

    def _technical_categories(self, text: str) -> set[str]:
        tokens = self._tokens(text)
        categories: set[str] = set()
        signals = {
            "realtime": {"realtime", "live", "stream", "instant", "websocket"},
            "event_processing": {"event", "telemetry", "sensor", "device", "iot", "message", "async", "asynchronous"},
            "geospatial": {"location", "geospatial", "map", "route", "distance", "coordinate", "gps"},
            "transactional": {"payment", "refund", "transaction", "ledger", "atomic", "checkout", "settlement"},
            "security": {"security", "secure", "auth", "authentication", "authorization", "encrypt", "privacy", "access"},
            "availability": {"availability", "uptime", "resilience", "recovery", "failover", "redundancy"},
            "performance": {"latency", "performance", "responsive", "millisecond", "fast"},
            "scalability": {"scale", "scalable", "concurrent", "traffic", "volume", "throughput", "growth"},
            "audit": {
                "audit", "trace", "compliance", "evidence", "history", "governance",
                "provenance", "tamper",
            },
            "integration": {"integration", "external", "webhook", "provider", "gateway", "thirdparty"},
            "offline": {"offline", "sync", "synchronization", "disconnected"},
            "media": {"media", "file", "image", "video", "audio", "document", "upload"},
        }
        for category, category_signals in signals.items():
            if tokens & category_signals:
                categories.add(category)
        return categories

    def _role_affinity(self, text: str, requirement_type: str) -> int:
        lowered = text.lower()
        if requirement_type == "functional_requirement" and any(
            word in lowered for word in ("service", "core", "workflow", "interface", "api", "module")
        ):
            return 1
        if requirement_type in {"non_functional_requirement", "constraint"} and any(
            word in lowered for word in ("gateway", "database", "event", "security", "observability", "deployment")
        ):
            return 1
        return 0

    def _component_type(self, name: str) -> str:
        lowered = name.lower()
        if any(word in lowered for word in ("service", "module", "core", "worker")):
            return "service_module"
        return "architecture_component"

    def _tokens(self, text: str) -> set[str]:
        tokens: set[str] = set()
        for raw in re.findall(r"[a-zA-Z0-9]+", text.lower()):
            if len(raw) < 3 or raw in STOP_WORDS:
                continue
            token = raw
            if len(token) > 5 and token.endswith("ies"):
                token = f"{token[:-3]}y"
            elif len(token) > 5 and token.endswith("es"):
                token = token[:-2]
            elif len(token) > 4 and token.endswith("s"):
                token = token[:-1]
            tokens.add(token)
        return tokens

    def _slug(self, value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
        return slug or "item"

    def _dedupe(self, values: Iterable[str]) -> list[str]:
        return list(dict.fromkeys(values))

    def _dedupe_nodes(self, nodes: Iterable[CausalGraphNode]) -> list[CausalGraphNode]:
        return list({node.id: node for node in nodes}.values())

    def _known_modules(self) -> set[str]:
        return {
            "requirements", "architectures", "comparison", "recommendation", "database",
            "api", "deployment", "diagrams", "documentation",
        }
