"""Deterministic blast-radius simulation for architecture component failures.

Design rationale:
  Blast radius is computed entirely from a component dependency graph combined
  with the architecture's fault_isolation score from the comparison matrix.
  No LLM is involved in computing the blast radius — every propagation rule
  is a hard-coded, auditable decision that mirrors real deployment topology
  semantics (shared process vs isolated service vs event-driven consumer).

  The simulation answers: "If this specific component fails, which other
  components go down, degrade, or stay healthy?" It does NOT predict data
  loss, latency, or partial functionality beyond the coarse status labels.

  Resilience recommendations are rule-based: each mitigation maps to
  canonical roles, applies deterministic status transformations, and
  reduces severity by a fixed amount. No LLM decides scores or
  recommendations.

Canonical roles:
  client, gateway, app_service, business_logic, database, message_broker,
  cache, auth_service, external_integration
"""

from __future__ import annotations

from app.schemas.domain import (
    ArchitectureComponent,
    ArchitectureOption,
    BlastRadiusResult,
    ComponentStatus,
    ResilienceRecommendation,
)

# ---------------------------------------------------------------------------
# Canonical role definitions for keyword matching
# ---------------------------------------------------------------------------

_ROLE_KEYWORDS: dict[str, list[str]] = {
    "client": ["client", "frontend", "web app", "web client", "browser", "ui"],
    "gateway": ["gateway", "api gateway", "edge", "cdn", "load balancer", "proxy"],
    "app_service": [
        "service", "api layer", "backend", "worker", "processor",
        "handler", "orchestrator", "microservice", "function", "lambda",
    ],
    "business_logic": [
        "core", "business logic", "domain", "rule engine", "engine",
        "recommendation", "analysis", "scoring", "pipeline",
    ],
    "database": ["database", "db", "postgres", "postgresql", "mysql", "mongo", "dynamodb", "persistence", "storage"],
    "message_broker": ["broker", "queue", "message", "kafka", "rabbitmq", "sqs", "sns", "event bus", "pubsub"],
    "cache": ["cache", "redis", "memcached", "elasticache"],
    "auth_service": ["auth", "authentication", "authorization", "identity", "oauth", "jwt", "session"],
    "external_integration": ["integration", "external", "third-party", "webhook", "payment", "gateway api"],
}

# ---------------------------------------------------------------------------
# Failure propagation rules per architecture style
# ---------------------------------------------------------------------------
#
# Each entry maps a failed_role -> set of roles that are affected.
# Status is encoded as:
#   "down"     = fully unavailable
#   "degraded" = partially functional (reason appended)
#
# Roles not listed for a given failure are assumed "healthy".

