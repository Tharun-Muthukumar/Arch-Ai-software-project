"""Stateless deterministic endpoints for team fit and public precedents."""

from fastapi import APIRouter

from app.schemas.domain import (
    ConwayFitRequest,
    ConwayFitResult,
    RequirementAnalysis,
    TwinMatch,
    TwinMatchRequest,
)
from app.services.conway_law_engine import check_fit
from app.services.twin_matching_engine import match_twins

router = APIRouter(tags=["architecture-insights"])


@router.post("/conway-fit", response_model=ConwayFitResult)
def conway_fit(payload: ConwayFitRequest) -> ConwayFitResult:
    """Check architecture and team boundary fit using deterministic rules."""
    return check_fit(
        architecture=payload.architecture,
        analysis=RequirementAnalysis(detected_entities=payload.entities),
        constraints=payload.constraints,
        bounded_contexts=payload.bounded_contexts,
    )


@router.post("/twin-match", response_model=list[TwinMatch])
def twin_match(payload: TwinMatchRequest) -> list[TwinMatch]:
    """Return the closest public architecture precedents without LLM calls."""
    return match_twins(
        comparison_matrix=payload.comparison_matrix,
        recommended_architecture_id=payload.recommended_architecture_id,
        deployment_stack=payload.deployment_stack,
        weights=payload.weights,
        domain=payload.domain,
        domain_signals=payload.domain_signals,
        capability_signals=payload.capability_signals,
        workload_signals=payload.workload_signals,
        data_signals=payload.data_signals,
        reliability_signals=payload.reliability_signals,
        integration_signals=payload.integration_signals,
        project_profile=payload.project_profile,
        similarity_weights=payload.similarity_weights,
    )
