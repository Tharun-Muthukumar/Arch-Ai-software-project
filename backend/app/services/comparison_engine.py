import re

from app.schemas.domain import (
    ArchitectureOption,
    ArchitectureScorecard,
    ComparisonResult,
    CriteriaWeights,
    MetricScore,
    RequirementModel,
)
from app.services.decision_config import (
    ARCHITECTURE_DECISION_MODEL_VERSION,
    ARCHITECTURE_METRIC_WEIGHTS,
    metric_direction,
    metric_raw_score,
    metric_utility,
)

METRICS = [
    "scalability",
    "performance",
    "maintainability",
    "security",
    "cost",
    "reliability",
    "availability",
    "deployment_complexity",
    "learning_curve",
    "development_time",
    "fault_isolation",
    "operational_complexity",
]

# Calibrated starting points: simple topologies lead on cost/simplicity,
# distributed topologies lead on elasticity/isolation. Adjustments below
# (not these bases) decide the winner from confirmed requirement signals.
BASE_UTILITY_PROFILES = {
    "modular-monolith": {
        "scalability": 6,
        "performance": 8,
        "maintainability": 7,
        "security": 7,
        "cost": 9,
        "reliability": 7,
        "availability": 6,
        "deployment_complexity": 9,
        "learning_curve": 9,
        "development_time": 9,
        "fault_isolation": 5,
        "operational_complexity": 9,
    },
    "service-based": {
        "scalability": 7,
        "performance": 8,
        "maintainability": 7,
        "security": 7,
        "cost": 7,
        "reliability": 7,
        "availability": 7,
        "deployment_complexity": 7,
        "learning_curve": 7,
        "development_time": 7,
        "fault_isolation": 7,
        "operational_complexity": 7,
    },
    "event-driven-microservices": {
        "scalability": 10,
        "performance": 7,
        "maintainability": 6,
        "security": 7,
        "cost": 4,
        "reliability": 8,
        "availability": 9,
        "deployment_complexity": 3,
        "learning_curve": 4,
        "development_time": 4,
        "fault_isolation": 10,
        "operational_complexity": 3,
    },
    "serverless-platform": {
        "scalability": 8,
        "performance": 6,
        "maintainability": 7,
        "security": 7,
        "cost": 7,
        "reliability": 8,
        "availability": 8,
        "deployment_complexity": 7,
        "learning_curve": 6,
        "development_time": 8,
        "fault_isolation": 8,
        "operational_complexity": 8,
    },
    "hybrid-modular-serverless": {
        "scalability": 8,
        "performance": 7,
        "maintainability": 7,
        "security": 7,
        "cost": 8,
        "reliability": 8,
        "availability": 8,
        "deployment_complexity": 7,
        "learning_curve": 7,
        "development_time": 8,
        "fault_isolation": 7,
        "operational_complexity": 7,
    },
    "hybrid-event-serverless": {
        "scalability": 9,
        "performance": 7,
        "maintainability": 6,
        "security": 7,
        "cost": 6,
        "reliability": 8,
        "availability": 9,
        "deployment_complexity": 5,
        "learning_curve": 5,
        "development_time": 6,
        "fault_isolation": 9,
        "operational_complexity": 5,
    },
}

# Public/exported profiles use the direction displayed to the user. This keeps
# e.g. deployment_complexity=2 truthful (low burden), while the internal base
# profiles above remain convenient higher-is-better utilities for adjustments.
BASE_PROFILES = {
    architecture_id: {
        metric: metric_raw_score(metric, utility)
        for metric, utility in profile.items()
    }
    for architecture_id, profile in BASE_UTILITY_PROFILES.items()
}