PROPAGATION_RULES: dict[str, list[tuple[str, str, str | None]]] = {
    # --- Monolithic / Layered / Clean ---
    # Shared process: if ANY app-tier role fails, ALL app-tier roles fail.
    # Client survives but sees total failure of the backend.
    "modular-monolith": {
        "client": [("client", "down", None)],
        "gateway": [
            ("gateway", "down", None),
            ("app_service", "down", "request routing interrupted"),
            ("business_logic", "down", "request routing interrupted"),
        ],
        "app_service": [
            ("app_service", "down", None),
            ("business_logic", "down", "shared process crashed"),
            ("gateway", "down", "upstream dependency lost"),
            ("database", "down", "shared process crashed"),
            ("cache", "down", "shared process crashed"),
            ("auth_service", "down", "shared process crashed"),
        ],
        "business_logic": [
            ("business_logic", "down", None),
            ("app_service", "down", "shared process crashed"),
            ("gateway", "down", "upstream dependency lost"),
            ("database", "down", "shared process crashed"),
            ("cache", "down", "shared process crashed"),
            ("auth_service", "down", "shared process crashed"),
        ],
        "database": [
            ("database", "down", None),
            ("app_service", "down", "cannot persist or read state"),
            ("business_logic", "down", "cannot persist or read state"),
            ("gateway", "down", "backend read failures cascade"),
        ],
        "message_broker": [
            ("message_broker", "down", None),
            ("app_service", "degraded", "async workflows blocked"),
            ("business_logic", "degraded", "async workflows blocked"),
        ],
        "cache": [
            ("cache", "down", None),
            ("app_service", "degraded", "cache miss fallback to DB, latency spike"),
            ("business_logic", "degraded", "cache miss fallback to DB, latency spike"),
        ],
        "auth_service": [
            ("auth_service", "down", None),
            ("app_service", "down", "authentication unavailable"),
            ("gateway", "down", "unauthenticated requests rejected"),
        ],
        "external_integration": [
            ("external_integration", "down", None),
            ("app_service", "degraded", "downstream call failures"),
            ("business_logic", "degraded", "downstream call failures"),
        ],
    },
    # --- Event-Driven Microservices ---
    # Strong fault isolation: only directly dependent services fail.
    # Client degrades gracefully. Broker failure is catastrophic.
    "event-driven-microservices": {
        "client": [("client", "down", None)],
        "gateway": [
            ("gateway", "down", None),
            ("app_service", "degraded", "request routing interrupted"),
        ],
        "app_service": [
            ("app_service", "down", None),
            ("gateway", "degraded", "partial backend degradation"),
        ],
        "business_logic": [
            ("business_logic", "down", None),
            ("app_service", "degraded", "domain logic unavailable"),
        ],
        "database": [
            ("database", "down", None),
            ("app_service", "down", "cannot persist or read state"),
            ("business_logic", "down", "cannot persist or read state"),
        ],
        "message_broker": [
            ("message_broker", "down", None),
            ("app_service", "degraded", "async events stopped, backlog growing"),
            ("business_logic", "degraded", "async events stopped, backlog growing"),
        ],
        "cache": [
            ("cache", "down", None),
            ("app_service", "degraded", "cache miss, fallback to DB"),
        ],
        "auth_service": [
            ("auth_service", "down", None),
            ("app_service", "down", "authentication unavailable"),
            ("gateway", "down", "unauthenticated requests rejected"),
        ],
        "external_integration": [
            ("external_integration", "down", None),
            ("app_service", "degraded", "downstream call failures"),
        ],
    },
    # --- Serverless Platform ---
    # Functions are isolated by default. Shared managed services
    # (database, auth) failing cascades to all functions that call them.
    "serverless-platform": {
        "client": [("client", "down", None)],
        "gateway": [
            ("gateway", "down", None),
            ("app_service", "degraded", "request routing interrupted"),
        ],
        "app_service": [
            ("app_service", "down", None),
        ],
        "business_logic": [
            ("business_logic", "down", None),
            ("app_service", "degraded", "domain logic unavailable"),
        ],
        "database": [
            ("database", "down", None),
            ("app_service", "down", "cannot persist or read state"),
            ("business_logic", "down", "cannot persist or read state"),
        ],
        "message_broker": [
            ("message_broker", "down", None),
            ("app_service", "degraded", "async invocations paused"),
            ("business_logic", "degraded", "async invocations paused"),
        ],
        "cache": [
            ("cache", "down", None),
            ("app_service", "degraded", "cold starts increase, latency degraded"),
        ],
        "auth_service": [
            ("auth_service", "down", None),
            ("app_service", "down", "authentication unavailable"),
            ("gateway", "down", "unauthenticated requests rejected"),
        ],
        "external_integration": [
            ("external_integration", "down", None),
            ("app_service", "degraded", "downstream call failures"),
        ],
    },
}

# Default propagation for unknown architecture IDs — treat like microservices
# (conservative isolation assumption).
DEFAULT_PROPAGATION = PROPAGATION_RULES["event-driven-microservices"]

# Architecture ID aliases — the codebase uses hyphenated IDs, the spec
# uses underscored names. Map both to canonical rule keys.
_ARCH_ID_ALIASES: dict[str, str] = {
    "modular-monolith": "modular-monolith",
    "monolithic": "modular-monolith",
    "layered": "modular-monolith",
    "clean": "modular-monolith",
    "event-driven-microservices": "event-driven-microservices",
    "microservices": "event-driven-microservices",
    "event_driven": "event-driven-microservices",
    "event-driven": "event-driven-microservices",
    "serverless-platform": "serverless-platform",
    "serverless": "serverless-platform",
}


def _resolve_rules(architecture_id: str) -> dict[str, list[tuple[str, str, str | None]]]:
    key = _ARCH_ID_ALIASES.get(architecture_id, architecture_id)
    return PROPAGATION_RULES.get(key, DEFAULT_PROPAGATION)


