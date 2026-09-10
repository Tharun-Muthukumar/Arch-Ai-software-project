import re

from app.schemas.domain import (
    ArchitectureOption,
    ComparisonResult,
    RecommendationResult,
    RequirementModel,
)
from app.services.decision_config import (
    RECOMMENDATION_EXACT_TIE_EPSILON,
    RECOMMENDATION_NEAR_TIE_MARGIN,
    metric_utility,
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
        ranked = sorted(
            comparison.scorecards,
            key=lambda item: (-(item.ranking_score if item.ranking_score is not None else item.weighted_score), item.architecture_id),
        )
        best_scorecard = ranked[0]
        runner_up = ranked[1] if len(ranked) > 1 else None
        margin = (
            (best_scorecard.ranking_score if best_scorecard.ranking_score is not None else best_scorecard.weighted_score)
            - (runner_up.ranking_score if runner_up.ranking_score is not None else runner_up.weighted_score)
            if runner_up else None
        )
        architecture_lookup = {architecture.id: architecture for architecture in architectures}
        best_architecture = architecture_lookup[best_scorecard.architecture_id]

        scale_reason = (
            f"It fits the confirmed `{requirements.scale_profile}` profile."
            if requirements.scale_profile != "unknown"
            else "Workload scale is still unknown, so the recommendation favors reversible decisions and controlled complexity."
        )
        ranking_reason = (
            f"{best_architecture.name} and {runner_up.architecture_name} are tied at the displayed precision; "
            "the stable architecture ID tie-breaker selected the recommendation."
            if runner_up and margin is not None and abs(margin) <= RECOMMENDATION_EXACT_TIE_EPSILON
            else f"{best_architecture.name} narrowly leads {runner_up.architecture_name}; treat the result as a near tie, not a decisive win."
            if runner_up and margin is not None and margin <= RECOMMENDATION_NEAR_TIE_MARGIN
            else f"{best_architecture.name} has the strongest weighted trade-off balance."
        )
        why = [
            f"{ranking_reason} {scale_reason}",
            "The comparison uses confirmed requirement signals and neutral weights for missing information.",
            self._evidence_line(requirements, answers, comparison, best_scorecard.architecture_id),
            "The design can evolve after the open architecture questions are answered.",
        ]

        why_not: dict[str, list[str]] = {}
        for scorecard in comparison.scorecards:
            if scorecard.architecture_id == best_scorecard.architecture_id:
                continue
            score_gap = (
                (best_scorecard.ranking_score if best_scorecard.ranking_score is not None else best_scorecard.weighted_score)
                - (scorecard.ranking_score if scorecard.ranking_score is not None else scorecard.weighted_score)
            )
            comparison_text = (
                f"Weighted scores are effectively tied ({best_scorecard.weighted_score} vs {scorecard.weighted_score}); stable ID order breaks the tie."
                if abs(score_gap) <= RECOMMENDATION_EXACT_TIE_EPSILON
                else f"Weighted score {scorecard.weighted_score} trails by only {score_gap:.2f} points, so this remains a credible alternative."
                if score_gap <= RECOMMENDATION_NEAR_TIE_MARGIN
                else f"Weighted score {scorecard.weighted_score} is lower than {best_scorecard.weighted_score}."
            )
            why_not[scorecard.architecture_name] = [
                comparison_text,
                scorecard.risks[0],
                "The trade-offs are less favorable for the current workload and operational maturity.",
            ]

        rollout_plan = [
            "Start with the recommended architecture and establish module boundaries plus API contracts early.",
            "Instrument critical flows with logs, metrics, and audit traces before scaling out.",
            "Use the impact-aware regeneration workflow to evolve only affected artifacts as requirements change.",
        ]

        # Confidence reflects how strongly the inputs support the pick:
        # explicit scale/team answers and few open questions raise it. Unknown
        # scale alone no longer forces Low when the brief is otherwise rich:
        # Low requires either many open questions or unknown scale combined
        # with several unresolved items.
        team_known = bool(re.search(r"\d+", str(answers.get("team_size", "") or "")))
        open_count = len(requirements.open_questions)
        confirmed_inputs = sum([
            bool(requirements.functional_requirements),
            bool(requirements.domain_entities),
            bool(requirements.domain_workflows),
            bool(requirements.actors),
            1 if team_known else 0,
            1 if requirements.scale_profile != "unknown" else 0,
        ])
        if open_count >= 6 or (requirements.scale_profile == "unknown" and open_count >= 5):
            confidence = "Low"
        elif (
            best_scorecard.weighted_score >= 74
            and team_known
            and open_count < 4
            and confirmed_inputs >= 4
        ):
            confidence = "High"
        else:
            confidence = "Medium"

        return RecommendationResult(
            recommended_architecture_id=best_architecture.id,
            recommended_architecture_name=best_architecture.name,
            decision_summary=(
                f"{best_architecture.name} is the current recommendation. {ranking_reason} "
                "The ranking uses the same direction-aware weighted score shown in the comparison, "
                "and should be revisited when unresolved constraints are answered."
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
        # Use the same ranking key as the scorecard sort (ranking_score with
        # stable architecture_id tie-break) so the named runner-up can never
        # contradict the displayed ranking.
        ranked_others = sorted(
            others,
            key=lambda item: (-(item.ranking_score if item.ranking_score is not None else item.weighted_score), item.architecture_id),
        )
        runner_up = ranked_others[0] if ranked_others else None
        score_gap = (
            (best.ranking_score if best.ranking_score is not None else best.weighted_score)
            - (runner_up.ranking_score if runner_up.ranking_score is not None else runner_up.weighted_score)
            if runner_up else None
        )
        margin = (
            f"tied with {runner_up.architecture_name}; stable architecture ID order is the tie-breaker"
            if runner_up is not None and score_gap is not None and abs(score_gap) <= RECOMMENDATION_EXACT_TIE_EPSILON
            else f"by {score_gap:.2f} points over {runner_up.architecture_name} (a near tie)"
            if runner_up is not None and score_gap is not None and score_gap <= RECOMMENDATION_NEAR_TIE_MARGIN
            else f"by {score_gap:.2f} points over {runner_up.architecture_name}"
            if runner_up is not None
            else "as the only shortlisted option"
        )
        best_metrics = {
            item.metric: item.normalized_score
            if item.normalized_score is not None
            else metric_utility(item.metric, item.score)
            for item in best.metric_scores
        }
        deltas: list[tuple[str, float]] = []
        for other in others:
            other_metrics = {
                item.metric: item.normalized_score
                if item.normalized_score is not None
                else metric_utility(item.metric, item.score)
                for item in other.metric_scores
            }
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
            top_wins.append(f"{metric.replace('_', ' ')} (+{delta:g} utility)")
            if len(top_wins) == 2:
                break
        wins_clause = (
            f"Largest metric advantages: {', '.join(top_wins)}."
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
