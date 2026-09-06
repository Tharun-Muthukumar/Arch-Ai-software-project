import json

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import get_account_repository, get_db, get_optional_current_user
from app.models.account import User
from app.repositories.account_repository import AccountRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.domain import (
    CausalGraph,
    CausalGraphTrace,
    ChangeRequest,
    ClarificationAnswerRequest,
    CounterfactualSimulationRequest,
    CounterfactualSimulationResult,
    WorkspaceCreateRequest,
    WorkspaceResponse,
)
from app.services.workspace_orchestrator import WorkspaceOrchestrator
from app.services.counterfactual_simulator import CounterfactualSimulator
from app.services.history_service import HistoryService

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def get_orchestrator(db: Session = Depends(get_db)) -> WorkspaceOrchestrator:
    repository = WorkspaceRepository(db)
    return WorkspaceOrchestrator(repository)


def get_history_service(
    repository: AccountRepository = Depends(get_account_repository),
) -> HistoryService:
    return HistoryService(repository)


def require_workspace_access(
    workspace_id: str,
    user: User | None,
    history_service: HistoryService,
    *,
    write: bool = False,
) -> str:
    permission = history_service.workspace_permission(workspace_id, user)
    if permission is None:
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        raise HTTPException(status_code=404, detail="Workspace not found")
    if write and permission == "VIEW":
        raise HTTPException(status_code=403, detail="Shared conversations are read-only")
    return permission


@router.get("", response_model=list[WorkspaceResponse])
def list_workspaces(
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> list[WorkspaceResponse]:
    workspaces = orchestrator.list_workspaces()
    visible_ids = history_service.filter_workspace_ids(
        [workspace.id for workspace in workspaces], user
    )
    return [workspace for workspace in workspaces if workspace.id in visible_ids]


@router.post("", response_model=WorkspaceResponse, status_code=201)
def create_workspace(
    payload: WorkspaceCreateRequest,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> WorkspaceResponse:
    workspace = orchestrator.create_workspace(payload)
    if user is not None:
        history_service.create_for_workspace(user, workspace, payload.description)
    return workspace


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(
    workspace_id: str,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> WorkspaceResponse:
    require_workspace_access(workspace_id, user, history_service)
    workspace = orchestrator.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


@router.get("/{workspace_id}/causal-graph", response_model=CausalGraph)
def get_causal_graph(
    workspace_id: str,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> CausalGraph:
    require_workspace_access(workspace_id, user, history_service)
    graph = orchestrator.get_causal_graph(workspace_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return graph


@router.get(
    "/{workspace_id}/causal-graph/nodes/{node_id}",
    response_model=CausalGraphTrace,
)
def explain_causal_node(
    workspace_id: str,
    node_id: str,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> CausalGraphTrace:
    require_workspace_access(workspace_id, user, history_service)
    trace = orchestrator.explain_causal_node(workspace_id, node_id)
    if trace is None:
        workspace = orchestrator.get_workspace(workspace_id)
        detail = "Causal graph node not found" if workspace else "Workspace not found"
        raise HTTPException(status_code=404, detail=detail)
    return trace


@router.post("/{workspace_id}/clarifications", response_model=WorkspaceResponse)
def answer_clarifications(
    workspace_id: str,
    payload: ClarificationAnswerRequest,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> WorkspaceResponse:
    require_workspace_access(workspace_id, user, history_service, write=True)
    workspace = orchestrator.answer_clarifications(workspace_id, payload.answers)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if user is not None:
        history_service.record_exchange(
            workspace_id,
            f"Clarification answers: {json.dumps(payload.answers, sort_keys=True)}",
            "Updated the requirements and regenerated the affected architecture results.",
        )
    return workspace


@router.post("/{workspace_id}/changes", response_model=WorkspaceResponse)
def apply_change_request(
    workspace_id: str,
    payload: ChangeRequest,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> WorkspaceResponse:
    require_workspace_access(workspace_id, user, history_service, write=True)
    workspace = orchestrator.apply_change_request(workspace_id, payload.change_request)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if user is not None:
        history_service.record_exchange(
            workspace_id,
            payload.change_request,
            "Applied the change request and regenerated the impacted architecture artifacts.",
        )
    return workspace


@router.post(
    "/{workspace_id}/counterfactual/simulate",
    response_model=CounterfactualSimulationResult,
)
def simulate_counterfactual(
    workspace_id: str,
    payload: CounterfactualSimulationRequest,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> CounterfactualSimulationResult:
    require_workspace_access(workspace_id, user, history_service, write=True)
    workspace = orchestrator.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    result = CounterfactualSimulator().simulate(workspace, payload)
    if user is not None:
        user_content = payload.scenario or json.dumps(
            [change.model_dump() for change in payload.changes], sort_keys=True
        )
        history_service.record_exchange(
            workspace_id,
            user_content,
            (
                "Simulated the counterfactual. Recommended architecture: "
                f"{result.recommended_architecture_name}."
            ),
        )
    return result


@router.get("/{workspace_id}/documentation/markdown", response_class=PlainTextResponse)
def download_markdown(
    workspace_id: str,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> str:
    require_workspace_access(workspace_id, user, history_service)
    workspace = orchestrator.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace.documentation_markdown


@router.get("/{workspace_id}/documentation/pdf")
def download_pdf(
    workspace_id: str,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> Response:
    require_workspace_access(workspace_id, user, history_service)
    pdf_bytes = orchestrator.export_pdf(workspace_id)
    if pdf_bytes is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="archai-{workspace_id}.pdf"'
        },
    )