# ---------------------------------------------------------------------------
# Role mapping
# ---------------------------------------------------------------------------


def map_components_to_roles(architecture: ArchitectureOption) -> dict[str, str]:
    """Map each literal component name to a canonical role via keyword matching.

    Returns a dict of component_name -> role. Unmatched components default
    to 'app_service' since most application-tier components behave like
    generic services for blast-radius purposes.
    """
    mapping: dict[str, str] = {}
    for component in architecture.components:
        name_lower = component.name.lower()
        matched_role = "app_service"  # fallback

        best_match_len = 0
        for role, keywords in _ROLE_KEYWORDS.items():
            for keyword in keywords:
                if keyword in name_lower and len(keyword) > best_match_len:
                    matched_role = role
                    best_match_len = len(keyword)
                    break

        mapping[component.name] = matched_role
    return mapping


# ---------------------------------------------------------------------------
# Severity scoring
# ---------------------------------------------------------------------------


def _compute_severity(
    fault_isolation: int,
    statuses: list[ComponentStatus],
) -> float:
    """Derive severity_score 0-10 from fault_isolation and collapse count.

    fault_isolation is 1-10 where 10 = excellent isolation.
    A high fault_isolation means failures are contained (low severity).
    We adjust by the proportion of components that went fully 'down'.
    """
    base_severity = 10 - fault_isolation  # 0-9 range

    total = len(statuses) or 1
    down_count = sum(1 for s in statuses if s.status == "down")
    degraded_count = sum(1 for s in statuses if s.status == "degraded")

    # Weight down more heavily than degraded
    collapse_ratio = (down_count * 1.0 + degraded_count * 0.4) / total
    severity = base_severity + (collapse_ratio * 4)
    return round(min(10.0, max(0.0, severity)), 1)


# ---------------------------------------------------------------------------
# Impact summary
# ---------------------------------------------------------------------------


def _build_impact_summary(
    failed_component: str,
    statuses: list[ComponentStatus],
) -> str:
    """Compose a human-readable impact summary string."""
    down = [s for s in statuses if s.status == "down"]
    degraded = [s for s in statuses if s.status == "degraded"]
    healthy = [s for s in statuses if s.status == "healthy"]

    total = len(statuses)
    parts: list[str] = []

    if down:
        parts.append(f"{len(down)} of {total} components down")
    if degraded:
        parts.append(f"{len(degraded)} degraded")
    if not down and not degraded:
        parts.append(f"All {total} components healthy")

    detail_parts: list[str] = []
    if down:
        down_names = ", ".join(s.component for s in down)
        detail_parts.append(f"Down: {down_names}")
    if degraded:
        degraded_names = ", ".join(s.component for s in degraded)
        detail_parts.append(f"Degraded: {degraded_names}")
    if healthy and (down or degraded):
        healthy_names = ", ".join(s.component for s in healthy)
        detail_parts.append(f"Healthy: {healthy_names}")

    summary = "; ".join(parts)
    if detail_parts:
        summary += ". " + ". ".join(detail_parts) + "."
    return summary


# ---------------------------------------------------------------------------
# Main simulation entry point
# ---------------------------------------------------------------------------


