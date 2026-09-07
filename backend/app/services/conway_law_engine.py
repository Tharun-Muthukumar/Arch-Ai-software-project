"""Deterministic Conway's Law fit analysis with architecture-specific roles.

Design rationale:
  Conway's Law says that system structure mirrors communication structure.
  This module first produces an auditable staffing plan for the architecture,
  then tests its component and service boundaries against those recommended
  roles. No LLM is involved: role allocation, ownership, and friction all use
  fixed catalog entries and capacity-ratio rules.
"""

from collections import Counter

from app.schemas.domain import (
    ArchitectureOption,
    ConwayFitResult,
    FrictionPoint,
    OwnershipSuggestion,
    ProjectConstraints,
    RequirementAnalysis,
    RoleDefinition,
    RoleRecommendation,
    TeamDefinition,
    TeamFitPlan,
)

_SHARED_UNIT_ARCHITECTURES = {"modular-monolith", "monolithic", "layered", "clean"}
_SERVICE_ARCHITECTURES = {
    "event-driven-microservices", "microservices", "event-driven", "event_driven",
    "serverless-platform", "serverless",
    "service-based", "service_based",
    "hybrid-event-serverless",
}
_HYBRID_MODULAR_ARCHITECTURES = {"hybrid-modular-serverless"}
_PENALTIES = {"high": 3.0, "medium": 1.5, "low": 0.5}

ROLE_CATALOG: dict[str, list[RoleDefinition]] = {
    "modular-monolith": [
        RoleDefinition(
            role_name="Backend Engineers",
            description="Own the shared application modules, API contracts, domain logic, and release-ready integration inside one deployable unit.",
            suggested_percentage=0.45,
            min_headcount=1,
            essential=True,
        ),
        RoleDefinition(
            role_name="Frontend Engineers",
            description="Own the web client, its integration with the shared API, and cohesive end-to-end user flows.",
            suggested_percentage=0.25,
            min_headcount=1,
            essential=True,
        ),
        RoleDefinition(
            role_name="QA/Testing",
            description="Protect shared-release quality with integration and regression coverage across the single application boundary.",
            suggested_percentage=0.20,
            min_headcount=1,
            essential=True,
        ),
        RoleDefinition(
            role_name="DevOps (part-time/shared)",
            description="Maintains the container pipeline, environments, backups, and production monitoring without a dedicated platform layer.",
            suggested_percentage=0.10,
            min_headcount=0,
            essential=False,
        ),
    ],
    "event-driven-microservices": [
        RoleDefinition(
            role_name="Backend/Service Owners",
            description="Own bounded-context services, service APIs, event contracts, and the reliability of each independently deployed workload.",
            suggested_percentage=0.35,
            min_headcount=1,
            essential=True,
        ),
        RoleDefinition(
            role_name="Platform & DevOps",
            description="Owns the Kubernetes cluster, service mesh, CI/CD pipelines per service, and cross-service observability; without this role independent service deployment breaks down.",
            suggested_percentage=0.25,
            min_headcount=1,
            essential=True,
        ),
        RoleDefinition(
            role_name="Frontend Engineers",
            description="Own the client application and gateway-facing user journeys while coordinating contracts across backend services.",
            suggested_percentage=0.15,
            min_headcount=1,
            essential=True,
        ),
        RoleDefinition(
            role_name="Data/Database Engineers",
            description="Design service-owned data stores, event retention, migrations, and data consistency boundaries between services.",
            suggested_percentage=0.10,
            min_headcount=0,
            essential=False,
        ),
        RoleDefinition(
            role_name="QA/Testing",
            description="Own contract, integration, and end-to-end tests that catch failures across asynchronous service and event boundaries.",
            suggested_percentage=0.15,
            min_headcount=1,
            essential=True,
        ),
    ],
    "serverless-platform": [
        RoleDefinition(
            role_name="Backend/Functions Engineers",
            description="Own small function boundaries, managed workflow handlers, API contracts, and safe retries for event-triggered work.",
            suggested_percentage=0.40,
            min_headcount=1,
            essential=True,
        ),
        RoleDefinition(
            role_name="Frontend Engineers",
            description="Own the static web application, CDN-delivered experience, and API integration with managed endpoints.",
            suggested_percentage=0.25,
            min_headcount=1,
            essential=True,
        ),
        RoleDefinition(
            role_name="Cloud/Infrastructure Engineer",
            description="Configures managed identity, gateways, data services, permissions, cost controls, and production observability.",
            suggested_percentage=0.20,
            min_headcount=1,
            essential=True,
        ),
        RoleDefinition(
            role_name="QA/Testing",
            description="Tests function workflows, cloud integration paths, and production-like failure handling across managed services.",
            suggested_percentage=0.15,
            min_headcount=1,
            essential=True,
        ),
    ],
    "service-based": [
        RoleDefinition(
            role_name="Backend/Service Owners",
            description="Own the small set of coarse services, their versioned APIs, and the consistency rules inside each service boundary.",
            suggested_percentage=0.40,
            min_headcount=1,
            essential=True,
        ),
        RoleDefinition(
            role_name="Frontend Engineers",
            description="Own the client application and its integration with the coarse service APIs.",
            suggested_percentage=0.20,
            min_headcount=1,
            essential=True,
        ),
        RoleDefinition(
            role_name="QA/Testing",
            description="Own service-level contract tests plus end-to-end coverage across the coarse service boundaries.",
            suggested_percentage=0.20,
            min_headcount=1,
            essential=True,
        ),
        RoleDefinition(
            role_name="DevOps (part-time/shared)",
            description="Maintains container pipelines, environments, and observability for a handful of deployables without a full platform team.",
            suggested_percentage=0.20,
            min_headcount=0,
            essential=False,
        ),
    ],
    "hybrid-modular-serverless": [
        RoleDefinition(
            role_name="Backend Core Engineers",
            description="Own the cohesive transactional core, its modules, API contracts, and release-ready integration.",
            suggested_percentage=0.35,
            min_headcount=1,
            essential=True,
        ),
        RoleDefinition(
            role_name="Frontend Engineers",
            description="Own the client experience and its integration with core APIs and edge-triggered flows.",
            suggested_percentage=0.20,
            min_headcount=1,
            essential=True,
        ),
        RoleDefinition(
            role_name="Serverless/Edge Engineers",
            description="Own the bursty or asynchronous edge handlers, idempotent writes, retries, and function observability.",
            suggested_percentage=0.20,
            min_headcount=0,
            essential=False,
        ),
        RoleDefinition(
            role_name="QA/Testing",
            description="Covers core regression plus core-edge contract and failure-handling tests across two compute models.",
            suggested_percentage=0.15,
            min_headcount=1,
            essential=True,
        ),
        RoleDefinition(
            role_name="Cloud/Infrastructure (shared)",
            description="Configures core hosting, managed functions, queues, identity, and shared production monitoring.",
            suggested_percentage=0.10,
            min_headcount=0,
            essential=False,
        ),
    ],
    "hybrid-event-serverless": [
        RoleDefinition(
            role_name="Backend/Service Owners",
            description="Own the stable coarse services, their APIs, and the versioned events they publish.",
            suggested_percentage=0.30,
            min_headcount=1,
            essential=True,
        ),
        RoleDefinition(
            role_name="Platform & DevOps",
            description="Owns the event backbone, container hosting, per-service pipelines, and cross-boundary observability.",
            suggested_percentage=0.20,
            min_headcount=1,
            essential=True,
        ),
        RoleDefinition(
            role_name="Frontend Engineers",
            description="Own the client application and gateway-facing journeys across services and managed endpoints.",
            suggested_percentage=0.15,
            min_headcount=1,
            essential=True,
        ),
        RoleDefinition(
            role_name="Serverless Consumers",
            description="Own the elastic event consumers, idempotent handlers, retry budgets, and consumer projections.",
            suggested_percentage=0.15,
            min_headcount=0,
            essential=False,
        ),
        RoleDefinition(
            role_name="QA/Testing",
            description="Own contract, event-compatibility, and end-to-end tests across services and serverless consumers.",
            suggested_percentage=0.20,
            min_headcount=1,
            essential=True,
        ),
    ],
}

