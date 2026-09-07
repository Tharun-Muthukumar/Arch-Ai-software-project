import re

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
        answers: dict[str, str] | None = None,
    ) -> RecommendationResult:
        answers = answers or {}
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
            self._evidence_line(requirements, answers, comparison, best_scorecard.architecture_id),
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

        # Confidence reflects how strongly the inputs support the pick:
        # explicit scale/team answers and few open questions raise it, while
        # unknown scale or many unresolved questions keep it low.
        team_known = bool(re.search(r"\d+", str(answers.get("team_size", "") or "")))
        open_count = len(requirements.open_questions)
        if requirements.scale_profile == "unknown" or open_count >= 5:
            confidence = "Low"
        elif (
            best_scorecard.weighted_score >= 76
            and team_known
            and open_count < 4
        ):
            confidence = "High"
        else:
            confidence = "Medium"

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

    @staticmethod
    def _evidence_line(
        requirements: RequirementModel,
        answers: dict[str, str],
        comparison: ComparisonResult,
        best_id: str,
    ) -> str:
        """Name the concrete inputs and metric wins behind the pick.

        This keeps the recommendation auditable: every claim here is derived
        from the stored scorecards and answers, never invented.
        """
        best = next(item for item in comparison.scorecards if item.architecture_id == best_id)
        others = [item for item in comparison.scorecards if item.architecture_id != best_id]
        runner_up = max(others, key=lambda item: item.weighted_score, default=None)
        margin = (
            f"by {round(best.weighted_score - runner_up.weighted_score, 1)} points over "
            f"{runner_up.architecture_name}"
            if runner_up is not None
            else "as the only shortlisted option"
        )
        best_metrics = {item.metric: item.score for item in best.metric_scores}
        deltas: list[tuple[str, int]] = []
        for other in others:
            other_metrics = {item.metric: item.score for item in other.metric_scores}
            for metric, score in best_metrics.items():
                deltas.append((metric, score - other_metrics.get(metric, score)))
        wins = sorted(
            [item for item in deltas if item[1] > 0],
            key=lambda item: (-item[1], item[0]),
        )
        seen: set[str] = set()
        top_wins: list[str] = []
        for metric, delta in wins:
            if metric in seen:
                continue
            seen.add(metric)
            top_wins.append(f"{metric.replace('_', ' ')} (+{delta})")
            if len(top_wins) == 2:
                break
        wins_clause = (
            f"Decisive metric wins: {', '.join(top_wins)}."
            if top_wins
            else "No single metric dominates; the win comes from the weighted blend."
        )
        team_match = re.search(r"\d+", str(answers.get("team_size", "") or ""))
        team_clause = (
            f"{team_match.group()}-person team"
            if team_match
            else "unspecified team size (5-person planning baseline)"
        )
        return (
            f"Evidence: {requirements.scale_profile} profile with {team_clause}; "
            f"weighted score {best.weighted_score} {margin}. {wins_clause}"
        )