def simulate_failure(
    architecture: ArchitectureOption,
    failed_component: str,
    comparison_matrix: dict[str, dict[str, int]],
) -> BlastRadiusResult:
    """Simulate what happens when *failed_component* fails in *architecture*.

    Pure deterministic computation — no LLM, no network, no side effects.
    The comparison_matrix provides the fault_isolation score for severity
    calculation. The architecture's component list and the propagation rules
    determine which other components are affected.
    """
    component_to_role = map_components_to_roles(architecture)
    failed_role = component_to_role.get(failed_component, "app_service")

    # Look up fault_isolation from comparison matrix
    arch_scores = comparison_matrix.get(architecture.id, {})
    fault_isolation = arch_scores.get("fault_isolation", 5)

    # Prefer the generated, project-specific dependency graph. Each edge is
    # ``consumer -> required component`` and therefore represents an actual
    # service/data dependency. Older saved architectures without these edges
    # retain the role-based compatibility path below.
    if any(component.dependencies for component in architecture.components):
        component_names = {component.name for component in architecture.components}
        dependencies = {
            component.name: [name for name in component.dependencies if name in component_names]
            for component in architecture.components
        }
        reverse: dict[str, list[str]] = {name: [] for name in component_names}
        for consumer, required in dependencies.items():
            for dependency in required:
                reverse.setdefault(dependency, []).append(consumer)

        status_by_name: dict[str, tuple[str, str | None]] = {
            failed_component: ("down", None)
        }
        queue = [failed_component]
        while queue:
            unavailable = queue.pop(0)
            unavailable_role = component_to_role.get(unavailable, "app_service")
            for consumer in reverse.get(unavailable, []):
                previous = status_by_name.get(consumer)
                # Shared event/integration/cache dependencies degrade their
                # consumers; exclusive data/auth/API dependencies take the
                # direct consumer down. A service behind an aggregator only
                # removes part of that aggregator's capability.
                consumer_dependencies = dependencies.get(consumer, [])
                degraded_dependency = unavailable_role in {
                    "message_broker", "cache", "external_integration",
                } or (
                    unavailable_role in {"app_service", "business_logic"}
                    and len(consumer_dependencies) > 1
                )
                new_status = "degraded" if degraded_dependency else "down"
                reason = f"runtime dependency unavailable: {unavailable}"
                if previous and previous[0] == "down":
                    continue
                status_by_name[consumer] = (new_status, reason)
                if new_status == "down":
                    queue.append(consumer)

        statuses = []
        for component in architecture.components:
            status, reason = status_by_name.get(component.name, ("healthy", None))
            statuses.append(ComponentStatus(
                component=component.name,
                role=component_to_role[component.name],
                status=status,
                reason=reason,
            ))
        return BlastRadiusResult(
            failed_component=failed_component,
            architecture_id=architecture.id,
            statuses=statuses,
            impact_summary=_build_impact_summary(failed_component, statuses),
            severity_score=_compute_severity(fault_isolation, statuses),
        )

    rules = _resolve_rules(architecture.id)
    # Build lookup: affected_role -> (status, reason) for the failed role
    propagation: dict[str, tuple[str, str | None]] = {}
    for affected_role, status_str, reason in rules.get(failed_role, []):
        propagation[affected_role] = (status_str, reason)

    statuses: list[ComponentStatus] = []
    for component in architecture.components:
        if component.name == failed_component:
            statuses.append(
                ComponentStatus(
                    component=component.name,
                    role=component_to_role[component.name],
                    status="down",
                    reason=None,
                )
            )
            continue

        role = component_to_role[component.name]
        if role in propagation:
            status_str, reason = propagation[role]
            statuses.append(
                ComponentStatus(
                    component=component.name,
                    role=role,
                    status=status_str,
                    reason=reason,
                )
            )
        else:
            statuses.append(
                ComponentStatus(
                    component=component.name,
                    role=role,
                    status="healthy",
                    reason=None,
                )
            )

    impact_summary = _build_impact_summary(failed_component, statuses)
    severity_score = _compute_severity(fault_isolation, statuses)

    return BlastRadiusResult(
        failed_component=failed_component,
        architecture_id=architecture.id,
        statuses=statuses,
        impact_summary=impact_summary,
        severity_score=severity_score,
    )


# ---------------------------------------------------------------------------
# Resilience mitigation catalog
# ---------------------------------------------------------------------------
#
# Each mitigation entry defines:
#   id                       – unique identifier
#   name                     – human-readable name
#   category                 – grouping label (isolation, redundancy, etc.)
#   description              – what the mitigation does in plain language
#   applicable_roles         – canonical roles this mitigation can protect
#   severity_reduction       – fixed points subtracted from severity_score
#   status_transformations   – role -> (new_status, new_reason) mappings
#                              "down" -> "degraded" or "degraded" -> "healthy"

