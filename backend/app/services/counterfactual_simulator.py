import re
import uuid

from app.schemas.domain import (
    ArchitectureOption,
    ArchitectureScorecard,
    CounterfactualArchitectureRank,
    CounterfactualChange,
    CounterfactualSimulationRequest,
    CounterfactualSimulationResult,
    CounterfactualSnapshot,
    ProjectConstraints,
    RequirementAnalysis,
    RequirementModel,
    WorkspaceResponse,
)
from app.services.blast_radius_engine import simulate_failure
from app.services.budget_estimator import generate_budget
from app.services.causal_graph import COMPONENT_TYPES, CausalGraphService
from app.services.comparison_engine import ComparisonEngine
from app.services.conway_law_engine import check_fit


class CounterfactualSimulator:
    """Evaluate temporary requirement changes without mutating a workspace."""

    def __init__(self) -> None:
        self.comparison_engine = ComparisonEngine()
        self.graph_service = CausalGraphService()

    def simulate(
        self,
        workspace: WorkspaceResponse,
        payload: CounterfactualSimulationRequest,
    ) -> CounterfactualSimulationResult:
        changes = self._merge_changes(payload.changes, self._parse_scenario(payload.scenario or ""))
        baseline = self._baseline_values(workspace)
        changes = [
            change.model_copy(
                update={
                    "original_value": (
                        change.original_value
                        if change.original_value is not None
                        else baseline.get(change.variable)
                    )
                }
            )
            for change in changes
        ]

        current_architecture = self._current_architecture(workspace)
        temporary_requirements, temporary_answers = self._temporary_state(workspace, changes)
        after_comparison = self.comparison_engine.compare(
            temporary_requirements,
            workspace.architectures,
            temporary_answers,
        )

        change_text = self._change_text(changes, payload.scenario)
        direct_nodes, indirect_nodes = (
            self.graph_service.impacted_nodes_for_text(workspace.causal_graph, change_text)
            if workspace.causal_graph and change_text
            else ([], [])
        )
        affected_components = self._affected_components(
            current_architecture, direct_nodes, indirect_nodes, change_text
        )

        before_constraints, before_team_known = self._project_constraints(
            workspace, workspace.requirements, workspace.answers, changes, before=True
        )
        after_constraints, after_team_known = self._project_constraints(
            workspace, temporary_requirements, temporary_answers, changes, before=False
        )
        before_ranking = self._ranking(
            workspace.architectures,
            workspace.comparison.scorecards,
            workspace.requirements,
            before_constraints,
            before_team_known,
        )
        after_ranking = self._ranking(
            workspace.architectures,
            after_comparison.scorecards,
            temporary_requirements,
            after_constraints,
            after_team_known,
        )
        before = self._snapshot(
            workspace,
            current_architecture,
            workspace.comparison.scorecards,
            before_ranking,
            workspace.requirements,
            before_constraints,
            before_team_known,
            self._scale_tier(workspace.requirements, changes, before=True),
        )
        after = self._snapshot(
            workspace,
            current_architecture,
            after_comparison.scorecards,
            after_ranking,
            temporary_requirements,
            after_constraints,
            after_team_known,
            self._scale_tier(temporary_requirements, changes, before=False),
        )

        conflicts = self._conflicts(changes, after_ranking)
        still_suitable = (
            after.suitability_score >= 60
            and before.suitability_score - after.suitability_score <= 15
            and (after.team_fit_score is None or after.team_fit_score >= 5)
        )
        recommended = (
            current_architecture
            if still_suitable or conflicts
            else self._recommended_architecture(after_ranking, workspace.architectures)
        )
        evolution = self._evolution_path(changes, current_architecture, still_suitable, conflicts)
        unknown_originals = sum(change.original_value is None for change in changes)
        confidence = (
            "Low"
            if not changes or unknown_originals > len(changes) / 2
            else "High" if unknown_originals == 0 and direct_nodes else "Medium"
        )

        return CounterfactualSimulationResult(
            simulation_id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            current_architecture_version=workspace.causal_graph.version if workspace.causal_graph else "unknown",
            scenario=payload.scenario,
            changed_variables=changes,
            directly_affected_node_ids=[node.id for node in direct_nodes],
            indirectly_affected_node_ids=[node.id for node in indirect_nodes],
            affected_components=affected_components,
            before=before,
            after=after,
            before_ranking=before_ranking,
            after_ranking=after_ranking,
            current_architecture_still_suitable=still_suitable,
            recommended_architecture_id=recommended.id,
            recommended_architecture_name=recommended.name,
            recommended_evolution_path=evolution,
            conflicts=conflicts,
            explanation=self._explanation(changes, before, after, direct_nodes, indirect_nodes),
            confidence=confidence,
            estimate_notes=[
                "Suitability, risk, resilience, team fit, and ranking are deterministic planning scores, not measured production outcomes.",
                "Monthly costs reuse ArchAI's illustrative budget model and are estimates, not vendor quotes.",
                *(
                    ["Team size was not specified, so cost uses the existing five-person planning baseline; team-fit is left unknown."]
                    if not before_team_known and not after_team_known
                    else []
                ),
                "The simulation is isolated; no workspace requirement, architecture, ADR, or graph node was changed.",
            ],
        )

    def _parse_scenario(self, scenario: str) -> list[CounterfactualChange]:
        text = " ".join(scenario.split()).casefold()
        changes: list[CounterfactualChange] = []

        def add(variable: str, original, hypothetical) -> None:
            changes.append(CounterfactualChange(
                variable=variable,
                original_value=original,
                hypothetical_value=hypothetical,
                source="scenario",
            ))

        paired_patterns = (
            ("expected_users", r"(?:users?|user base)[^.!?]{0,40}?from\s+(\d[\d,.]*\s*(?:million|m|thousand|k)?)\s+to\s+(\d[\d,.]*\s*(?:million|m|thousand|k)?)"),
            ("availability_percent", r"availability[^.!?]{0,25}?from\s+([\d.]+)%?\s+to\s+([\d.]+)%?"),
            ("latency_ms", r"latency[^.!?]{0,25}?from\s+([\d,.]+)\s*ms\s+to\s+([\d,.]+)\s*ms"),
            ("team_size", r"team(?: size)?[^.!?]{0,25}?from\s+(\d+)\s+to\s+(\d+)"),
        )
        for variable, pattern in paired_patterns:
            if match := re.search(pattern, text):
                parser = (
                    self._parse_count
                    if variable == "expected_users"
                    else self._parse_float
                    if variable == "availability_percent"
                    else self._parse_number
                )
                add(variable, parser(match.group(1)), parser(match.group(2)))

        if match := re.search(r"(?:traffic|requests?)[^.!?]{0,25}?(\d+(?:\.\d+)?)\s*x", text):
            add("peak_traffic_multiplier", 1, float(match.group(1)))
        if match := re.search(r"data volume[^.!?]{0,25}?(\d+(?:\.\d+)?)\s*x", text):
            add("data_volume_multiplier", 1, float(match.group(1)))
        elif "data volume" in text and any(word in text for word in ("increase", "grow", "significant")):
            add("data_volume_multiplier", None, "significant increase")
        if match := re.search(r"budget[^.!?]{0,20}?(decrease|reduce|increase)[^\d]{0,10}(\d+(?:\.\d+)?)%", text):
            amount = float(match.group(2))
            add("monthly_budget_change_percent", 0, -amount if match.group(1) != "increase" else amount)
        if "multiple region" in text or "multi-region" in text:
            add("geographic_regions", 1 if "one region" in text else None, "multiple")
        if ("realtime" in text or "real-time" in text) and any(word in text for word in ("need", "require", "become")):
            add("realtime_required", False, True)
        if "compliance" in text or "security constraint" in text:
            level = "regulated" if "regulat" in text else "high"
            add("compliance_level", None, level)
        return changes

    def _merge_changes(
        self,
        structured: list[CounterfactualChange],
        parsed: list[CounterfactualChange],
    ) -> list[CounterfactualChange]:
        by_variable = {change.variable: change for change in parsed}
        for change in structured:
            by_variable[change.variable] = change
        return list(by_variable.values())

    def _baseline_values(self, workspace: WorkspaceResponse) -> dict[str, object | None]:
        text = " ".join([
            workspace.original_prompt,
            *workspace.requirements.non_functional_requirements,
            *workspace.requirements.constraints,
        ])
        users = self._first_number(text, r"(\d[\d,.]*\s*(?:million|m|thousand|k)?)\s+users?")
        availability_match = re.search(r"([\d.]+)%\s+availability", text, flags=re.IGNORECASE)
        availability = self._parse_float(availability_match.group(1)) if availability_match else None
        latency_match = re.search(r"(\d+)\s*ms", text, flags=re.IGNORECASE)
        latency = self._parse_number(latency_match.group(1)) if latency_match else None
        team = self._parse_number(workspace.answers.get("team_size", ""))
        return {
            "expected_users": users,
            "availability_percent": availability,
            "latency_ms": latency,
            "budget_level": workspace.answers.get("budget"),
            "team_size": team or None,
            "realtime_required": any(marker in text.casefold() for marker in ("realtime", "real-time")),
            "geographic_regions": None,
            "peak_traffic_multiplier": 1,
            "monthly_budget_change_percent": 0,
            "compliance_level": None,
            "data_volume_multiplier": 1,
            "growth_rate_percent": None,
        }

    def _temporary_state(
        self, workspace: WorkspaceResponse, changes: list[CounterfactualChange]
    ) -> tuple[RequirementModel, dict[str, str]]:
        requirements = workspace.requirements.model_copy(deep=True)
        answers = dict(workspace.answers)
        for change in changes:
            value = change.hypothetical_value
            if change.variable == "expected_users" and isinstance(value, (int, float)):
                requirements.scale_profile = self._profile_for_users(float(value))
                requirements.non_functional_requirements.append(f"Plan capacity for {int(value):,} expected users.")
            elif change.variable in {"peak_traffic_multiplier", "data_volume_multiplier"}:
                multiplier = float(value) if isinstance(value, (int, float)) else None
                if multiplier is None or multiplier >= 3:
                    requirements.scale_profile = "high-scale"
                requirements.non_functional_requirements.append(
                    f"Hypothetical {change.variable.replace('_', ' ')}: {value}."
                )
            elif change.variable == "availability_percent":
                requirements.non_functional_requirements.append(f"Availability target: {value}%.")
            elif change.variable == "latency_ms":
                requirements.non_functional_requirements.append(f"Latency target: {value} ms.")
            elif change.variable == "budget_level":
                answers["budget"] = str(value)
            elif change.variable == "monthly_budget_change_percent":
                if isinstance(value, (int, float)) and value < 0:
                    answers["budget"] = "low"
            elif change.variable == "team_size":
                answers["team_size"] = str(value)
            elif change.variable == "geographic_regions":
                answers["geographic_regions"] = "2" if str(value).casefold() == "multiple" else str(value)
                requirements.non_functional_requirements.append(f"Deployment regions: {value}.")
            elif change.variable == "realtime_required" and bool(value):
                requirements.non_functional_requirements.append("Real-time processing is required.")
            elif change.variable == "compliance_level":
                requirements.constraints.append(f"Hypothetical compliance level: {value}.")
            elif change.variable == "growth_rate_percent":
                requirements.non_functional_requirements.append(f"Expected growth rate: {value}%.")
        requirements.non_functional_requirements = list(dict.fromkeys(requirements.non_functional_requirements))
        requirements.constraints = list(dict.fromkeys(requirements.constraints))
        return requirements, answers

    def _project_constraints(
        self,
        workspace: WorkspaceResponse,
        requirements: RequirementModel,
        answers: dict[str, str],
        changes: list[CounterfactualChange],
        *,
        before: bool,
    ) -> tuple[ProjectConstraints, bool]:
        team = self._parse_number(answers.get("team_size", ""))
        team_change = next((item for item in changes if item.variable == "team_size"), None)
        if team_change:
            selected = team_change.original_value if before else team_change.hypothetical_value
            team = self._parse_number(str(selected))
        team_known = bool(team)
        budget = answers.get("budget", "medium").casefold()
        if budget not in {"low", "medium", "high"}:
            budget = "medium"
        return ProjectConstraints(
            team_size=team or 5,
            budget_level=budget,
            expected_scale=requirements.scale_profile,
            timeline_weeks=max(1, self._parse_number(answers.get("timeline_weeks", "12")) or 12),
        ), team_known

    def _ranking(
        self,
        architectures: list[ArchitectureOption],
        scorecards: list[ArchitectureScorecard],
        requirements: RequirementModel,
        constraints: ProjectConstraints,
        team_known: bool,
    ) -> list[CounterfactualArchitectureRank]:
        architecture_by_id = {item.id: item for item in architectures}
        entries: list[tuple[float, ArchitectureScorecard, float | None]] = []
        for scorecard in scorecards:
            architecture = architecture_by_id[scorecard.architecture_id]
            team_fit = self._team_fit(architecture, requirements, constraints) if team_known else None
            combined = scorecard.weighted_score if team_fit is None else scorecard.weighted_score * 0.8 + team_fit * 10 * 0.2
            entries.append((combined, scorecard, team_fit))
        entries.sort(key=lambda item: item[0], reverse=True)
        return [
            CounterfactualArchitectureRank(
                architecture_id=scorecard.architecture_id,
                architecture_name=scorecard.architecture_name,
                rank=index,
                suitability_score=round(scorecard.weighted_score, 1),
                team_fit_score=team_fit,
            )
            for index, (_, scorecard, team_fit) in enumerate(entries, 1)
        ]

    def _snapshot(
        self,
        workspace: WorkspaceResponse,
        architecture: ArchitectureOption,
        scorecards: list[ArchitectureScorecard],
        ranking: list[CounterfactualArchitectureRank],
        requirements: RequirementModel,
        constraints: ProjectConstraints,
        team_known: bool,
        scale_tier: int,
    ) -> CounterfactualSnapshot:
        scorecard = next(item for item in scorecards if item.architecture_id == architecture.id)
        rank = next(item.rank for item in ranking if item.architecture_id == architecture.id)
        metrics = {item.metric: item.score for item in scorecard.metric_scores}
        resilience = round(sum(metrics.get(item, 5) for item in ("reliability", "availability", "fault_isolation")) / 3, 1)
        matrix = {
            item.architecture_id: {metric.metric: metric.score for metric in item.metric_scores}
            for item in scorecards
        }
        severities = [
            simulate_failure(architecture, component.name, matrix).severity_score
            for component in architecture.components
        ]
        risk_score = round(max(severities, default=10 - resilience), 1)
        cost = generate_budget(architecture, self._deployment_stack(workspace), constraints)
        monthly = cost.budgets_by_scale[scale_tier].total_monthly_usd
        team_fit = self._team_fit(architecture, requirements, constraints) if team_known else None
        return CounterfactualSnapshot(
            architecture_id=architecture.id,
            architecture_name=architecture.name,
            suitability_score=round(scorecard.weighted_score, 1),
            rank=rank,
            monthly_cost_estimate_usd=monthly,
            resilience_score=resilience,
            risk_score=risk_score,
            risk_level="High" if risk_score >= 7 else "Medium" if risk_score >= 4 else "Low",
            team_fit_score=team_fit,
            operational_complexity_score=round(11 - metrics.get("operational_complexity", 5), 1),
        )

    def _team_fit(self, architecture, requirements, constraints) -> float:
        entities = [item.name for item in requirements.domain_entities]
        return check_fit(architecture, RequirementAnalysis(detected_entities=entities), constraints).fit_score

    def _scale_tier(self, requirements, changes, *, before: bool) -> int:
        user_change = next((item for item in changes if item.variable == "expected_users"), None)
        value = user_change.original_value if user_change and before else user_change.hypothetical_value if user_change else None
        if isinstance(value, (int, float)):
            return 0 if value <= 10_000 else 1 if value <= 250_000 else 2
        return 2 if requirements.scale_profile == "high-scale" else 0 if requirements.scale_profile == "startup-scale" else 1

    def _affected_components(self, architecture, direct, indirect, text) -> list[str]:
        graph_components = [
            node.name
            for node in [*direct, *indirect]
            if node.type in COMPONENT_TYPES
            and node.metadata.get("architecture_id") == architecture.id
        ]
        if graph_components:
            return list(dict.fromkeys(graph_components))
        tokens = text.casefold()
        matches = [
            component.name
            for component in architecture.components
            if any(token in f"{component.name} {component.responsibility}".casefold() for token in re.findall(r"[a-z]{4,}", tokens))
        ]
        return matches

    def _conflicts(self, changes, ranking) -> list[str]:
        values = {item.variable: item.hypothetical_value for item in changes}
        small_team = isinstance(values.get("team_size"), (int, float)) and values["team_size"] <= 6
        constrained = values.get("budget_level") == "low" or (
            isinstance(values.get("monthly_budget_change_percent"), (int, float))
            and values["monthly_budget_change_percent"] < 0
        )
        scale_pressure = (
            isinstance(values.get("expected_users"), (int, float)) and values["expected_users"] >= 250_000
        ) or values.get("realtime_required") is True or (
            isinstance(values.get("peak_traffic_multiplier"), (int, float)) and values["peak_traffic_multiplier"] >= 3
        )
        conflicts = []
        if scale_pressure and small_team:
            conflicts.append("Scale pressure favors stronger isolation, but the smaller team reduces the fit of independently operated services.")
        if scale_pressure and constrained:
            conflicts.append("Scale pressure raises infrastructure needs while the tighter budget favors incremental changes and measured hotspots.")
        distributed_ids = {"event-driven-microservices", "hybrid-event-serverless", "service-based"}
        for distributed_id in distributed_ids:
            micro = next((item for item in ranking if item.architecture_id == distributed_id), None)
            if micro and micro.team_fit_score is not None and micro.team_fit_score < 5:
                conflicts.append(f"{micro.architecture_name} technical suitability is offset by insufficient team ownership capacity.")
                break
        return list(dict.fromkeys(conflicts))

    def _evolution_path(self, changes, architecture, still_suitable, conflicts) -> list[str]:
        values = {item.variable: item.hypothetical_value for item in changes}
        steps: list[str] = []
        scale_pressure = any(
            isinstance(values.get(key), (int, float)) and values[key] >= threshold
            for key, threshold in (("expected_users", 250_000), ("peak_traffic_multiplier", 3), ("data_volume_multiplier", 3))
        ) or values.get("data_volume_multiplier") == "significant increase"
        if scale_pressure:
            steps.extend([
                "Measure load by component and add caching only to verified read hotspots.",
                "Scale the system of record with indexes, connection controls, and read replicas before changing topology.",
            ])
        if values.get("realtime_required") is True or (
            isinstance(values.get("peak_traffic_multiplier"), (int, float)) and values["peak_traffic_multiplier"] >= 3
        ):
            steps.append("Introduce a durable queue or event stream for asynchronous work that is proven to leave request-path limits.")
        if isinstance(values.get("availability_percent"), (int, float)) and values["availability_percent"] >= 99.99:
            steps.append("Add redundant application instances, database failover, health checks, and tested recovery procedures.")
        if isinstance(values.get("latency_ms"), (int, float)) and values["latency_ms"] <= 100:
            steps.append("Profile critical paths, set latency budgets, and cache only measurements that show a bottleneck.")
        if str(values.get("geographic_regions", "")).casefold() == "multiple" or (
            isinstance(values.get("geographic_regions"), (int, float)) and values["geographic_regions"] > 1
        ):
            steps.append("Introduce region-aware routing and an explicit data-consistency and residency strategy before active-active writes.")
        if values.get("compliance_level"):
            steps.append("Add threat modeling, access-control evidence, encryption boundaries, and auditable policy checks for the new constraint.")
        if conflicts:
            steps.append("Keep one primary deployable unit and extract only a measured high-load boundary after ownership capacity exists.")
        elif scale_pressure and architecture.id in {"modular-monolith", "service-based", "hybrid-modular-serverless"} and not still_suitable:
            steps.append("Extract only the highest-load module if independent scaling remains necessary after the preceding changes.")
        if not steps:
            steps.append("No architecture evolution is justified by the recognized hypothetical changes.")
        return list(dict.fromkeys(steps))

    def _explanation(self, changes, before, after, direct, indirect) -> list[str]:
        if not changes:
            return ["No supported counterfactual variable changed, so the current scores remain unchanged."]
        return [
            f"The current architecture suitability changed from {before.suitability_score:.1f} to {after.suitability_score:.1f} using the existing deterministic scoring engine.",
            f"Causal traversal found {len(direct)} direct and {len(indirect)} indirect existing graph nodes related to the hypothetical state.",
            f"Resilience changed from {before.resilience_score:.1f} to {after.resilience_score:.1f}; risk is derived from the existing component failure simulation.",
            "Only the temporary requirement and constraint copy was scored; the saved workspace remains unchanged.",
        ]

    def _recommended_architecture(self, ranking, architectures):
        winner = ranking[0]
        return next(item for item in architectures if item.id == winner.architecture_id)

    def _current_architecture(self, workspace):
        return next(
            item for item in workspace.architectures
            if item.id == workspace.recommendation.recommended_architecture_id
        )

    def _deployment_stack(self, workspace):
        return list(dict.fromkeys([
            *workspace.deployment_plan.target_stack,
            *workspace.deployment_plan.docker_services,
            *workspace.deployment_plan.kubernetes_modules,
        ]))

    def _change_text(self, changes, scenario):
        parts = [scenario or ""]
        technical_context = {
            "expected_users": "scalability traffic workload growth capacity",
            "peak_traffic_multiplier": "scalability traffic throughput capacity",
            "availability_percent": "availability resilience recovery failover redundancy",
            "latency_ms": "latency performance response time",
            "budget_level": "cost budget operational complexity",
            "monthly_budget_change_percent": "cost budget operational complexity",
            "team_size": "team ownership operational complexity",
            "geographic_regions": "region deployment availability data residency",
            "realtime_required": "realtime event processing asynchronous stream",
            "compliance_level": "compliance security audit governance",
            "data_volume_multiplier": "data volume storage scalability throughput",
            "growth_rate_percent": "growth scalability capacity",
        }
        parts.extend(
            f"{item.variable} {item.original_value} to {item.hypothetical_value} {technical_context[item.variable]}"
            for item in changes
        )
        return " ".join(parts).strip()

    def _profile_for_users(self, users: float) -> str:
        return "high-scale" if users >= 250_000 else "growth-scale" if users >= 25_000 else "startup-scale"

    def _first_number(self, text: str, pattern: str):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        return self._parse_count(match.group(1)) if match else None

    def _parse_count(self, value: str):
        match = re.search(r"(\d[\d,.]*)\s*(million|m|thousand|k)?", str(value).casefold())
        if not match:
            return None
        number = float(match.group(1).replace(",", ""))
        if match.group(2) in {"million", "m"}:
            number *= 1_000_000
        elif match.group(2) in {"thousand", "k"}:
            number *= 1_000
        return int(number)

    def _parse_number(self, value: str):
        match = re.search(r"-?\d[\d,.]*", str(value))
        return int(float(match.group().replace(",", ""))) if match else 0

    def _parse_float(self, value: str):
        match = re.search(r"-?\d[\d,.]*", str(value))
        return float(match.group().replace(",", "")) if match else 0.0
