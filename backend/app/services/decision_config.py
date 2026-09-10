"""Documented, centralized constants for deterministic architecture decisions.

The values are deliberately modest: they express relative decision pressure,
not claims about real-world infrastructure capacity. Keeping them here makes a
review or product calibration change explicit and testable.
"""

from __future__ import annotations

ARCHITECTURE_METRIC_WEIGHTS: dict[str, float] = {
    "scalability": 0.12,
    "performance": 0.09,
    "maintainability": 0.10,
    "security": 0.10,
    "cost": 0.08,
    "reliability": 0.09,
    "availability": 0.08,
    "deployment_complexity": 0.08,
    "learning_curve": 0.06,
    "development_time": 0.08,
    "fault_isolation": 0.06,
    "operational_complexity": 0.06,
}

ARCHITECTURE_DECISION_MODEL_VERSION = "semantic-provenance-direction-aware-v3"

# Score differences are measured on the displayed 0-100 weighted scale.
# Full internal precision decides order; these constants control only how the
# result is communicated.
RECOMMENDATION_EXACT_TIE_EPSILON = 0.005
RECOMMENDATION_NEAR_TIE_MARGIN = 1.0

# Metric values are shown as the quantity named by the metric. Capability
# metrics are maximized, while burden metrics are minimized. Ranking always
# uses ``metric_utility`` so a low complexity/cost/time value contributes more
# than a high one without relabelling the raw value as a benefit score.
ARCHITECTURE_METRIC_DIRECTIONS: dict[str, str] = {
    "scalability": "maximize",
    "performance": "maximize",
    "maintainability": "maximize",
    "security": "maximize",
    "cost": "minimize",
    "reliability": "maximize",
    "availability": "maximize",
    "deployment_complexity": "minimize",
    "learning_curve": "minimize",
    "development_time": "minimize",
    "fault_isolation": "maximize",
    "operational_complexity": "minimize",
}

# Unambiguous product glossary: each metric names a distinct engineering
# property so scorecards cannot conflate related concepts. Cost here is
# strictly an architecture trade-off (relative 1-10 burden), never a monetary
# budget input.
ARCHITECTURE_METRIC_DEFINITIONS: dict[str, str] = {
    "scalability": "Capacity to absorb growth in users, data, and throughput without redesign.",
    "performance": "Latency and throughput of request/event paths under the confirmed workload.",
    "maintainability": "Ease of changing application code safely (modularity, contracts, testability).",
    "security": "Strength of identity, authorization, data-protection, and audit controls.",
    "cost": "Relative infrastructure plus engineering burden of the topology (lower raw is better).",
    "reliability": "Probability of correct operation over time (fault handling, recovery).",
    "availability": "Share of time the system is operable against the stated SLA (redundancy, failover).",
    "deployment_complexity": "Effort and risk of releasing and rolling back changes (lower raw is better).",
    "learning_curve": "Ramp-up burden for the team to become productive (lower raw is better).",
    "development_time": "Time to first production release with the current team (lower raw is better).",
    "fault_isolation": "Blast-radius containment when a component fails.",
    "operational_complexity": "Day-to-day burden of running, observing, and scaling the system (lower raw is better).",
}


def metric_direction(metric: str) -> str:
    return ARCHITECTURE_METRIC_DIRECTIONS.get(metric, "maximize")


def metric_utility(metric: str, raw_score: int | float) -> float:
    """Convert a displayed 1-10 metric into a higher-is-better utility."""
    bounded = max(1.0, min(10.0, float(raw_score)))
    return 11.0 - bounded if metric_direction(metric) == "minimize" else bounded


def metric_raw_score(metric: str, utility_score: int | float) -> int:
    """Convert a higher-is-better utility back to its displayed direction."""
    bounded = max(1.0, min(10.0, float(utility_score)))
    raw = 11.0 - bounded if metric_direction(metric) == "minimize" else bounded
    return int(round(raw))

# Upper bounds identify a change in engineering shape, not company maturity.
SCALE_THRESHOLDS = {
    "growth_concurrent_users": 25_000,
    "enterprise_concurrent_users": 100_000,
    "large_team": 50,
    "enterprise_team": 13,
    "large_integration_count": 5,
    "global_region_count": 2,
    "mission_critical_availability": 99.99,
    "high_event_volume_per_day": 1_000_000,
}

# A transparent default blend for precedent matching. Callers may override it.
PRECEDENT_SIMILARITY_WEIGHTS = {
    "domain": 0.25,
    "capability": 0.15,
    "workload": 0.12,
    "scale": 0.10,
    "architecture": 0.14,
    "technology": 0.06,
    "data": 0.07,
    "reliability": 0.06,
    "integration": 0.05,
}

# An industry result with no compatible domain evidence is capped even when its
# topology and stack look similar. This prevents architecture resemblance from
# being presented as industry resemblance. Caps are intentionally low: an
# incompatible domain can never present as a strong precedent.
PRECEDENT_DOMAIN_COMPATIBILITY_THRESHOLD = 40.0
PRECEDENT_INCOMPATIBLE_INDUSTRY_CAP = 25.0
PRECEDENT_WEAK_DOMAIN_OVERALL_CAP = 40.0

# Used for compact, user-facing confidence rather than a misleading single score.
CONFIDENCE_THRESHOLDS = {
    "input_base": 20,
    "input_area_points": 8,
    "explicit_input_points": 3,
    "explicit_input_cap": 12,
    "blueprint_inference_base": 88,
    "model_inference_base": 82,
    "deterministic_inference_base": 74,
    "unknown_domain_penalty": 15,
    "unresolved_inference_penalty": 5,
    "contradiction_inference_penalty": 12,
    "architecture_base": 35,
    "architecture_input_factor": 0.45,
    "known_scale_bonus": 10,
    "unresolved_architecture_penalty": 4,
    "contradiction_architecture_penalty": 10,
}

# These labels are stable product vocabulary and deliberately independent of
# architecture style (for example, serverless never implies a small project).
PROJECT_PROFILE_LABELS = (
    "small/local",
    "departmental",
    "enterprise",
    "large-scale enterprise",
    "globally distributed / mission-critical",
)