_ROLE_CATALOG_ALIASES = {
    "monolithic": "modular-monolith",
    "layered": "modular-monolith",
    "clean": "modular-monolith",
    "microservices": "event-driven-microservices",
    "event-driven": "event-driven-microservices",
    "event_driven": "event-driven-microservices",
    "serverless": "serverless-platform",
    "service_based": "service-based",
}


def _catalog_for(architecture_id: str) -> list[RoleDefinition]:
    """Resolve implementation aliases to one architecture-specific role catalog."""
    resolved = _ROLE_CATALOG_ALIASES.get(architecture_id, architecture_id)
    return ROLE_CATALOG.get(resolved, ROLE_CATALOG["service-based"])


def _allocate_headcounts(roles: list[RoleDefinition], team_size: int) -> list[int]:
    """Allocate seats with minimums, then largest-remainder reconciliation."""
    minimum_total = sum(role.min_headcount for role in roles)
    if team_size < minimum_total:
        allocation = [0] * len(roles)
        ranked = sorted(
            enumerate(roles),
            key=lambda item: (not item[1].essential, -item[1].suggested_percentage, item[0]),
        )
        for index, _ in ranked[:team_size]:
            allocation[index] = 1
        return allocation

    quotas = [role.suggested_percentage * team_size for role in roles]
    allocation = [max(role.min_headcount, int(quota)) for role, quota in zip(roles, quotas, strict=True)]

    while sum(allocation) > team_size:
        candidates = [
            index for index, role in enumerate(roles)
            if allocation[index] > role.min_headcount
        ]
        index = max(candidates, key=lambda candidate: (allocation[candidate] - quotas[candidate], candidate))
        allocation[index] -= 1

    remainders = [quota - int(quota) for quota in quotas]
    while sum(allocation) < team_size:
        index = max(
            range(len(roles)),
            key=lambda candidate: (remainders[candidate], roles[candidate].suggested_percentage, -candidate),
        )
        allocation[index] += 1
        remainders[index] = -1.0
    return allocation