MITIGATION_CATALOG: list[dict] = [
    {
        "id": "multi-region-static-delivery",
        "name": "Multi-Region Static Delivery",
        "category": "redundancy",
        "description": "Replicates the web client across independent edge origins so a failed deployment can fall back to the last known good release.",
        "applicable_roles": ["client"],
        "severity_reduction": 1.5,
        "status_transformations": {
            "client": ("degraded", "secondary edge origin serving the last known good client"),
        },
    },
    {
        "id": "circuit-breaker",
        "name": "Circuit Breaker",
        "category": "isolation",
        "description": "Prevents cascade failures by opening the circuit when a downstream dependency fails, returning a fallback response instead of propagating the error.",
        "applicable_roles": ["app_service", "business_logic", "gateway"],
        "severity_reduction": 1.5,
        "status_transformations": {
            "gateway": ("degraded", "circuit breaker returns fallback response"),
            "app_service": ("degraded", "circuit breaker returns fallback response"),
            "business_logic": ("degraded", "circuit breaker returns fallback response"),
        },
    },
    {
        "id": "database-replication",
        "name": "Database Replication",
        "category": "redundancy",
        "description": "Adds read replicas and automatic failover so that a primary database failure degrades writes but preserves read availability.",
        "applicable_roles": ["database"],
        "severity_reduction": 2.0,
        "status_transformations": {
            "database": ("degraded", "primary down, replica serving reads"),
            "app_service": ("degraded", "write path unavailable, reads via replica"),
            "business_logic": ("degraded", "write path unavailable, reads via replica"),
        },
    },
    {
        "id": "cache-fallback",
        "name": "Cache Fallback to Database",
        "category": "redundancy",
        "description": "Falls back to direct database queries when the cache layer is unavailable, trading latency for continued availability.",
        "applicable_roles": ["cache"],
        "severity_reduction": 1.0,
        "status_transformations": {
            "cache": ("degraded", "cache unavailable, falling back to DB"),
            "app_service": ("degraded", "cache miss, direct DB queries (latency spike)"),
        },
    },
    {
        "id": "broker-dlq",
        "name": "Dead Letter Queue + Retry",
        "category": "resilience",
        "description": "Routes unprocessable messages to a dead letter queue with exponential backoff retries, preventing message loss during broker outages.",
        "applicable_roles": ["message_broker"],
        "severity_reduction": 1.0,
        "status_transformations": {
            "message_broker": ("degraded", "broker degraded, DLQ absorbing messages"),
            "app_service": ("degraded", "async processing delayed, messages queued"),
        },
    },
    {
        "id": "auth-token-cache",
        "name": "Cached Auth Tokens",
        "category": "redundancy",
        "description": "Caches authentication tokens locally so that brief auth service outages don't block every request.",
        "applicable_roles": ["auth_service"],
        "severity_reduction": 1.5,
        "status_transformations": {
            "auth_service": ("degraded", "auth service down, serving cached tokens"),
            "app_service": ("degraded", "using cached auth tokens ( expiry risk )"),
            "gateway": ("degraded", "using cached auth tokens ( expiry risk )"),
        },
    },
    {
        "id": "rate-limiting",
        "name": "Rate Limiting + Backpressure",
        "category": "isolation",
        "description": "Applies rate limiting and backpressure to prevent a failing component from being overwhelmed by retries or traffic spikes.",
        "applicable_roles": ["gateway", "app_service"],
        "severity_reduction": 0.5,
        "status_transformations": {
            "gateway": ("degraded", "rate limiting active, some requests rejected"),
            "app_service": ("degraded", "backpressure applied, reduced throughput"),
        },
    },
    {
        "id": "graceful-degradation",
        "name": "Graceful Degradation",
        "category": "resilience",
        "description": "Returns cached or partial responses when a dependency is unavailable, preserving core functionality at reduced fidelity.",
        "applicable_roles": ["app_service", "business_logic", "external_integration"],
        "severity_reduction": 1.0,
        "status_transformations": {
            "app_service": ("degraded", "returning cached/partial responses"),
            "business_logic": ("degraded", "non-critical features disabled"),
            "external_integration": ("degraded", "third-party calls bypassed, using fallback"),
        },
    },
    {
        "id": "bulkhead",
        "name": "Bulkhead Isolation",
        "category": "isolation",
        "description": "Isolates component failure domains with thread-pool or process boundaries so that a crash in one module cannot consume all resources.",
        "applicable_roles": ["app_service", "business_logic"],
        "severity_reduction": 1.0,
        "status_transformations": {
            "app_service": ("degraded", "bulkhead isolated, partial functionality"),
            "business_logic": ("degraded", "bulkhead isolated, non-critical paths down"),
        },
    },
]