class ComparisonEngine:
    def compare(
        self,
        requirements: RequirementModel,
        architectures: list[ArchitectureOption],
        answers: dict[str, str] | None = None,
    ) -> ComparisonResult:
        answers = answers or {}
        weights = self._build_weights(requirements, answers)
        scorecards: list[ArchitectureScorecard] = []

        for architecture in architectures:
            utility_profile = dict(
                BASE_UTILITY_PROFILES.get(
                    architecture.id, BASE_UTILITY_PROFILES["service-based"]
                )
            )
            utility_profile = self._apply_adjustments(
                utility_profile, architecture.id, requirements, answers
            )
            profile = {
                metric: metric_raw_score(metric, utility_profile[metric])
                for metric in METRICS
            }
            metric_scores = [
                MetricScore(
                    metric=metric,
                    score=profile[metric],
                    direction=metric_direction(metric),  # type: ignore[arg-type]
                    normalized_score=utility_profile[metric],
                    explanation=self._explain(
                        metric,
                        profile[metric],
                        architecture.name,
                        requirements,
                        answers,
                    ),
                    weight=weights[metric],
                    contribution=round(utility_profile[metric] * weights[metric], 3),
                    requirement_signals=self._metric_signals(metric, requirements, answers),
                )
                for metric in METRICS
            ]
            exact_overall_score = sum(
                utility_profile[metric] * weights[metric] for metric in METRICS
            )
            overall_score = round(exact_overall_score, 1)
            weighted_score = overall_score * 10
            scorecards.append(
                ArchitectureScorecard(
                    architecture_id=architecture.id,
                    architecture_name=architecture.name,
                    overall_score=overall_score,
                    weighted_score=weighted_score,
                    ranking_score=exact_overall_score * 10,
                    metric_scores=metric_scores,
                    strengths=self._strengths(architecture.id),
                    risks=self._risks(architecture.id),
                    decision_model=ARCHITECTURE_DECISION_MODEL_VERSION,
                )
            )

        scale_reasoning = (
            f"The `{requirements.scale_profile}` profile raises the weights for elasticity and resilience."
            if requirements.scale_profile != "unknown"
            else "Workload scale is unknown, so scale-sensitive weights remain neutral."
        )
        team_size = self._parse_team_size(answers)
        team_reasoning = (
            f"A {team_size}-person team shifts weight toward operability and delivery speed."
            if team_size
            else "Team size was not specified, so team-sensitive weights remain neutral."
        )
        reasoning = [
            "Scores are rule-based from confirmed requirements, constraints, data characteristics, and operational answers.",
            scale_reasoning,
            team_reasoning,
            "Cost, deployment complexity, learning curve, development time, and operational complexity are burdens where lower raw values are better; all other metrics are capabilities where higher is better.",
            "Overall score is the normalized weight-weighted utility on a 0-10 scale; weighted score is the same result on a 0-100 scale. "
            "Scores are outputs of this deterministic decision model, not objective measurements of real systems.",
        ]

        scorecards.sort(
            key=lambda item: (-(item.ranking_score if item.ranking_score is not None else item.weighted_score), item.architecture_id)
        )

        return ComparisonResult(weights=weights, scorecards=scorecards, reasoning=reasoning)

    def _build_weights(
        self, requirements: RequirementModel, answers: dict[str, str] | None = None
    ) -> dict[str, float]:
        answers = answers or {}
        weights = dict(ARCHITECTURE_METRIC_WEIGHTS)

        if requirements.scale_profile == "high-scale":
            weights["scalability"] += 0.05
            weights["availability"] += 0.03
            weights["reliability"] += 0.02
            weights["cost"] -= 0.02
            weights["development_time"] -= 0.02
        elif requirements.scale_profile == "growth-scale":
            weights["scalability"] += 0.02
            weights["maintainability"] += 0.01
            weights["fault_isolation"] += 0.01
            weights["cost"] -= 0.01
            weights["development_time"] -= 0.01
        elif requirements.scale_profile == "small-scale":
            weights["cost"] += 0.03
            weights["development_time"] += 0.03
            weights["deployment_complexity"] += 0.02
            weights["fault_isolation"] -= 0.02
            weights["scalability"] -= 0.02

        team_size = self._parse_team_size(answers)
        if 0 < team_size <= 6:
            weights["cost"] += 0.02
            weights["development_time"] += 0.02
            weights["deployment_complexity"] += 0.01
            weights["learning_curve"] += 0.01
            weights["scalability"] -= 0.02
            weights["fault_isolation"] -= 0.02
        elif team_size >= 13:
            weights["scalability"] += 0.03
            weights["fault_isolation"] += 0.02
            weights["availability"] += 0.01
            weights["cost"] -= 0.02
            weights["development_time"] -= 0.01

        text = " ".join(
            requirements.functional_requirements
            + requirements.non_functional_requirements
            + requirements.constraints
            + requirements.data_characteristics
        ).lower()
        if any(marker in text for marker in ("audit", "compliance", "pci", "hipaa", "gdpr", "soc2", "regulated")):
            weights["security"] += 0.02
            weights["reliability"] += 0.01
            weights["development_time"] -= 0.01
        if any(marker in text for marker in ("realtime", "real-time", "event processing", "stream", "telemetry", "sensor")):
            weights["scalability"] += 0.02
            weights["performance"] += 0.01
            weights["fault_isolation"] += 0.01
            weights["cost"] -= 0.01

        total = sum(weights.values())
        return {metric: round(value / total, 4) for metric, value in weights.items()}

    def _apply_adjustments(
        self,
        profile: dict[str, int],
        architecture_id: str,
        requirements: RequirementModel,
        answers: dict[str, str],
    ) -> dict[str, int]:
        lower_requirements = " ".join(
            requirements.functional_requirements
            + requirements.non_functional_requirements
            + requirements.constraints
            + requirements.data_characteristics
        ).lower()
        entity_count = len(requirements.domain_entities)
        workflow_count = len(requirements.domain_workflows)
        integration_count = len(requirements.integrations)
        complex_domain = entity_count >= 6 or workflow_count >= 5
        many_integrations = integration_count >= 3
        realtime = any(marker in lower_requirements for marker in ("realtime", "real-time", "event processing", "stream", "telemetry", "sensor"))
        variable_demand = any(marker in lower_requirements for marker in ("bursty", "spiky", "variable demand", "seasonal", "batch"))
        compliance = any(marker in lower_requirements for marker in ("audit", "compliance", "pci", "hipaa", "gdpr", "soc2", "regulated"))
        strict_avail = bool(
            (requirements.project_profile.availability_target_percent or 0) >= 99.99
        ) or any(marker in lower_requirements for marker in ("99.99", "four nines", "strict availability"))
        latency_match = re.search(r"(?:latency|response time)[^\d]{0,20}(\d+)\s*ms", lower_requirements)
        low_latency = bool(latency_match and int(latency_match.group(1)) <= 100)
        team_size = self._parse_team_size(answers)
        cloud = (answers.get("preferred_cloud") or "").lower()
        regions = self._parse_int(answers.get("geographic_regions", "0") or "0")
        high_scale = requirements.scale_profile == "high-scale"
        growth_scale = requirements.scale_profile == "growth-scale"
        small_scale = requirements.scale_profile == "small-scale"

        is_monolith = architecture_id == "modular-monolith"
        is_service = architecture_id == "service-based"
        is_micro = architecture_id == "event-driven-microservices"
        is_serverless = architecture_id == "serverless-platform"
        is_hybrid_modular = architecture_id == "hybrid-modular-serverless"
        is_hybrid_event = architecture_id == "hybrid-event-serverless"

        # Scale pressure: reward independent scaling, penalise single deployables.
        if high_scale:
            if is_micro:
                profile["scalability"] += 1
                profile["availability"] += 1
            if is_hybrid_event:
                profile["scalability"] += 1
                profile["availability"] += 1
            if is_serverless:
                profile["scalability"] += 1
            if is_service:
                profile["scalability"] += 1
            if is_monolith:
                profile["scalability"] -= 2
                profile["availability"] -= 1
                profile["fault_isolation"] -= 1
                profile["maintainability"] -= 1
            if is_hybrid_modular and not variable_demand:
                profile["scalability"] -= 1
        elif growth_scale:
            if is_micro or is_hybrid_event:
                profile["scalability"] += 1
            if is_service or is_hybrid_modular:
                profile["maintainability"] += 1
            if is_monolith:
                profile["scalability"] -= 1
        elif small_scale:
            if is_micro:
                profile["cost"] -= 1
                profile["development_time"] -= 1
            if is_hybrid_event:
                profile["cost"] -= 1
            if is_monolith or is_hybrid_modular:
                profile["development_time"] += 1
                profile["cost"] += 1

        # Realtime / event-driven workloads.
        if realtime:
            if is_micro or is_hybrid_event:
                profile["scalability"] += 1
                profile["performance"] += 1
            if is_serverless:
                profile["scalability"] += 1
            if is_service:
                profile["performance"] += 1
            if is_hybrid_modular:
                profile["scalability"] += 1
            if is_monolith:
                profile["scalability"] -= 1
                profile["performance"] -= 1

        # Variable / bursty demand favours elastic edges.
        if variable_demand:
            if is_serverless or is_hybrid_modular:
                profile["scalability"] += 1
                profile["cost"] += 1
            if is_hybrid_event:
                profile["scalability"] += 1
            if is_monolith:
                profile["scalability"] -= 1
                profile["cost"] -= 1

        # Strict availability targets.
        if strict_avail:
            if is_monolith:
                profile["availability"] -= 2
                profile["fault_isolation"] -= 1
                profile["reliability"] -= 1
            else:
                profile["availability"] += 1
            if is_micro or is_hybrid_event:
                profile["fault_isolation"] += 1

        # Tight latency budgets favour fewer network hops.
        if low_latency:
            if is_monolith:
                profile["performance"] += 1
            if is_service:
                profile["performance"] += 1
            if is_micro or is_hybrid_event:
                profile["performance"] -= 1
            if is_serverless:
                profile["performance"] -= 1

        # Compliance-heavy briefs reward audit simplicity; distribution pays governance cost.
        if compliance:
            profile["security"] += 1
            if is_monolith or is_service or is_hybrid_modular:
                profile["maintainability"] += 1
            if is_micro or is_hybrid_event:
                profile["operational_complexity"] -= 1
                profile["learning_curve"] -= 1
            if is_serverless:
                profile["learning_curve"] -= 1

        # Cloud posture changes managed-service leverage.
        if cloud in {"aws", "azure", "gcp"}:
            if is_serverless or is_hybrid_event or is_hybrid_modular:
                profile["deployment_complexity"] += 1
                profile["cost"] += 1
            if is_micro:
                profile["deployment_complexity"] += 1
        elif cloud in {"on-premise", "on premise", "onprem", "self-hosted"}:
            if is_serverless:
                profile["deployment_complexity"] -= 2
                profile["cost"] -= 1
                profile["availability"] -= 1
            if is_hybrid_modular or is_hybrid_event:
                profile["deployment_complexity"] -= 1
            if is_micro:
                profile["deployment_complexity"] -= 1
            if is_monolith or is_service:
                profile["deployment_complexity"] += 1

        # Multi-region operation.
        if regions > 1:
            if is_monolith:
                profile["availability"] -= 1
                profile["deployment_complexity"] -= 2
            elif is_service:
                profile["availability"] += 1
            elif is_micro or is_hybrid_event:
                profile["availability"] += 1
            else:
                profile["availability"] += 1
                profile["deployment_complexity"] += 1

        # Team-size pressure (Conway-aware): small teams pay distributed overhead,
        # large teams outgrow single-deployable ownership.
        if 0 < team_size <= 6:
            if is_micro:
                profile["operational_complexity"] -= 2
                profile["deployment_complexity"] -= 1
                profile["learning_curve"] -= 1
                profile["development_time"] -= 1
            if is_hybrid_event:
                profile["operational_complexity"] -= 1
                profile["deployment_complexity"] -= 1
                profile["learning_curve"] -= 1
            if is_service:
                profile["operational_complexity"] -= 1
                profile["development_time"] -= 1
            if is_monolith or is_hybrid_modular:
                profile["operational_complexity"] += 1
                profile["development_time"] += 1
        elif 7 <= team_size <= 12:
            if is_service or is_hybrid_modular:
                profile["maintainability"] += 1
                profile["development_time"] += 1
            if is_micro or is_hybrid_event:
                profile["development_time"] += 1
            if is_monolith:
                profile["maintainability"] -= 1
        elif team_size >= 13:
            if is_micro or is_hybrid_event:
                profile["operational_complexity"] += 1
                profile["development_time"] += 1
                profile["learning_curve"] += 1
            if is_service:
                profile["maintainability"] += 1
            if is_monolith:
                profile["maintainability"] -= 1
                profile["fault_isolation"] -= 1
                profile["development_time"] -= 1

        # Domain complexity and integration sprawl.
        if complex_domain:
            if is_monolith:
                profile["maintainability"] -= 1
                profile["fault_isolation"] -= 1
            if is_service or is_micro:
                profile["maintainability"] += 1
            if is_hybrid_event or is_hybrid_modular:
                profile["scalability"] += 1
        if many_integrations:
            if is_monolith:
                profile["maintainability"] -= 1
            if is_micro or is_service or is_hybrid_event:
                profile["scalability"] += 1
                profile["fault_isolation"] += 1

        return {metric: max(1, min(10, score)) for metric, score in profile.items()}

    def _metric_signals(
        self, metric: str, requirements: RequirementModel, answers: dict[str, str]
    ) -> list[str]:
        """Expose the exact project signals that contributed to a metric."""
        profile = requirements.project_profile
        signals: list[str] = []
        if metric in {"scalability", "performance", "availability", "reliability", "fault_isolation"}:
            if profile.concurrent_users:
                signals.append(f"confirmed concurrency: {profile.concurrent_users:,}")
            if profile.event_volume_per_day:
                signals.append(f"confirmed event volume: {profile.event_volume_per_day:,}/day")
            if profile.availability_target_percent:
                signals.append(f"confirmed availability: {profile.availability_target_percent}%")
            if profile.geographic_scope == "global/multi-region":
                signals.append("global or multi-region operation")
        if metric == "security" and requirements.security_model.authorization:
            signals.append("authorization: " + ", ".join(requirements.security_model.authorization))
        if metric in {"maintainability", "fault_isolation", "operational_complexity"}:
            count = len(requirements.integration_details) or len(requirements.integrations)
            if count:
                signals.append(f"integration boundaries: {count}")
            if profile.team_size:
                signals.append(f"team size: {profile.team_size}")
        if metric == "cost":
            if requirements.project_profile.event_volume_per_day:
                signals.append(
                    f"sustained workload: {requirements.project_profile.event_volume_per_day:,} events/day"
                )
            if requirements.project_profile.geographic_scope == "global/multi-region":
                signals.append("multi-region infrastructure footprint")
            if requirements.integration_details:
                signals.append(f"integration operations: {len(requirements.integration_details)} boundaries")
        return signals or ["no metric-specific confirmed signal; neutral baseline retained"]

    @staticmethod
    def _parse_team_size(answers: dict[str, str]) -> int:
        match = re.search(r"\d+", str((answers or {}).get("team_size", "") or ""))
        return int(match.group()) if match else 0

    @staticmethod
    def _parse_int(value: str) -> int:
        match = re.search(r"\d+", str(value or ""))
        return int(match.group()) if match else 0

    def _explain(
        self,
        metric: str,
        score: int,
        architecture_name: str,
        requirements: RequirementModel,
        answers: dict[str, str] | None = None,
    ) -> str:
        answers = answers or {}
        drivers: list[str] = []
        scale = requirements.scale_profile
        if scale == "high-scale" and metric in {"scalability", "availability", "fault_isolation", "reliability"}:
            drivers.append("the confirmed high-scale brief rewards horizontal elasticity and isolation")
        elif scale == "small-scale" and metric in {"cost", "development_time", "deployment_complexity", "learning_curve"}:
            drivers.append("the small-scale brief rewards low operational overhead and fast delivery")
        elif scale == "unknown" and metric in {"scalability", "availability"}:
            drivers.append("unknown workload scale keeps elasticity expectations neutral")
        team_size = self._parse_team_size(answers)
        if team_size and metric in {"operational_complexity", "deployment_complexity", "learning_curve", "development_time"}:
            if team_size <= 6:
                drivers.append(f"a {team_size}-person team is sensitive to operational overhead")
            elif team_size >= 13:
                drivers.append(f"a {team_size}-person team can staff parallel ownership")
            else:
                drivers.append(f"a {team_size}-person team supports bounded service ownership")
        text = " ".join(
            requirements.functional_requirements
            + requirements.non_functional_requirements
            + requirements.constraints
            + requirements.data_characteristics
        ).lower()
        if metric == "performance" and ("latency" in text or "response time" in text):
            drivers.append("the brief states an explicit latency expectation")
        if metric == "security" and any(marker in text for marker in ("audit", "compliance", "pci", "hipaa", "gdpr", "soc2")):
            drivers.append("compliance and audit obligations shape the security posture")
        if metric in {"scalability", "performance"} and any(marker in text for marker in ("realtime", "real-time", "stream", "telemetry", "sensor")):
            drivers.append("realtime or event-driven demand shapes the elasticity assessment")
        if metric == "availability" and ("99.99" in text or "four nines" in text):
            drivers.append("a strict availability target tests redundancy and failover")
        if not drivers:
            if scale == "high-scale":
                drivers.append("the confirmed high-scale brief rewards horizontal elasticity")
            elif scale == "unknown":
                drivers.append("unknown workload scale keeps the weighting neutral")
            else:
                drivers.append("the confirmed scale profile rewards controlled complexity")
        return (
            f"{architecture_name} scores {score}/10 for {metric.replace('_', ' ')} "
            f"({'lower is better' if metric_direction(metric) == 'minimize' else 'higher is better'}) because "
            f"{' and '.join(drivers)}."
        )

    def _strengths(self, architecture_id: str) -> list[str]:
        strength_map = {
            "modular-monolith": [
                "Fastest path to a cohesive first production release.",
                "Clear internal modularity without distributed system overhead.",
            ],
            "service-based": [
                "Coarse services isolate volatile capabilities without microservices overhead.",
                "Allows independent scaling of hotspots while keeping data governance simple.",
            ],
            "event-driven-microservices": [
                "Strong isolation across bounded contexts and workloads.",
                "Natural fit for asynchronous regeneration and scaling hotspots.",
            ],
            "serverless-platform": [
                "Elastic infrastructure with lower steady-state ops load.",
                "Good balance between scale handling and platform team size.",
            ],
            "hybrid-modular-serverless": [
                "Keeps transactional core simple while scaling variable slices elastically.",
                "Lets small teams adopt serverless selectively with tracked usage cost.",
            ],
            "hybrid-event-serverless": [
                "Stable services plus elastic event consumers for variable reactions.",
                "Preserves replay and independent consumer evolution with fewer services.",
            ],
        }
        return strength_map.get(architecture_id, [
            "Balanced trade-offs across delivery speed and operational control.",
            "Clear component boundaries with governed contracts.",
        ])

    def _risks(self, architecture_id: str) -> list[str]:
        risk_map = {
            "modular-monolith": [
                "Requires team discipline to avoid tight coupling over time.",
                "May need later decomposition if traffic or team size grows sharply.",
            ],
            "service-based": [
                "Shared data governance can drift into coupling without contract discipline.",
                "A handful of deployables still needs service-level observability.",
            ],
            "event-driven-microservices": [
                "Operational load is high for early-stage teams.",
                "Distributed tracing and contract governance become mandatory quickly.",
            ],
            "serverless-platform": [
                "Vendor-specific tooling may influence long-term portability.",
                "Workflow observability needs deliberate investment.",
            ],
            "hybrid-modular-serverless": [
                "Core-edge contracts need idempotency, retries, and shared tracing.",
                "Two operational models can confuse ownership without clear runbooks.",
            ],
            "hybrid-event-serverless": [
                "Event contracts and consumer idempotency span two compute models.",
                "Retry storms and cold starts need explicit budgets and alerts.",
            ],
        }
        return risk_map.get(architecture_id, [
            "Contract governance becomes mandatory as ownership splits.",
            "Observability must cover every independently scaled boundary.",
        ])


