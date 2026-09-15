"""Whole-project reasoning for the architecture assistant.

The deterministic layer in ``assistant_intel`` handles the model of record —
listing, counting, adding, renaming, deleting. This module handles the
questions a design partner is actually asked: does the API surface cover the
requirements, where is the single point of failure, why is this technology
here, is the recommended style justified, what breaks if traffic grows tenfold.

Every answer is computed from the workspace: the requirement model, the causal
graph, the architecture options and their comparison scorecards, the API and
database designs, the deployment plan, the prototype and the recorded ADRs.
Nothing is asserted that the project does not support, and each claim is
labelled Confirmed, Inferred, Recommendation or Unknown so the reader can tell
a fact from an opinion.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from app.schemas.domain import (
    ArchitectureOption,
    CounterfactualSimulationRequest,
    WorkspaceResponse,
)
from app.services.assistant_intel import (
    ProjectIndex,
    clean_text,
    containment,
    plural,
    similarity,
    strip_query_noise,
    tokens,
    truncate,
)

# Markers that indicate a component already has redundancy designed in, so it
# should not be reported as a single point of failure.
REDUNDANCY_MARKERS = {
    "replica", "replication", "cluster", "failover", "multi-zone", "multi zone",
    "active-active", "active-passive", "standby", "redundant", "load balanced",
    "load-balanced", "autoscal", "sharded", "quorum",
}

# Component roles that are stateless by nature and cheap to run more than one
# of, so a missing redundancy note is less alarming.
STATELESS_HINTS = {"gateway", "api", "web", "frontend", "worker", "service"}

CONCEPTS: dict[str, tuple[str, str]] = {
    "non_functional_requirement": (
        r"\bwhat (?:is|are) (?:an? )?(?:nfrs?|non[- ]?functional requirements?)\b",
        "A non-functional requirement states a quality the system must have — how fast, "
        "how available, how secure, how durable — rather than a feature it must provide. "
        "A functional requirement says what someone can do; a non-functional requirement "
        "says how well the system must do it.",
    ),
    "functional_requirement": (
        r"\bwhat (?:is|are) (?:an? )?(?:frs?|functional requirements?)\b",
        "A functional requirement states an observable capability: who can do what to "
        "which business object.",
    ),
    "blast_radius": (
        r"\bwhat (?:is|does) (?:the )?blast[- ]radius\b|\bblast radius mean\b",
        "Blast radius is how far a single failure spreads. The analysis takes one "
        "component out and reports which other components go down, which degrade and "
        "which are unaffected, then scores the severity.",
    ),
    "causal_graph": (
        r"\b(?:what (?:is|does)|explain) (?:the )?causal graph\b",
        "The causal graph records why every artifact exists. Requirements are linked to "
        "the decisions, components, APIs, entities and diagrams derived from them, so any "
        "item can be traced back to the requirement that justifies it and forward to "
        "everything that would need revalidating if it changed.",
    ),
    "actor": (
        r"\bwhat (?:is|are) (?:an? )?actors?\b",
        "An actor is a person, organisational role or active machine participant that "
        "operates the system. Passive storage and external software belong in "
        "integrations instead.",
    ),
    "adr": (
        r"\bwhat (?:is|are) (?:an? )?adrs?\b|\barchitecture decision record",
        "An ADR is an immutable record of one architectural decision: the context it was "
        "taken in, the decision itself and the consequences accepted with it.",
    ),
}


@dataclass
class AnalysisResult:
    answer: str
    evidence: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)
    confidence: str = "high"


@dataclass
class Finding:
    """One critique finding, labelled by how sure the project makes us."""

    label: str  # "Confirmed issue" | "Potential risk" | "Needs verification"
    title: str
    detail: str
    evidence: list[str] = field(default_factory=list)
    # Classification for the risk view, which shows the same findings.
    category: str = "architecture_complexity"
    severity: str = "medium"
    components: list[str] = field(default_factory=list)
    recommendation: str = ""

    @property
    def needs_verification(self) -> bool:
        return self.label == "Needs verification"


class AnalysisEngine:
    """Deterministic analysis over the whole workspace."""

    # ------------------------------------------------------------- coverage

    def requirement_coverage(
        self, workspace: WorkspaceResponse, index: ProjectIndex
    ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """Split functional requirements into covered and uncovered.

        A requirement counts as covered when an API endpoint cites its id, or
        when the causal graph links it to an implementing artifact. Both are
        recorded facts, so this never guesses.
        """
        cited: set[str] = set()
        for group in workspace.api_design.groups:
            for endpoint in group.endpoints:
                cited.update(endpoint.requirement_ids)

        linked: set[str] = set()
        graph = workspace.causal_graph
        if graph is not None:
            implementing = {
                node.id
                for node in graph.nodes
                if node.type
                in {
                    "architecture_component",
                    "service_module",
                    "api",
                    "database_entity",
                    "infrastructure",
                }
            }
            for edge in graph.edges:
                if edge.target_node_id in implementing:
                    linked.add(edge.source_node_id)

        covered: list[tuple[str, str]] = []
        uncovered: list[tuple[str, str]] = []
        for item in index.items("functional_requirement"):
            target = covered if item.id in cited or item.id in linked else uncovered
            target.append((item.id, item.text))
        return covered, uncovered

    def coverage_answer(
        self, workspace: WorkspaceResponse, index: ProjectIndex
    ) -> AnalysisResult:
        covered, uncovered = self.requirement_coverage(workspace, index)
        total = len(covered) + len(uncovered)
        if total == 0:
            return AnalysisResult(
                answer=(
                    "Unknown: there are no functional requirements recorded yet, so there "
                    "is nothing to check coverage against."
                ),
                confidence="high",
            )
        endpoint_count = sum(
            len(group.endpoints) for group in workspace.api_design.groups
        )
        if not uncovered:
            return AnalysisResult(
                answer=(
                    f"Confirmed: all {total} functional "
                    f"{plural(total, 'requirement')} "
                    f"{plural(total, 'is', 'are')} covered. The {endpoint_count} recorded "
                    f"{plural(endpoint_count, 'endpoint')} and the causal graph between them "
                    "account for every requirement in the model."
                ),
                evidence=[item_id for item_id, _ in covered[:8]],
            )
        listing = " ".join(
            f"{item_id}: {truncate(text, 90)}" for item_id, text in uncovered[:6]
        )
        more = f" …and {len(uncovered) - 6} more." if len(uncovered) > 6 else ""
        return AnalysisResult(
            answer=(
                f"Confirmed: {len(covered)} of {total} functional requirements are covered "
                f"by the {endpoint_count} recorded "
                f"{plural(endpoint_count, 'endpoint')} or by a causal link to an "
                f"implementing artifact. {len(uncovered)} "
                f"{plural(len(uncovered), 'is', 'are')} not. Uncovered: {listing}{more} "
                "Inferred: an uncovered requirement usually means either the API design has "
                "not caught up with it or the requirement is not actually implementable as "
                "stated. Recommendation: review each one before treating the design as complete."
            ),
            evidence=[item_id for item_id, _ in uncovered[:8]],
            confidence="high",
            follow_ups=[f"why does {uncovered[0][0]} exist" for _ in (0,)],
        )

    # ----------------------------------------------------------------- SPOF

    def single_points_of_failure(
        self, architecture: ArchitectureOption
    ) -> list[tuple[str, int, bool]]:
        """Rank components by how many others depend on them.

        Uses the recorded ``dependencies`` edges rather than a generic role map,
        so the answer reflects this architecture and not an assumption.
        """
        dependents: Counter[str] = Counter()
        by_name = {component.name.casefold(): component for component in architecture.components}
        for component in architecture.components:
            for dependency in component.dependencies:
                key = dependency.casefold()
                if key in by_name:
                    dependents[by_name[key].name] += 1

        ranked: list[tuple[str, int, bool]] = []
        for name, count in dependents.most_common():
            component = by_name[name.casefold()]
            described = " ".join(
                [component.responsibility, *component.technologies, *component.interactions]
            ).casefold()
            redundant = any(marker in described for marker in REDUNDANCY_MARKERS)
            ranked.append((name, count, redundant))
        return ranked

    def spof_answer(
        self, workspace: WorkspaceResponse, architecture: ArchitectureOption
    ) -> AnalysisResult:
        ranked = self.single_points_of_failure(architecture)
        if not ranked:
            return AnalysisResult(
                answer=(
                    f"Unknown: {architecture.name} records no component-to-component "
                    "dependencies, so there is nothing to derive a single point of failure "
                    "from. Recommendation: capture each component's runtime dependencies "
                    "before relying on this analysis."
                ),
                confidence="low",
            )
        exposed = [entry for entry in ranked if not entry[2]]
        top = exposed[0] if exposed else ranked[0]
        name, count, redundant = top
        deployment = workspace.deployment_plan
        replica_note = (
            f"The deployment plan records {deployment.replicas} replicas."
            if getattr(deployment, "replicas", None)
            else "The deployment plan records no replica count."
        )
        verdict = (
            f"Confirmed: {name} has the most dependents in {architecture.name} — "
            f"{count} {plural(count, 'component')} {plural(count, 'relies', 'rely')} "
            "on it directly."
        )
        if redundant:
            verdict += (
                " Its description already mentions redundancy, so a single instance "
                "failing is not necessarily a total outage."
            )
        else:
            verdict += (
                " Nothing in its description mentions replication, failover or clustering, "
                "so on the recorded design it is a single point of failure."
            )
        others = ", ".join(
            f"{entry[0]} ({entry[1]})" for entry in ranked[1:4]
        )
        return AnalysisResult(
            answer=(
                f"{verdict} {replica_note} "
                + (f"Next most depended on: {others}. " if others else "")
                + "Recommendation: run the blast-radius simulation on it to see exactly what "
                "degrades, then decide whether redundancy is worth the operational cost."
            ),
            components=[name],
            confidence="high" if not redundant else "medium",
            follow_ups=[f"what breaks if {name} fails"],
        )

    # -------------------------------------------------------------- critique

    def critique(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        index: ProjectIndex,
    ) -> list[Finding]:
        findings: list[Finding] = []

        for issue in workspace.consistency_issues[:3]:
            findings.append(
                Finding(
                    label="Confirmed issue" if issue.severity == "error" else "Potential risk",
                    title=issue.code.replace("-", " "),
                    detail=issue.message,
                    evidence=issue.related_ids[:4],
                    category="data",
                    severity="high" if issue.severity == "error" else "medium",
                    recommendation="Resolve the inconsistency before generating downstream artifacts.",
                )
            )

        _, uncovered = self.requirement_coverage(workspace, index)
        if uncovered:
            findings.append(
                Finding(
                    label="Confirmed issue",
                    title="Requirements with no implementing artifact",
                    detail=(
                        f"{len(uncovered)} functional requirement"
                        f"{'s are' if len(uncovered) != 1 else ' is'} not cited by any API "
                        "endpoint and not linked to an implementing component in the causal graph."
                    ),
                    evidence=[item_id for item_id, _ in uncovered[:4]],
                    category="architecture_complexity",
                    severity="high",
                    recommendation=(
                        "Either design the API and components that satisfy them, or remove "
                        "requirements the project does not intend to build."
                    ),
                )
            )

        graph = workspace.causal_graph
        if graph is not None and graph.orphan_node_ids:
            names = [
                node.name for node in graph.nodes if node.id in set(graph.orphan_node_ids[:4])
            ]
            findings.append(
                Finding(
                    label="Confirmed issue",
                    title="Components with no originating requirement",
                    detail=(
                        f"{', '.join(names) or 'Several components'} cannot be traced back to a "
                        "validated requirement, so they are either unjustified or the "
                        "requirement that motivated them was never recorded."
                    ),
                    evidence=graph.orphan_node_ids[:4],
                    category="architecture_complexity",
                    severity="medium",
                    components=names[:6],
                    recommendation=(
                        "Record the requirement that motivates each one, or remove it."
                    ),
                )
            )

        ranked = self.single_points_of_failure(architecture)
        exposed = [entry for entry in ranked if not entry[2] and entry[1] >= 2]
        if exposed:
            name, count, _ = exposed[0]
            findings.append(
                Finding(
                    label="Potential risk",
                    title=f"{name} is a single point of failure",
                    detail=(
                        f"{count} components depend on {name} and its description records no "
                        "replication or failover."
                    ),
                    evidence=[name],
                    category="resilience",
                    severity="high",
                    components=[name],
                    recommendation=(
                        "Review isolation, replication and failover for the shared dependency, "
                        "then re-run the blast-radius simulation."
                    ),
                )
            )

        complexity = self._complexity_finding(workspace, architecture, index)
        if complexity is not None:
            findings.append(complexity)

        unjustified = self._unjustified_technology(workspace, architecture, index)
        if unjustified is not None:
            findings.append(unjustified)

        deployment = self._deployment_mismatch(workspace, index)
        if deployment is not None:
            findings.append(deployment)

        return findings

    def _complexity_finding(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        index: ProjectIndex,
    ) -> Finding | None:
        components = len(architecture.components)
        requirements = index.count("functional_requirement")
        if requirements == 0 or components <= 3:
            return None
        # More services than requirements means most services carry less than one
        # requirement's worth of behaviour.
        if components <= requirements:
            return None
        return Finding(
            label="Needs verification",
            title="More components than requirements",
            detail=(
                f"{architecture.name} defines {components} components for {requirements} "
                "functional requirements. Each additional service adds deployment, "
                "monitoring and failure modes, so this is worth justifying deliberately "
                "rather than by default."
            ),
            evidence=[component.name for component in architecture.components[:4]],
            category="operations",
            severity="low",
            recommendation=(
                "Justify each component against a requirement, or merge the ones that do "
                "not carry distinct behaviour."
            ),
        )

    def _unjustified_technology(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        index: ProjectIndex,
    ) -> Finding | None:
        """Flag heavyweight technology the requirement text does not motivate."""
        heavyweight = {
            "kafka": ("high-volume event streaming", r"stream|event|throughput|replay|pipeline"),
            "elasticsearch": ("full-text search at scale", r"search|index|full[- ]text"),
            "kubernetes": ("multi-service orchestration", r"orchestrat|scal|cluster|container"),
            "redis": ("caching or low-latency shared state", r"cach|latenc|session|realtime|real[- ]time"),
            "cassandra": ("very large write volumes", r"volume|write|scale|partition"),
        }
        requirement_text = " ".join(
            [
                *(item.text for item in index.items("functional_requirement")),
                *(item.text for item in index.items("non_functional_requirement")),
                *(item.text for item in index.items("constraint")),
                workspace.original_prompt or "",
                workspace.business_context or "",
            ]
        ).casefold()

        for component in architecture.components:
            for technology in component.technologies:
                key = technology.casefold()
                for marker, (purpose, pattern) in heavyweight.items():
                    if marker not in key:
                        continue
                    if re.search(pattern, requirement_text):
                        continue
                    if marker in requirement_text:
                        continue
                    return Finding(
                        label="Needs verification",
                        title=f"{technology} is not motivated by the requirements",
                        detail=(
                            f"{technology} is used by {component.name}, which is normally "
                            f"chosen for {purpose}. Nothing in the recorded requirements "
                            "describes that need. It may still be the right call, but the "
                            "justification is not in the project."
                        ),
                        evidence=[component.name],
                        category="operations",
                        severity="medium",
                        components=[component.name],
                        recommendation=(
                            "Record the requirement that needs it, or replace it with the "
                            "simplest thing that satisfies the stated need."
                        ),
                    )
        return None

    def _deployment_mismatch(
        self, workspace: WorkspaceResponse, index: ProjectIndex
    ) -> Finding | None:
        quality_text = " ".join(
            item.text for item in index.items("non_functional_requirement")
        ).casefold()
        deployment = workspace.deployment_plan
        mentions_availability = bool(
            re.search(r"availab|uptime|failover|resilien", quality_text)
        )
        replicas = getattr(deployment, "replicas", None)
        if mentions_availability and (replicas is None or replicas < 2):
            return Finding(
                label="Potential risk",
                title="Availability is required but the deployment runs single instances",
                detail=(
                    "A quality requirement mentions availability, yet the deployment plan "
                    f"records {replicas if replicas is not None else 'no'} replica"
                    f"{'' if replicas == 1 else 's'}. A single instance cannot meet an "
                    "availability target during a restart or a node failure."
                ),
                evidence=[
                    item.id
                    for item in index.items("non_functional_requirement")
                    if re.search(r"availab|uptime|failover|resilien", item.text, re.IGNORECASE)
                ][:3],
                category="reliability",
                severity="high",
                recommendation=(
                    "Set a replica count that can survive a restart, or record that the "
                    "availability requirement does not apply to this tier."
                ),
            )
        return None

    def critique_answer(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        index: ProjectIndex,
    ) -> AnalysisResult:
        findings = self.critique(workspace, architecture, index)
        if not findings:
            return AnalysisResult(
                answer=(
                    f"Confirmed: I found no evidenced problems in {architecture.name}. Every "
                    "functional requirement is linked to an implementing artifact, no "
                    "component is untraceable, and the consistency checks are clean. "
                    "Unknown: this checks what the project records, not whether the "
                    "requirements themselves are complete."
                ),
                confidence="medium",
                follow_ups=["what am I missing", "where is the single point of failure"],
            )
        body = " ".join(
            f"[{finding.label}] {finding.title} — {finding.detail}"
            + (f" Evidence: {', '.join(finding.evidence)}." if finding.evidence else "")
            for finding in findings
        )
        confirmed = sum(1 for finding in findings if finding.label == "Confirmed issue")
        return AnalysisResult(
            answer=(
                f"I found {len(findings)} finding{'s' if len(findings) != 1 else ''} in "
                f"{architecture.name}, {confirmed} of which the project confirms outright. "
                f"{body} "
                "Recommendation: address the confirmed issues first; the rest need a "
                "decision from you rather than a change from me."
            ),
            evidence=[item for finding in findings for item in finding.evidence][:10],
            confidence="high",
            follow_ups=["do the APIs cover all requirements", "where is the single point of failure"],
        )

    # --------------------------------------------------- component questions

    def find_component(
        self, architecture: ArchitectureOption, reference: str
    ) -> tuple[str, str] | None:
        """Locate a component by name or by a technology it uses."""
        needle = clean_text(reference).casefold()
        if not needle:
            return None
        for component in architecture.components:
            if component.name.casefold() == needle:
                return component.name, "name"
        for component in architecture.components:
            if needle in component.name.casefold():
                return component.name, "name"
        for component in architecture.components:
            if any(needle in technology.casefold() for technology in component.technologies):
                return component.name, "technology"
        best, best_score = None, 0.0
        for component in architecture.components:
            score = similarity(needle, f"{component.name} {component.responsibility}")
            if score > best_score:
                best, best_score = component.name, score
        return (best, "name") if best and best_score >= 0.5 else None

    def explain_component(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        index: ProjectIndex,
        reference: str,
    ) -> AnalysisResult | None:
        located = self.find_component(architecture, reference)
        if located is None:
            return None
        name, matched_by = located
        component = next(
            item for item in architecture.components if item.name == name
        )

        graph = workspace.causal_graph
        requirements: list[str] = []
        node_id = None
        if graph is not None:
            node = next(
                (
                    item
                    for item in graph.nodes
                    if item.name == name
                    and item.metadata.get("architecture_id") in {None, architecture.id}
                ),
                None,
            )
            if node is not None:
                node_id = node.id
                incoming = {
                    edge.source_node_id
                    for edge in graph.edges
                    if edge.target_node_id == node.id
                }
                requirements = [
                    f"{item.id} ({truncate(item.name, 50)})"
                    for item in graph.nodes
                    if item.id in incoming
                    and item.type
                    in {
                        "functional_requirement",
                        "non_functional_requirement",
                        "constraint",
                        "technical_characteristic",
                    }
                ][:5]

        parts = [
            f"Confirmed: {name} is a component of {architecture.name}. "
            f"Its recorded responsibility is '{truncate(component.responsibility, 160)}'."
        ]
        if matched_by == "technology":
            parts.append(
                f"The technology you named is listed under it: "
                f"{', '.join(component.technologies) or 'none recorded'}."
            )
        if requirements:
            parts.append(f"It traces back to: {', '.join(requirements)}.")
        else:
            parts.append(
                "Unknown: no requirement is linked to it in the causal graph, so its "
                "justification is not recorded in the project."
            )
        if component.dependencies:
            parts.append(f"It depends on: {', '.join(component.dependencies[:6])}.")

        adrs = [
            record
            for record in workspace.adrs
            if name.casefold() in f"{record.title} {record.decision} {record.context}".casefold()
        ][:2]
        if adrs:
            parts.append(
                "Recorded decisions: "
                + "; ".join(f"{record.title} — {truncate(record.decision, 90)}" for record in adrs)
                + "."
            )

        return AnalysisResult(
            answer=" ".join(parts),
            evidence=[entry.split(" ")[0] for entry in requirements] + ([node_id] if node_id else []),
            components=[name],
            confidence="high" if requirements else "medium",
            follow_ups=[f"what breaks if {name} is removed"],
        )

    def component_not_found(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        index: ProjectIndex,
        reference: str,
    ) -> AnalysisResult:
        """Answer honestly when the thing asked about is not in the project.

        This used to fall through to the model, which then timed out and told
        the user nothing. The project already knows the answer: it is not here.
        """
        name = truncate(clean_text(reference), 60)
        components = ", ".join(item.name for item in architecture.components[:8]) or "none"
        mentioned_in: list[str] = []
        for target_type in ("functional_requirement", "non_functional_requirement", "constraint"):
            mentioned_in.extend(
                item.id
                for item in index.items(target_type)
                if tokens(reference) and tokens(reference) <= tokens(item.text)
            )

        parts = [
            f"Confirmed: there is no component called '{name}' in {architecture.name}. "
            f"Its components are: {components}."
        ]
        if mentioned_in:
            parts.append(
                f"It is mentioned in {', '.join(mentioned_in[:4])}, so the requirement "
                "exists but nothing in the architecture implements it yet."
            )
        else:
            parts.append(
                "It is not named in the requirements either, so this project has no record "
                "of it at all."
            )
        parts.append(
            "Recommendation: if it should exist, add the requirement that motivates it "
            "first, so the component stays traceable."
        )
        return AnalysisResult(
            answer=" ".join(parts),
            evidence=mentioned_in[:4],
            confidence="high",
            follow_ups=["list the functional requirements"],
        )

    def justify_technology(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        index: ProjectIndex,
        reference: str,
    ) -> AnalysisResult:
        """Answer "do we really need X?" against the recorded requirements."""
        located = self.find_component(architecture, reference)
        name = clean_text(reference)
        requirement_text = " ".join(
            [
                *(item.text for item in index.items("functional_requirement")),
                *(item.text for item in index.items("non_functional_requirement")),
                *(item.text for item in index.items("constraint")),
                workspace.original_prompt or "",
            ]
        ).casefold()
        mentioned = name.casefold() in requirement_text

        if located is None:
            return AnalysisResult(
                answer=(
                    f"Confirmed: nothing named '{truncate(name, 60)}' is part of "
                    f"{architecture.name}, so there is nothing to justify. Recorded "
                    f"components: {', '.join(item.name for item in architecture.components[:8]) or 'none'}."
                ),
                confidence="high",
            )

        component_name, _ = located
        explanation = self.explain_component(workspace, architecture, index, reference)
        has_requirements = bool(explanation and "traces back to" in explanation.answer)

        if mentioned:
            verdict = (
                f"Confirmed: {name} is named in the project's own requirements, so it is "
                "justified by something you asked for rather than by a default."
            )
        elif has_requirements:
            verdict = (
                f"Confirmed: {component_name} is linked to recorded requirements, but "
                f"{name} itself is a technology choice rather than a stated requirement."
            )
        else:
            verdict = (
                f"Inferred: {name} is not named anywhere in the recorded requirements and "
                f"{component_name} has no linked requirement, so on the current project "
                "there is no written justification for it."
            )
        return AnalysisResult(
            answer=(
                f"{verdict} "
                + (explanation.answer if explanation else "")
                + " Recommendation: keep it only if you expect a need the requirements do "
                "not yet state, and record that need as a requirement so the decision is "
                "traceable. I can simulate the architecture without it if that helps."
            ),
            evidence=explanation.evidence if explanation else [],
            components=[component_name],
            confidence="medium",
            follow_ups=[f"what breaks if {component_name} is removed"],
        )

    # --------------------------------------------------------- architecture

    def compare_answer(
        self, workspace: WorkspaceResponse, reference: str
    ) -> AnalysisResult:
        """Answer "is X really necessary" / "would Y be better" from the scorecards."""
        recommendation = workspace.recommendation
        scorecards = workspace.comparison.scorecards
        if not scorecards:
            return AnalysisResult(
                answer=(
                    "Unknown: no architecture comparison has been recorded for this "
                    "project, so I cannot rank the options."
                ),
                confidence="low",
            )
        ranked = sorted(scorecards, key=lambda card: card.weighted_score, reverse=True)
        best = ranked[0]
        named = None
        if reference:
            named = next(
                (
                    card
                    for card in scorecards
                    if similarity(reference, card.architecture_name) >= 0.45
                ),
                None,
            )

        parts = [
            f"Confirmed: ArchAI ranks {best.architecture_name} first with a weighted score "
            f"of {best.weighted_score:.1f}."
        ]
        if recommendation.why:
            parts.append("Recorded rationale: " + " ".join(recommendation.why[:3]))
        if named is not None and named.architecture_id != best.architecture_id:
            gap = best.weighted_score - named.weighted_score
            parts.append(
                f"{named.architecture_name} scores {named.weighted_score:.1f}, {gap:.1f} "
                "lower. "
                + (
                    "Its recorded risks: " + "; ".join(named.risks[:2]) + "."
                    if named.risks
                    else "No specific risks are recorded against it."
                )
            )
            reasons = recommendation.why_not.get(named.architecture_name) or recommendation.why_not.get(
                named.architecture_id
            )
            if reasons:
                parts.append(f"Why it was not chosen: {'; '.join(reasons[:3])}.")
        elif named is not None:
            parts.append(f"{named.architecture_name} is the currently recommended option.")

        others = ", ".join(
            f"{card.architecture_name} ({card.weighted_score:.1f})" for card in ranked[1:4]
        )
        if others:
            parts.append(f"Other options scored: {others}.")
        parts.append(
            "Inferred: the ranking reflects the weights currently set for this project. "
            "Recommendation: change the weights in the comparison view if your priorities "
            "differ, and the ranking recomputes deterministically."
        )
        return AnalysisResult(
            answer=" ".join(parts),
            confidence="high",
            follow_ups=["what am I missing", "find problems with my architecture"],
        )

    # ----------------------------------------------------------- simulation

    def simulate_answer(
        self, workspace: WorkspaceResponse, message: str
    ) -> AnalysisResult | None:
        """Run the recorded counterfactual simulator on a what-if question."""
        from app.services.counterfactual_simulator import CounterfactualSimulator

        result = CounterfactualSimulator().simulate(
            workspace, CounterfactualSimulationRequest(scenario=clean_text(message)[:1000])
        )
        if not result.changed_variables:
            supported = (
                "expected users, peak traffic multiplier, availability percent, latency, "
                "team size, geographic regions, realtime requirement, compliance level, "
                "data volume and growth rate"
            )
            return AnalysisResult(
                answer=(
                    "Unknown: I could not read a simulable variable out of that question, so "
                    "nothing was simulated and nothing changed. The simulator works on "
                    f"{supported}. Recommendation: phrase it with a value, for example "
                    "'what happens at 5 million users', 'what if availability becomes 99.99%' "
                    "or 'simulate a team size of 4'."
                ),
                confidence="low",
            )

        changes = ", ".join(
            f"{change.variable.replace('_', ' ')}: "
            f"{change.original_value} → {change.hypothetical_value}"
            for change in result.changed_variables[:4]
        )
        before, after = result.before, result.after
        verdict = (
            "still suitable"
            if result.current_architecture_still_suitable
            else "no longer the best fit"
        )
        parts = [
            f"Confirmed: I simulated {changes}.",
            f"{before.architecture_name} moves from a suitability of "
            f"{before.suitability_score:.0f} to {after.suitability_score:.0f} "
            f"(rank {before.rank} → {after.rank}), risk {before.risk_level} → "
            f"{after.risk_level}. On that basis it is {verdict}.",
        ]
        if result.recommended_architecture_name != before.architecture_name:
            parts.append(
                f"The simulation favours {result.recommended_architecture_name} under these "
                "conditions."
            )
        if result.explanation:
            parts.append(" ".join(result.explanation[:3]))
        if result.conflicts:
            parts.append("Conflicts: " + "; ".join(result.conflicts[:2]) + ".")
        if result.estimate_notes:
            parts.append("Unknown: " + "; ".join(result.estimate_notes[:2]) + ".")
        parts.append(
            "This is a simulation against the recorded model; it does not change the project."
        )
        return AnalysisResult(
            answer=" ".join(parts),
            components=result.affected_components[:6],
            evidence=result.directly_affected_node_ids[:6],
            confidence=result.confidence.casefold(),
        )

    # ------------------------------------------------------------- concepts

    def concept_answer(
        self, workspace: WorkspaceResponse, index: ProjectIndex, message: str
    ) -> AnalysisResult | None:
        """Define a term, then ground it in this project rather than in theory."""
        for key, (pattern, definition) in CONCEPTS.items():
            if not re.search(pattern, message, re.IGNORECASE):
                continue
            grounding = self._concept_grounding(workspace, index, key)
            return AnalysisResult(
                answer=f"{definition} {grounding}",
                confidence="high",
            )
        return None

    def _concept_grounding(
        self, workspace: WorkspaceResponse, index: ProjectIndex, key: str
    ) -> str:
        if key in {"functional_requirement", "non_functional_requirement", "actor"}:
            target = "domain_entity" if key == "entity" else key
            items = index.items(target)
            if not items:
                return (
                    f"In this project none are recorded yet, so there is no example to "
                    "point at."
                )
            example = items[0]
            return (
                f"In this project there are {index.count_phrase(target)}; "
                f"{example.id} is one: '{truncate(example.text, 120)}'."
            )
        if key == "causal_graph":
            graph = workspace.causal_graph
            if graph is None:
                return "This project has no causal graph recorded yet."
            return (
                f"This project's graph has {len(graph.nodes)} nodes and "
                f"{len(graph.edges)} links"
                + (
                    f", with {len(graph.orphan_node_ids)} node(s) not traceable to a requirement."
                    if graph.orphan_node_ids
                    else ", and every node traces back to a requirement."
                )
            )
        if key == "adr":
            return (
                f"This project has {len(workspace.adrs)} recorded decision(s)."
                if workspace.adrs
                else "This project has no decisions recorded yet."
            )
        if key == "blast_radius":
            return (
                "You can run it from the Blast radius view, or ask me "
                "'where is the single point of failure'."
            )
        return ""

    # ------------------------------------------------------------- briefing

    def project_briefing(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        index: ProjectIndex,
        *,
        sections: set[str] | None = None,
    ) -> AnalysisResult:
        """Walk the whole project, section by section.

        "Explain everything" is a fair request and the project can answer it in
        full: every collection, the recommended architecture, the API and data
        design, deployment, traceability and what is still unknown. Nothing
        here is generated — it is the recorded model, read out.
        """
        wanted = sections or set()

        def include(name: str) -> bool:
            return not wanted or name in wanted

        blocks: list[str] = []
        evidence: list[str] = []

        requirements = workspace.requirements
        header = [
            f"{workspace.title} — {requirements.domain}.",
            truncate(requirements.summary, 320),
        ]
        if workspace.business_context:
            header.append(f"Business context: {truncate(workspace.business_context, 200)}")
        blocks.append("PROJECT\n" + "\n".join(header))

        for target_type, title in (
            ("functional_requirement", "FUNCTIONAL REQUIREMENTS"),
            ("non_functional_requirement", "NON-FUNCTIONAL REQUIREMENTS"),
            ("actor", "ACTORS"),
            ("domain_entity", "DOMAIN ENTITIES"),
            ("constraint", "CONSTRAINTS"),
            ("assumption", "ASSUMPTIONS"),
            ("integration", "INTEGRATIONS"),
        ):
            if not include(target_type):
                continue
            items = index.items(target_type)
            if not items:
                blocks.append(f"{title}\nNone recorded.")
                continue
            lines = [
                f"  {item.id}  {truncate(item.text, 150)}" for item in items[:25]
            ]
            if len(items) > 25:
                lines.append(f"  …and {len(items) - 25} more.")
            blocks.append(f"{title} ({len(items)})\n" + "\n".join(lines))
            evidence.extend(item.id for item in items[:6])

        if include("workflow") and requirements.domain_workflows:
            lines = [
                f"  {flow.name} — {truncate(flow.description, 110)} "
                f"(actor: {flow.primary_actor or 'unknown'})"
                for flow in requirements.domain_workflows[:8]
            ]
            blocks.append(
                f"WORKFLOWS ({len(requirements.domain_workflows)})\n" + "\n".join(lines)
            )

        if include("architecture"):
            components = [
                f"  {component.name} — {truncate(component.responsibility, 110)}"
                + (
                    f" [{', '.join(component.technologies[:4])}]"
                    if component.technologies
                    else ""
                )
                for component in architecture.components[:12]
            ]
            scorecard = next(
                (
                    card
                    for card in workspace.comparison.scorecards
                    if card.architecture_id == architecture.id
                ),
                None,
            )
            score = (
                f" Weighted score {scorecard.weighted_score:.1f}."
                if scorecard is not None
                else ""
            )
            blocks.append(
                f"ARCHITECTURE — {architecture.name} ({architecture.style}){score}\n"
                + truncate(architecture.overview, 240)
                + ("\n" + "\n".join(components) if components else "")
            )

        if include("api"):
            endpoints = [
                (group.name, endpoint)
                for group in workspace.api_design.groups
                for endpoint in group.endpoints
            ]
            if endpoints:
                lines = [
                    f"  {endpoint.method.upper()} {endpoint.path} — "
                    f"{truncate(endpoint.purpose, 90)}"
                    for _, endpoint in endpoints[:12]
                ]
                if len(endpoints) > 12:
                    lines.append(f"  …and {len(endpoints) - 12} more.")
                blocks.append(
                    f"API ({len(endpoints)} endpoints across "
                    f"{len(workspace.api_design.groups)} "
                    f"{plural(len(workspace.api_design.groups), 'group')}, "
                    f"{workspace.api_design.style})\n" + "\n".join(lines)
                )
            else:
                blocks.append("API\nNo endpoints recorded.")

        if include("database"):
            database = workspace.database_design
            if database.entities:
                lines = [
                    f"  {entity.name} — {len(entity.fields)} "
                    f"{plural(len(entity.fields), 'field')}"
                    for entity in database.entities[:12]
                ]
                blocks.append(
                    f"DATABASE — {database.database_engine} "
                    f"({len(database.entities)} "
                    f"{plural(len(database.entities), 'entity', 'entities')}, "
                    f"{len(database.relationships)} "
                    f"{plural(len(database.relationships), 'relationship')})\n"
                    + "\n".join(lines)
                )
            else:
                blocks.append("DATABASE\nNo entities recorded.")

        if include("deployment"):
            deployment = workspace.deployment_plan
            facts = [f"Model: {deployment.deployment_model}."]
            if getattr(deployment, "replicas", None):
                facts.append(f"Replicas: {deployment.replicas}.")
            if deployment.regions:
                facts.append(f"Regions: {', '.join(deployment.regions[:4])}.")
            if deployment.target_stack:
                facts.append(f"Stack: {', '.join(deployment.target_stack[:6])}.")
            blocks.append("DEPLOYMENT\n" + " ".join(facts))

        if include("traceability"):
            graph = workspace.causal_graph
            covered, uncovered = self.requirement_coverage(workspace, index)
            trace = [
                f"Causal graph: {len(graph.nodes)} nodes, {len(graph.edges)} links."
                if graph is not None
                else "Causal graph: not built yet.",
                f"Requirement coverage: {len(covered)} of {len(covered) + len(uncovered)} "
                "linked to an implementing artifact.",
            ]
            if uncovered:
                trace.append(
                    "Uncovered: " + ", ".join(item_id for item_id, _ in uncovered[:6]) + "."
                )
            if workspace.adrs:
                trace.append(f"Recorded decisions: {len(workspace.adrs)}.")
            blocks.append("TRACEABILITY\n" + "\n".join(trace))

        if include("unknowns"):
            unknowns: list[str] = []
            if workspace.consistency_issues:
                unknowns.extend(
                    f"  [issue] {issue.message}" for issue in workspace.consistency_issues[:4]
                )
            unknowns.extend(
                f"  [open question] {truncate(question, 140)}"
                for question in requirements.open_questions[:5]
            )
            blocks.append(
                "UNKNOWNS AND OPEN ITEMS\n"
                + ("\n".join(unknowns) if unknowns else "  Nothing outstanding.")
            )

        return AnalysisResult(
            answer="\n\n".join(blocks),
            evidence=evidence[:20],
            components=[component.name for component in architecture.components[:8]],
            confidence="high",
            follow_ups=[
                "find problems with my architecture",
                "what am I missing",
                "do these APIs cover all requirements",
            ],
        )

    # -------------------------------------------------------------- retrieval

    def search_project(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        index: ProjectIndex,
        query: str,
        *,
        limit: int = 8,
    ) -> list[tuple[float, str, str]]:
        """Rank everything in the project against a free-text query.

        Used as the last resort so an unrecognised question still gets a
        grounded answer built from what the project actually contains, rather
        than an apology.
        """
        # The question words carry no signal and drown the one or two words that
        # do: "explain the login function" must be scored on "login", or every
        # candidate containing "the" ranks equally and nothing stands out.
        query = strip_query_noise(query)
        query_tokens = tokens(query)
        if not query_tokens:
            return []

        candidates: list[tuple[str, str]] = []
        for target_type in (
            "functional_requirement",
            "non_functional_requirement",
            "constraint",
            "assumption",
            "integration",
            "actor",
            "domain_entity",
        ):
            for item in index.items(target_type):
                candidates.append((item.id, item.search_text))

        for component in architecture.components:
            candidates.append(
                (f"component:{component.name}", f"{component.name} {component.responsibility} "
                 f"{' '.join(component.technologies)}")
            )
        for group in workspace.api_design.groups:
            for endpoint in group.endpoints:
                candidates.append(
                    (
                        f"api:{endpoint.method.upper()} {endpoint.path}",
                        f"{endpoint.path} {endpoint.purpose} {group.name}",
                    )
                )
        for entity in workspace.database_design.entities:
            candidates.append((f"table:{entity.name}", f"{entity.name} {entity.description}"))
        for record in workspace.adrs:
            candidates.append((f"adr:{record.title}", f"{record.title} {record.decision}"))
        for screen in getattr(getattr(workspace, "prototype", None), "screens", None) or []:
            candidates.append((f"screen:{screen.name}", f"{screen.name} {screen.purpose}"))

        scored = [
            (containment(query, text) * 0.6 + similarity(query, text) * 0.4, label, text)
            for label, text in candidates
        ]
        ranked = sorted(
            (entry for entry in scored if entry[0] > 0.12),
            key=lambda entry: entry[0],
            reverse=True,
        )
        return ranked[:limit]

    # ------------------------------------------------------------ prototype

    def prototype_answer(
        self, workspace: WorkspaceResponse, index: ProjectIndex, reference: str
    ) -> AnalysisResult | None:
        screens = getattr(getattr(workspace, "prototype", None), "screens", None) or []
        if not screens:
            return None
        needle = clean_text(reference).casefold()
        screen = next(
            (item for item in screens if item.name.casefold() == needle), None
        ) or next(
            (item for item in screens if needle and needle in item.name.casefold()), None
        )
        if screen is None and needle:
            best, best_score = None, 0.0
            for item in screens:
                score = similarity(needle, f"{item.name} {item.purpose}")
                if score > best_score:
                    best, best_score = item, score
            screen = best if best_score >= 0.45 else None
        if screen is None:
            return None

        sources = screen.source_requirement_ids
        if sources:
            trace = f"It was generated from {', '.join(sources[:5])}."
            confidence = "high"
        else:
            trace = (
                "Unknown: no requirement is recorded as its source, so it is a "
                "prototype-only screen and should be validated against the requirement model."
            )
            confidence = "medium"
        return AnalysisResult(
            answer=(
                f"Confirmed: '{screen.name}' exists to {truncate(screen.purpose, 140)} "
                f"It uses the {screen.layout} layout. {trace}"
            ),
            evidence=list(sources[:6]),
            confidence=confidence,
        )
