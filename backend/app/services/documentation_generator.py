from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer

from app.schemas.domain import WorkspaceResponse


class DocumentationGenerator:
    def build_markdown(self, workspace: WorkspaceResponse) -> str:
        architecture_lines: list[str] = []
        for architecture in workspace.architectures:
            architecture_lines.extend(
                [
                    f"### {architecture.name}",
                    architecture.overview,
                    "",
                    "**Advantages**",
                    *[f"- {item}" for item in architecture.advantages],
                    "",
                    "**Disadvantages**",
                    *[f"- {item}" for item in architecture.disadvantages],
                    "",
                ]
            )

        diagrams = "\n".join(
            f"- {key}: {artifact.title}" for key, artifact in workspace.diagrams.items()
        )
        api_groups = "\n".join(
            f"- {group.name}: {len(group.endpoints)} endpoints"
            for group in workspace.api_design.groups
        )
        graph = workspace.causal_graph
        graph_lines = ["- Causal graph not available"]
        if graph is not None:
            graph_lines = [
                f"- {len(graph.nodes)} traceable nodes",
                f"- {len(graph.edges)} validated relationships",
                f"- {len(graph.orphan_node_ids)} unjustified architecture components",
            ]

        return "\n".join(
            [
                f"# {workspace.title}",
                "",
                "## Executive Summary",
                workspace.recommendation.decision_summary,
                "",
                "## Requirements",
                workspace.requirements.summary,
                f"Extraction source: {workspace.requirements.analysis_source}",
                "",
                "### Functional Requirements",
                *[f"- {item}" for item in workspace.requirements.functional_requirements],
                "",
                "### Non-Functional Requirements",
                *[f"- {item}" for item in workspace.requirements.non_functional_requirements],
                "",
                "### Confirmed Integrations",
                *([f"- {item}" for item in workspace.requirements.integrations] or ["- None confirmed"]),
                "",
                "### Open Questions",
                *([f"- {item}" for item in workspace.requirements.open_questions] or ["- None recorded"]),
                "",
                "## Clarification Snapshot",
                f"Completeness score: {workspace.clarification_plan.completeness_score}%",
                "",
                "## Architecture Alternatives",
                *architecture_lines,
                "## Recommendation",
                *[f"- {item}" for item in workspace.recommendation.why],
                "",
                "## Database Design",
                *[
                    f"- {entity.name}: {entity.description}"
                    for entity in workspace.database_design.entities
                ],
                "",
                "## API Design",
                api_groups,
                "",
                "## Deployment Plan",
                f"Replicas: {workspace.deployment_plan.replicas if workspace.deployment_plan.replicas else 'unknown'}",
                f"Regions: {', '.join(workspace.deployment_plan.regions) if workspace.deployment_plan.regions else 'unknown'}",
                f"Strategy: {workspace.deployment_plan.deployment_strategy or 'not decided'}",
                f"Availability: {workspace.deployment_plan.availability_configuration or 'not specified'}",
                "",
                "### Stack rationale (which workload needs each technology)",
                *(
                    [f"- {item}" for item in workspace.deployment_plan.stack_rationale]
                    or ["- Stack rationale pending deployment clarification."]
                ),
                "",
                "### Target stack",
                *[f"- {item}" for item in workspace.deployment_plan.target_stack],
                "",
                "## Diagrams",
                diagrams,
                "",
                "## Requirement-to-Architecture Traceability",
                *graph_lines,
                "",
                "Relationships are derived from validated requirements and generated artifacts; semantic confidence is recorded where matching is approximate.",
                "",
                "## Consistency Review",
                *(
                    [f"- [{issue.severity}] {issue.message}" for issue in workspace.consistency_issues]
                    or ["- No consistency findings recorded."]
                ),
            ]
        )

    def render_pdf(self, title: str, markdown: str) -> bytes:
        buffer = BytesIO()
        document = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        heading_style = styles["Heading2"]
        body_style = styles["BodyText"]
        code_style = ParagraphStyle("Code", parent=styles["Code"], leading=12)

        story = [Paragraph(escape(title), styles["Title"]), Spacer(1, 12)]

        for raw_line in markdown.splitlines():
            line = raw_line.rstrip()
            if not line:
                story.append(Spacer(1, 6))
                continue
            if line.startswith("# "):
                story.append(Paragraph(escape(line[2:]), styles["Title"]))
            elif line.startswith("## "):
                story.append(Paragraph(escape(line[3:]), heading_style))
            elif line.startswith("### "):
                story.append(Paragraph(escape(line[4:]), styles["Heading3"]))
            elif line.startswith("- "):
                story.append(Paragraph(escape(f"* {line[2:]}"), body_style))
            elif line.startswith("**") and line.endswith("**"):
                story.append(Paragraph(escape(line.strip("*")), styles["Heading4"]))
            elif line.startswith("```"):
                story.append(Preformatted(line, code_style))
            else:
                story.append(Paragraph(escape(line), body_style))

        document.build(story)
        return buffer.getvalue()