def recompute_with_weights(
    matrix: dict[str, dict[str, int]],
    criteria_weights: CriteriaWeights,
) -> list[ArchitectureScorecard]:
    """Re-rank architectures using user-specified criterion weights.

    This is a pure computation with no LLM involvement — it takes the
    existing score matrix and applies a weighted sum, normalised by the
    sum of active weights so the total_score stays on the 0-10 scale.

    Called on every slider drag in the What-If Playground, so it must
    be fast and side-effect free.
    """
    active_weights = criteria_weights.weights
    weight_sum = sum(active_weights.values()) or 1.0

    scorecards: list[ArchitectureScorecard] = []
    for arch_name, scores in matrix.items():
        weighted_total = sum(
            metric_utility(metric, scores.get(metric, 5))
            * active_weights.get(metric, 1.0)
            for metric in METRICS
        )
        exact_total_score = weighted_total / weight_sum
        total_score = round(exact_total_score, 1)
        metric_scores = [
            MetricScore(
                metric=metric,
                score=scores.get(metric, 0),
                direction=metric_direction(metric),  # type: ignore[arg-type]
                normalized_score=metric_utility(metric, scores.get(metric, 5)),
                explanation=(
                    f"Score {scores.get(metric, 0)}/10 for {metric.replace('_', ' ')}; "
                    f"{metric_direction(metric)} this metric."
                ),
            )
            for metric in METRICS
        ]
        scorecards.append(
            ArchitectureScorecard(
                architecture_id=arch_name,
                architecture_name=arch_name.replace("-", " ").title(),
                overall_score=total_score,
                weighted_score=round(total_score * 10, 1),
                ranking_score=exact_total_score * 10,
                metric_scores=metric_scores,
                strengths=[],
                risks=[],
                decision_model=ARCHITECTURE_DECISION_MODEL_VERSION,
            )
        )

    scorecards.sort(
        key=lambda item: (
            -(item.ranking_score if item.ranking_score is not None else item.weighted_score),
            item.architecture_id,
        )
    )
    return scorecards