def suggest_roles(architecture: ArchitectureOption, constraints: ProjectConstraints) -> TeamFitPlan:
    """Produce a deterministic architecture-specific staffing recommendation."""
    catalog = _catalog_for(architecture.id)
    headcounts = _allocate_headcounts(catalog, constraints.team_size)
    minimum_total = sum(role.min_headcount for role in catalog)
    roles = [
        RoleRecommendation(
            role_name=role.role_name,
            description=role.description,
            recommended_headcount=headcount,
            rationale=(
                f"{headcount} of {constraints.team_size} people recommended for {role.role_name} "
                f"from its {role.suggested_percentage:.0%} architecture staffing share."
            ),
        )
        for role, headcount in zip(catalog, headcounts, strict=True)
    ]
    coverage_warning = None
    if constraints.team_size < minimum_total:
        uncovered = [role.role_name for role, headcount in zip(catalog, headcounts, strict=True) if headcount == 0]
        coverage_warning = (
            f"team_size {constraints.team_size} is tight for {architecture.name}; consider merging "
            f"{', '.join(uncovered)} into the nearest delivery role until the team grows."
        )
    return TeamFitPlan(
        architecture_id=architecture.id,
        total_team_size=constraints.team_size,
        roles=roles,
        coverage_warning=coverage_warning,
    )


def _ownership_units(architecture: ArchitectureOption, entities: list[str]) -> list[str]:
    """Return the units that can receive independent role ownership."""
    if architecture.id in _SHARED_UNIT_ARCHITECTURES:
        return ["Application tier"]
    if architecture.id in _HYBRID_MODULAR_ARCHITECTURES:
        return ["Application core", "Serverless edge handlers"]
    if architecture.id in _SERVICE_ARCHITECTURES:
        return entities or [component.name for component in architecture.components] or ["Application service"]
    return entities or [component.name for component in architecture.components] or ["Application tier"]


def _active_role_teams(plan: TeamFitPlan) -> list[TeamDefinition]:
    """Convert staffed role recommendations to the capacity shape used by rules."""
    return [
        TeamDefinition(name=role.role_name, member_count=role.recommended_headcount)
        for role in plan.roles
        if role.recommended_headcount > 0
    ]


def suggest_ownership(
    architecture: ArchitectureOption,
    entities: list[str],
    team_fit_plan: TeamFitPlan,
) -> list[OwnershipSuggestion]:
    """Allocate ownership greedily across staffed recommended roles."""
    units = _ownership_units(architecture, entities)
    teams = _active_role_teams(team_fit_plan)
    assigned_counts = {team.name: 0 for team in teams}
    suggestions: list[OwnershipSuggestion] = []
    for unit in units:
        team = min(
            teams,
            key=lambda candidate: (assigned_counts[candidate.name] / candidate.member_count, candidate.name),
        )
        assigned_counts[team.name] += 1
        suggestions.append(OwnershipSuggestion(
            component=unit,
            suggested_team=team.name,
            reason=f"Assigned by capacity: {team.name} has the lowest current ownership load per person.",
        ))
    return suggestions


