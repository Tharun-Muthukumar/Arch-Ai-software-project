import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_account_repository, get_db, get_optional_current_user
from app.models.account import User
from app.repositories.account_repository import AccountRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.domain import (
    ArchitectureChatApplyRequest,
    ArchitectureChatRequest,
    ArchitectureChatResponse,
    ArchitectureRiskAnalysis,
    ArchitectureRiskRequest,
    CausalGraph,
    CausalGraphTrace,
    ChangeRequest,
    ClarificationAnswerRequest,
    CounterfactualSimulationRequest,
    CounterfactualSimulationResult,
    ProjectDescriptionAnalyzeRequest,
    WorkspaceEditPreview,
    WorkspaceEditRequest,
    WorkspaceMutationResponse,
    WorkspaceCreateRequest,
    WorkspaceResponse,
)
from app.services.workspace_orchestrator import WorkspaceOrchestrator
from app.services.counterfactual_simulator import CounterfactualSimulator
from app.services.history_service import HistoryService
from app.services.generation_runtime import GENERATION_TELEMETRY
from app.services.project_description_analyzer import (
    ProjectDescriptionAnalysisError,
    ProjectDescriptionAnalyzer,
)
from app.services.architecture_assistant import ArchitectureAssistantUnavailableError

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
logger = logging.getLogger(__name__)


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
    active_workspace_id: str | None = None,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> list[WorkspaceResponse]:
    workspaces = orchestrator.list_workspaces(active_workspace_id)
    visible_ids = history_service.filter_workspace_ids(
        [workspace.id for workspace in workspaces], user
    )
    return [workspace for workspace in workspaces if workspace.id in visible_ids]


@router.post("/analyze-description", response_model=WorkspaceCreateRequest)
def analyze_project_description(
    payload: ProjectDescriptionAnalyzeRequest,
) -> WorkspaceCreateRequest:
    try:
        return ProjectDescriptionAnalyzer().analyze(payload.prompt)
    except ProjectDescriptionAnalysisError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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


@router.post("/stream")
async def create_workspace_stream(
    payload: WorkspaceCreateRequest,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> StreamingResponse:
    """Generate a workspace while emitting each completed section over SSE."""
    project_id = str(uuid.uuid4())
    queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    user_id = user.id if user is not None else None

    def on_progress(_section: str, event: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, ("progress", event))

    async def run_generation() -> None:
        try:
            workspace = await asyncio.to_thread(
                orchestrator.create_workspace,
                payload,
                on_progress,
                project_id,
            )
            if user_id is not None and user is not None:
                await asyncio.to_thread(
                    history_service.create_for_workspace,
                    user,
                    workspace,
                    payload.description,
                )
            await queue.put(
                (
                    "complete",
                    {
                        "workspace": workspace.model_dump(mode="json"),
                        "metrics": GENERATION_TELEMETRY.snapshot(project_id),
                    },
                )
            )
        except Exception:
            logger.exception("Streaming workspace generation failed for %s", project_id)
            await queue.put(
                (
                    "error",
                    {
                        "message": "Workspace generation failed. Please try again.",
                        "project_id": project_id,
                    },
                )
            )

    async def event_stream():
        generation_task = asyncio.create_task(run_generation())
        try:
            while True:
                event_name, data = await queue.get()
                yield f"event: {event_name}\ndata: {json.dumps(data)}\n\n"
                if event_name in {"complete", "error"}:
                    break
        finally:
            # Generation writes a single coherent workspace. Let that safe,
            # scoped write finish even if the browser navigates away.
            if not generation_task.done():
                await asyncio.shield(generation_task)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


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


@router.post(
    "/{workspace_id}/architecture-chat",
    response_model=ArchitectureChatResponse,
)
def architecture_chat(
    workspace_id: str,
    payload: ArchitectureChatRequest,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> ArchitectureChatResponse:
    require_workspace_access(workspace_id, user, history_service)
    try:
        result = orchestrator.architecture_chat(workspace_id, payload)
    except ArchitectureAssistantUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if user is not None:
        assistant_message = (
            result.answer
            if result.type == "question"
            else f"Proposed, but did not apply: {result.proposal.summary if result.proposal else result.answer}"
        )
        history_service.record_exchange(workspace_id, payload.message, assistant_message)
    return result


@router.post(
    "/{workspace_id}/architecture-chat/apply",
    response_model=WorkspaceMutationResponse,
)
def apply_architecture_chat_proposal(
    workspace_id: str,
    payload: ArchitectureChatApplyRequest,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> WorkspaceMutationResponse:
    require_workspace_access(workspace_id, user, history_service, write=True)
    try:
        result = orchestrator.apply_architecture_proposal(workspace_id, payload.proposal)
    except ValueError as exc:
        status = 409 if "changed after you opened" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if user is not None:
        history_service.record_exchange(
            workspace_id,
            f"Apply proposal: {payload.proposal.request}",
            result.message,
        )
    return result


@router.post(
    "/{workspace_id}/risk-analysis",
    response_model=ArchitectureRiskAnalysis,
)
def analyze_architecture_risks(
    workspace_id: str,
    payload: ArchitectureRiskRequest,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> ArchitectureRiskAnalysis:
    require_workspace_access(workspace_id, user, history_service)
    try:
        result = orchestrator.analyze_architecture_risks(
            workspace_id,
            payload.architecture_id,
            include_ai=payload.include_ai,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return result


@router.get("/{workspace_id}/generation-metrics")
def get_generation_metrics(
    workspace_id: str,
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, user, history_service)
    metrics = GENERATION_TELEMETRY.snapshot(workspace_id)
    if metrics is None:
        raise HTTPException(status_code=404, detail="Generation metrics are unavailable")
    return metrics


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


@router.post(
    "/{workspace_id}/edits/preview",
    response_model=WorkspaceEditPreview,
)
def preview_workspace_edit(
    workspace_id: str,
    payload: WorkspaceEditRequest,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> WorkspaceEditPreview:
    require_workspace_access(workspace_id, user, history_service, write=True)
    try:
        preview = orchestrator.preview_edit(workspace_id, payload)
    except ValueError as exc:
        status = 409 if "changed after you opened" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    if preview is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return preview


@router.post(
    "/{workspace_id}/edits",
    response_model=WorkspaceMutationResponse,
)
def apply_workspace_edit(
    workspace_id: str,
    payload: WorkspaceEditRequest,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> WorkspaceMutationResponse:
    require_workspace_access(workspace_id, user, history_service, write=True)
    try:
        result = orchestrator.apply_workspace_edit(workspace_id, payload)
    except ValueError as exc:
        status = 409 if "changed after you opened" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if user is not None:
        history_service.record_exchange(
            workspace_id,
            f"Workspace edit: {payload.operation} {payload.target_type}",
            result.message,
        )
    return result


@router.post(
    "/{workspace_id}/edits/undo",
    response_model=WorkspaceMutationResponse,
)
def undo_workspace_edit(
    workspace_id: str,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> WorkspaceMutationResponse:
    require_workspace_access(workspace_id, user, history_service, write=True)
    try:
        result = orchestrator.undo_workspace_edit(workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return result


@router.post(
    "/{workspace_id}/edits/redo",
    response_model=WorkspaceMutationResponse,
)
def redo_workspace_edit(
    workspace_id: str,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
    user: User | None = Depends(get_optional_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> WorkspaceMutationResponse:
    require_workspace_access(workspace_id, user, history_service, write=True)
    try:
        result = orchestrator.redo_workspace_edit(workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return result


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
