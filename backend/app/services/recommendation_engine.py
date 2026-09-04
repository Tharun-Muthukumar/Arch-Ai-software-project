from app.schemas.domain import (
    ArchitectureOption,
    ComparisonResult,
    RecommendationResult,
    RequirementModel,
)


class RecommendationEngine:
    def recommend(
        self,
        requirements: RequirementModel,
        architectures: list[ArchitectureOption],
        comparison: ComparisonResult,
    ) -> RecommendationResult:
        best_scorecard = max(comparison.scorecards, key=lambda item: item.weighted_score)
        architecture_lookup = {architecture.id: architecture for architecture in architectures}
        best_architecture = architecture_lookup[best_scorecard.architecture_id]

        scale_reason = (
            f"It fits the confirmed `{requirements.scale_profile}` profile."
            if requirements.scale_profile != "unknown"
            else "Workload scale is still unknown, so the recommendation favors reversible decisions and controlled complexity."
        )
        why = [
            f"{best_architecture.name} has the strongest weighted trade-off balance. {scale_reason}",
            "The comparison uses confirmed requirement signals and neutral weights for missing information.",
            "The design can evolve after the open architecture questions are answered.",
        ]

        why_not: dict[str, list[str]] = {}
        for scorecard in comparison.scorecards:
            if scorecard.architecture_id == best_scorecard.architecture_id:
                continue
            why_not[scorecard.architecture_name] = [
                f"Weighted score {scorecard.weighted_score} is lower than {best_scorecard.weighted_score}.",
                scorecard.risks[0],
                "The trade-offs are less favorable for the current brief's budget and operational maturity.",
            ]

        rollout_plan = [
            "Start with the recommended architecture and establish module boundaries plus API contracts early.",
            "Instrument critical flows with logs, metrics, and audit traces before scaling out.",
            "Use the impact-aware regeneration workflow to evolve only affected artifacts as requirements change.",
        ]

        if requirements.open_questions or requirements.scale_profile == "unknown":
            confidence = "Low"
        else:
            confidence = "High" if best_scorecard.weighted_score >= 76 else "Medium"

        return RecommendationResult(
            recommended_architecture_id=best_architecture.id,
            recommended_architecture_name=best_architecture.name,
            decision_summary=(
                f"{best_architecture.name} is the best-fit architecture for this brief because it offers "
                "the strongest current balance between implementation complexity and maintainable operations. "
                "This recommendation must be revisited when unresolved constraints are answered."
            ),
            why=why,
            why_not=why_not,
            rollout_plan=rollout_plan,
            confidence=confidence,
        )

