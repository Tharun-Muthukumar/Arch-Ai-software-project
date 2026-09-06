import re

from app.schemas.domain import (
    ArchitectureOption,
    ArchitectureScorecard,
    ComparisonResult,
    CriteriaWeights,
    MetricScore,
    RequirementModel,
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

BASE_PROFILES = {
    "modular-monolith": {
        "scalability": 7,
        "performance": 8,
        "maintainability": 8,
        "security": 8,
        "cost": 9,
        "reliability": 8,
        "availability": 7,
        "deployment_complexity": 9,
        "learning_curve": 9,
        "development_time": 9,
        "fault_isolation": 6,
        "operational_complexity": 9,
    },
    "event-driven-microservices": {
        "scalability": 9,
        "performance": 8,
        "maintainability": 7,
        "security": 8,
        "cost": 4,
        "reliability": 8,
        "availability": 9,
        "deployment_complexity": 4,
        "learning_curve": 4,
        "development_time": 5,
        "fault_isolation": 9,
        "operational_complexity": 4,
    },
    "serverless-platform": {
        "scalability": 8,
        "performance": 7,
        "maintainability": 7,
        "security": 8,
        "cost": 7,
        "reliability": 8,
        "availability": 8,
        "deployment_complexity": 7,
        "learning_curve": 6,
        "development_time": 7,
        "fault_isolation": 7,
        "operational_complexity": 7,
    },
}


class ComparisonEngine:
    def compare(
        self,
        requirements: RequirementModel,
        architectures: list[ArchitectureOption],
        answers: dict[str, str] | None = None,
    ) -> ComparisonResult:
        weights = self._build_weights(requirements)
        scorecards: list[ArchitectureScorecard] = []

        for architecture in architectures:
            profile = BASE_PROFILES[architecture.id].copy()
            profile = self._apply_adjustments(profile, architecture.id, requirements, answers or {})
            metric_scores = [
                MetricScore(
                    metric=metric,
                    score=profile[metric],
                    explanation=self._explain(metric, profile[metric], architecture.name, requirements),
                )
                for metric in METRICS
            ]
            overall_score = round(
                sum(item.score for item in metric_scores) / max(len(metric_scores), 1), 1
            )
            weighted_score = round(
                sum(profile[metric] * weights[metric] for metric in METRICS) * 10, 1
            )
            scorecards.append(
                ArchitectureScorecard(
                    architecture_id=architecture.id,
                    architecture_name=architecture.name,
                    overall_score=overall_score,
                    weighted_score=weighted_score,
                    metric_scores=metric_scores,
                    strengths=self._strengths(architecture.id),
                    risks=self._risks(architecture.id),
                )
            )

        scale_reasoning = (
            f"The `{requirements.scale_profile}` profile adjusts scalability, reliability, and availability weights."
            if requirements.scale_profile != "unknown"
            else "Workload scale is unknown, so scale-sensitive weights remain neutral."
        )
        reasoning = [
            "Scores are rule-based and derived from confirmed requirements and the available operational context.",
            scale_reasoning,
            "Cost and complexity metrics favor simpler deployment topologies when the brief does not justify distributed systems overhead.",
        ]

        return ComparisonResult(weights=weights, scorecards=scorecards, reasoning=reasoning)

    def _build_weights(self, requirements: RequirementModel) -> dict[str, float]:
        weights = {
            "scalability": 0.12,
            "performance": 0.09,
            "maintainability": 0.1,
            "security": 0.1,
            "cost": 0.08,
            "reliability": 0.09,
            "availability": 0.08,
            "deployment_complexity": 0.08,
            "learning_curve": 0.06,
            "development_time": 0.08,
            "fault_isolation": 0.06,
            "operational_complexity": 0.06,
        }

        if requirements.scale_profile == "high-scale":
            weights["scalability"] += 0.05
            weights["availability"] += 0.03
            weights["reliability"] += 0.02
            weights["cost"] -= 0.02
            weights["development_time"] -= 0.02
        elif requirements.scale_profile == "startup-scale":
            weights["cost"] += 0.03
            weights["development_time"] += 0.03
            weights["deployment_complexity"] += 0.02
            weights["fault_isolation"] -= 0.02

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

        if requirements.scale_profile == "high-scale":
            if architecture_id == "event-driven-microservices":
                profile["scalability"] += 1
                profile["availability"] += 1
            if architecture_id == "modular-monolith":
                profile["scalability"] -= 2
                profile["availability"] -= 1
                profile["fault_isolation"] -= 1
            if architecture_id == "serverless-platform":
                profile["scalability"] += 1
        if any(marker in lower_requirements for marker in ("realtime", "real-time", "event processing")):
            if architecture_id == "event-driven-microservices":
                profile["scalability"] += 1
                profile["performance"] += 1
            elif architecture_id == "modular-monolith":
                profile["scalability"] -= 1
            elif architecture_id == "serverless-platform":
                profile["scalability"] += 1
        if any(marker in lower_requirements for marker in ("99.99", "four nines", "strict availability")):
            if architecture_id == "modular-monolith":
                profile["availability"] -= 2
                profile["fault_isolation"] -= 1
            else:
                profile["availability"] += 1
        latency_match = re.search(r"(?:latency|response time)[^\d]{0,20}(\d+)\s*ms", lower_requirements)
        if latency_match and int(latency_match.group(1)) <= 100:
            if architecture_id == "modular-monolith":
                profile["performance"] += 1
            else:
                profile["performance"] -= 1
        if "audit" in lower_requirements or "compliance" in lower_requirements:
            profile["security"] += 1
            if architecture_id == "serverless-platform":
                profile["learning_curve"] -= 1
        if answers.get("preferred_cloud", "").lower() in {"aws", "azure", "gcp"}:
            if architecture_id == "serverless-platform":
                profile["deployment_complexity"] += 1
                profile["cost"] += 1
        if answers.get("budget", "").lower() in {"low", "constrained", "startup"}:
            if architecture_id == "event-driven-microservices":
                profile["cost"] -= 2
                profile["development_time"] -= 1
            if architecture_id == "modular-monolith":
                profile["cost"] += 1
        regions = int(answers.get("geographic_regions", "0") or 0)
        if regions > 1:
            if architecture_id == "modular-monolith":
                profile["availability"] -= 1
                profile["deployment_complexity"] -= 2
            elif architecture_id == "event-driven-microservices":
                profile["availability"] += 1
            else:
                profile["availability"] += 1
                profile["deployment_complexity"] += 1
        team_size = int(answers.get("team_size", "0") or 0)
        if 0 < team_size <= 6:
            if architecture_id == "event-driven-microservices":
                profile["operational_complexity"] -= 2
                profile["deployment_complexity"] -= 1
                profile["learning_curve"] -= 1
                profile["development_time"] -= 1
            elif architecture_id == "modular-monolith":
                profile["operational_complexity"] += 1
                profile["development_time"] += 1
        return {metric: max(1, min(10, score)) for metric, score in profile.items()}

    def _explain(
        self,
        metric: str,
        score: int,
        architecture_name: str,
        requirements: RequirementModel,
    ) -> str:
        if requirements.scale_profile == "high-scale":
            scale_reason = "the confirmed high-scale brief rewards horizontal elasticity"
        elif requirements.scale_profile == "unknown":
            scale_reason = "unknown workload scale keeps the weighting neutral"
        else:
            scale_reason = "the confirmed scale profile rewards controlled complexity"
        return (
            f"{architecture_name} scores {score}/10 for {metric.replace('_', ' ')} because "
            f"{scale_reason} and this option balances that against delivery and operations trade-offs."
        )

    def _strengths(self, architecture_id: str) -> list[str]:
        strength_map = {
            "modular-monolith": [
                "Fastest path to a cohesive first production release.",
                "Clear internal modularity without distributed system overhead.",
            ],
            "event-driven-microservices": [
                "Strong isolation across bounded contexts and workloads.",
                "Natural fit for asynchronous regeneration and scaling hotspots.",
            ],
            "serverless-platform": [
                "Elastic infrastructure with lower steady-state ops load.",
                "Good balance between scale handling and platform team size.",
            ],
        }
        return strength_map[architecture_id]

    def _risks(self, architecture_id: str) -> list[str]:
        risk_map = {
            "modular-monolith": [
                "Requires team discipline to avoid tight coupling over time.",
                "May need later decomposition if traffic or team size grows sharply.",
            ],
            "event-driven-microservices": [
                "Operational load is high for early-stage teams.",
                "Distributed tracing and contract governance become mandatory quickly.",
            ],
            "serverless-platform": [
                "Vendor-specific tooling may influence long-term portability.",
                "Workflow observability needs deliberate investment.",
            ],
        }
        return risk_map[architecture_id]


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
            scores.get(metric, 0) * active_weights.get(metric, 1.0)
            for metric in METRICS
        )
        total_score = round(weighted_total / weight_sum, 1)
        metric_scores = [
            MetricScore(
                metric=metric,
                score=scores.get(metric, 0),
                explanation=f"Score {scores.get(metric, 0)}/10 for {metric.replace('_', ' ')}.",
            )
            for metric in METRICS
        ]
        scorecards.append(
            ArchitectureScorecard(
                architecture_id=arch_name,
                architecture_name=arch_name.replace("-", " ").title(),
                overall_score=total_score,
                weighted_score=round(weighted_total, 1),
                metric_scores=metric_scores,
                strengths=[],
                risks=[],
            )
        )

    scorecards.sort(key=lambda s: s.overall_score, reverse=True)
    return scorecards