def detect_friction(
    architecture: ArchitectureOption,
    entities: list[str],
    team_fit_plan: TeamFitPlan,
    ownership: list[OwnershipSuggestion],
) -> list[FrictionPoint]:
    """Apply fixed Conway's Law mismatch rules to staffed recommended roles.

    Conway's Law maps communication structure to system structure: a single
    deployable fits a small collocated team, while independently operated
    services need enough staffed ownership capacity per boundary.
    """
    units = _ownership_units(architecture, entities)
    teams = _active_role_teams(team_fit_plan)
    team_names = [team.name for team in teams]
    team_size = team_fit_plan.total_team_size
    points: list[FrictionPoint] = []
    distributed_ids = {
        "event-driven-microservices", "microservices", "event-driven", "event_driven",
        "service-based", "service_based", "hybrid-event-serverless",
        "serverless-platform", "serverless",
    }
    if architecture.id in _SHARED_UNIT_ARCHITECTURES:
        if team_size >= 13 or len(teams) >= 5:
            points.append(FrictionPoint(
                description=f"{team_size} people across {len(teams)} roles share one deployable unit; expect merge, release, and ownership contention (Conway mismatch for large teams).",
                severity="high",
                affected_components=units,
                affected_teams=team_names,
            ))
        elif team_size >= 7:
            points.append(FrictionPoint(
                description=f"{team_size} people across {len(teams)} roles share one deployable unit; coordination cost will grow as parallel work increases.",
                severity="medium",
                affected_components=units,
                affected_teams=team_names,
            ))
    if architecture.id in _HYBRID_MODULAR_ARCHITECTURES:
        if team_size <= 2:
            points.append(FrictionPoint(
                description=f"Only {team_size} people must cover both the application core and serverless edge handlers; edge work will compete with core delivery.",
                severity="medium",
                affected_components=units,
                affected_teams=team_names,
            ))
        if team_size >= 13:
            points.append(FrictionPoint(
                description=f"{team_size} people on a hybrid core-plus-edge shape may outgrow the single core; plan which bounded context splits next.",
                severity="low",
                affected_components=units,
                affected_teams=team_names,
            ))
    if architecture.id in distributed_ids:
        if team_size <= 6 and architecture.id in {"event-driven-microservices", "microservices", "event-driven", "event_driven", "hybrid-event-serverless"}:
            points.append(FrictionPoint(
                description=f"Only {team_size} people must operate {len(units)} distributed boundaries plus platform/eventing work; ownership capacity is insufficient for independently deployed services.",
                severity="high",
                affected_components=units,
                affected_teams=team_names,
            ))
        elif team_size <= 6:
            points.append(FrictionPoint(
                description=f"A {team_size}-person team will stretch to cover {len(units)} service boundaries plus delivery and QA; keep service count small.",
                severity="medium",
                affected_components=units,
                affected_teams=team_names,
            ))
        if len(units) < len(teams):
            owners = {item.suggested_team for item in ownership}
            shared_roles = [team.name for team in teams if team.name not in owners]
            points.append(FrictionPoint(
                description=(
                    f"Only {len(units)} service boundary/boundaries exist for {len(teams)} staffed roles; "
                    f"{', '.join(shared_roles or team_names)} will be idle or forced to co-own services."
                ),
                severity="medium",
                affected_components=units,
                affected_teams=shared_roles or team_names,
            ))
    ownership_counts = Counter(item.suggested_team for item in ownership)
    for team in teams:
        if team.member_count < 2 and ownership_counts[team.name] > 2:
            owned = [item.component for item in ownership if item.suggested_team == team.name]
            points.append(FrictionPoint(
                description=f"{team.name} has {team.member_count} person but owns {len(owned)} services; this creates a bottleneck and bus-factor risk.",
                severity="medium",
                affected_components=owned,
                affected_teams=[team.name],
            ))
    if len(units) > len(teams) * 3:
        points.append(FrictionPoint(
            description=f"{len(units)} service boundaries for {len(teams)} staffed roles are over-decomposed relative to maintenance capacity; merge boundaries or grow ownership.",
            severity="medium",
            affected_components=units,
            affected_teams=team_names,
        ))
    if not points:
        points.append(FrictionPoint(
            description="Ownership boundaries look well-matched to the recommended role structure.",
            severity="low",
            affected_components=units,
            affected_teams=team_names,
        ))
    return points


def compute_fit_score(
    architecture: ArchitectureOption,
    entities: list[str],
    team_fit_plan: TeamFitPlan,
    friction_points: list[FrictionPoint],
) -> float:
    """Score fit from 10 down using fixed penalties for each friction point."""
    del architecture, entities, team_fit_plan
    return round(max(0.0, 10.0 - sum(_PENALTIES[point.severity] for point in friction_points)), 1)


def check_fit(
    architecture: ArchitectureOption,
    analysis: RequirementAnalysis,
    constraints: ProjectConstraints,
) -> ConwayFitResult:
    """Build a role plan, map ownership, identify friction, and summarize fit."""
    team_fit_plan = suggest_roles(architecture, constraints)
    ownership = suggest_ownership(architecture, analysis.detected_entities, team_fit_plan)
    friction_points = detect_friction(architecture, analysis.detected_entities, team_fit_plan, ownership)
    fit_score = compute_fit_score(architecture, analysis.detected_entities, team_fit_plan, friction_points)
    staffed_roles = len([role for role in team_fit_plan.roles if role.recommended_headcount > 0])
    unit_count = len(_ownership_units(architecture, analysis.detected_entities))
    return ConwayFitResult(
        fit_score=fit_score,
        team_fit_plan=team_fit_plan,
        ownership_mapping=ownership,
        friction_points=friction_points,
        summary=(
            f"Conway fit is {fit_score}/10 for a {constraints.team_size}-person team on {architecture.name}: "
            f"{staffed_roles} staffed roles map to {unit_count} ownership units. {friction_points[0].description}"
        ),
    )