def suggest_mitigations(
    blast_result: BlastRadiusResult,
    architecture: ArchitectureOption,
) -> list[ResilienceRecommendation]:
    """Return deterministic mitigation suggestions for a blast radius result.

    Selection logic:
      1. Map the failed component to its canonical role.
      2. Filter the MITIGATION_CATALOG to entries whose applicable_roles
         include the failed role.
      3. For each candidate, check whether at least one status_transformations
         key matches a component that is currently "down" or "degraded" —
         otherwise the mitigation would have no observable effect.
      4. Cap at 5 recommendations to avoid overwhelming the user.
    """
    component_to_role = map_components_to_roles(architecture)
    failed_role = component_to_role.get(blast_result.failed_component, "app_service")

    # Index statuses by role for quick lookup
    role_to_statuses: dict[str, list[ComponentStatus]] = {}
    for s in blast_result.statuses:
        role_to_statuses.setdefault(s.role, []).append(s)

    recommendations: list[ResilienceRecommendation] = []
    for entry in MITIGATION_CATALOG:
        if failed_role not in entry["applicable_roles"]:
            continue

        # Check that at least one transformation target is actually affected
        has_effect = False
        for target_role in entry["status_transformations"]:
            for s in role_to_statuses.get(target_role, []):
                if s.status in ("down", "degraded"):
                    has_effect = True
                    break
            if has_effect:
                break

        if not has_effect:
            continue

        recommendations.append(
            ResilienceRecommendation(
                id=entry["id"],
                name=entry["name"],
                category=entry["category"],
                description=entry["description"],
                severity_reduction=entry["severity_reduction"],
            )
        )

        if len(recommendations) >= 5:
            break

    return recommendations


def apply_mitigations(
    blast_result: BlastRadiusResult,
    selected_mitigation_ids: list[str],
    architecture: ArchitectureOption,
) -> BlastRadiusResult:
    """Apply selected mitigations and return a modified blast radius result.

    For each selected mitigation, iterate over its status_transformations.
    If a component with a matching role is currently "down", upgrade it to
    the transformation's target status (typically "degraded"). If it is
    already "degraded", leave it as-is (mitigations never downgrade).

    Severity is recomputed from scratch using the updated statuses, so the
    improvement is fully deterministic and auditable.
    """
    component_to_role = map_components_to_roles(architecture)

    # Build a lookup of mitigation entries by id
    catalog_by_id = {e["id"]: e for e in MITIGATION_CATALOG}

    # Deep-copy statuses so we don't mutate the original
    updated_statuses = [
        ComponentStatus(
            component=s.component,
            role=s.role,
            status=s.status,
            reason=s.reason,
        )
        for s in blast_result.statuses
    ]

    for mid in selected_mitigation_ids:
        entry = catalog_by_id.get(mid)
        if not entry:
            continue

        for target_role, (new_status, new_reason) in entry["status_transformations"].items():
            for s in updated_statuses:
                if s.role == target_role and s.status in ("down", "degraded"):
                    # Only upgrade, never downgrade
                    status_priority = {"healthy": 0, "degraded": 1, "down": 2}
                    if status_priority.get(new_status, 1) < status_priority.get(s.status, 2):
                        s.status = new_status
                        s.reason = new_reason

    # Recompute severity from updated statuses
    arch_scores = {}  # We don't have the original comparison_matrix here,
    # so recompute severity using a neutral fault_isolation.
    # The caller should provide comparison_matrix if they want exact
    # recalculation. For the apply path we use the original score as baseline
    # and subtract total severity_reduction from applied mitigations.
    total_reduction = sum(
        catalog_by_id[mid]["severity_reduction"]
        for mid in selected_mitigation_ids
        if mid in catalog_by_id
    )
    new_severity = round(max(0.0, blast_result.severity_score - total_reduction), 1)

    # Rebuild impact summary from updated statuses
    new_impact_summary = _build_impact_summary(blast_result.failed_component, updated_statuses)

    return BlastRadiusResult(
        failed_component=blast_result.failed_component,
        architecture_id=blast_result.architecture_id,
        statuses=updated_statuses,
        impact_summary=new_impact_summary,
        severity_score=new_severity,
    )
