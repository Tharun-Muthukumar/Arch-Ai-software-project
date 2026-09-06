from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import get_account_repository, require_current_user
from app.api.routes.workspaces import get_orchestrator
from app.models.account import User
from app.repositories.account_repository import AccountRepository
from app.schemas.account import (
    ConversationDetail,
    ConversationShareResponse,
    ConversationSummary,
    ConversationUpdateRequest,
    ShareConversationRequest,
    UserLookup,
)
from app.services.history_service import HistoryService
from app.services.workspace_orchestrator import WorkspaceOrchestrator


router = APIRouter(prefix="/history", tags=["history"])


def get_history_service(
    repository: AccountRepository = Depends(get_account_repository),
) -> HistoryService:
    return HistoryService(repository)


def require_accessible_conversation(
    conversation_id: str,
    user: User,
    repository: AccountRepository,
    history_service: HistoryService,
):
    conversation = repository.get_conversation(conversation_id)
    if conversation is None or history_service.permission_for(conversation, user) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.get("", response_model=list[ConversationSummary])
def list_history(
    user: User = Depends(require_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> list[ConversationSummary]:
    return history_service.list_for_user(user)


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_history_item(
    conversation_id: str,
    user: User = Depends(require_current_user),
    repository: AccountRepository = Depends(get_account_repository),
    history_service: HistoryService = Depends(get_history_service),
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
) -> ConversationDetail:
    conversation = require_accessible_conversation(
        conversation_id, user, repository, history_service
    )
    workspace = orchestrator.get_workspace(conversation.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Conversation result not found")
    return history_service.to_detail(conversation, user, workspace)


@router.patch("/{conversation_id}", response_model=ConversationSummary)
def update_history_item(
    conversation_id: str,
    payload: ConversationUpdateRequest,
    user: User = Depends(require_current_user),
    repository: AccountRepository = Depends(get_account_repository),
    history_service: HistoryService = Depends(get_history_service),
) -> ConversationSummary:
    conversation = require_accessible_conversation(
        conversation_id, user, repository, history_service
    )
    if conversation.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can edit this conversation")
    conversation.title = payload.title
    updated = repository.save_conversation(conversation)
    return history_service.to_summary(updated, user)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_history_item(
    conversation_id: str,
    user: User = Depends(require_current_user),
    repository: AccountRepository = Depends(get_account_repository),
    history_service: HistoryService = Depends(get_history_service),
) -> None:
    conversation = require_accessible_conversation(
        conversation_id, user, repository, history_service
    )
    if conversation.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can delete this conversation")
    repository.delete_conversation(conversation)


@router.post(
    "/{conversation_id}/shares",
    response_model=ConversationShareResponse,
    status_code=status.HTTP_201_CREATED,
)
def share_history_item(
    conversation_id: str,
    payload: ShareConversationRequest,
    user: User = Depends(require_current_user),
    repository: AccountRepository = Depends(get_account_repository),
    history_service: HistoryService = Depends(get_history_service),
) -> ConversationShareResponse:
    conversation = require_accessible_conversation(
        conversation_id, user, repository, history_service
    )
    if conversation.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can share this conversation")
    recipient = repository.get_user(payload.recipient_id)
    if recipient is None:
        raise HTTPException(status_code=404, detail="Recipient not found")
    if recipient.id == user.id:
        raise HTTPException(status_code=400, detail="A conversation is already available to its owner")
    share = history_service.share_with(conversation, recipient)
    return ConversationShareResponse(
        recipient=UserLookup(
            id=recipient.id,
            username=recipient.username,
            email=recipient.email,
        ),
        permission="VIEW",
        created_at=share.created_at,
    )


@router.delete(
    "/{conversation_id}/shares/{recipient_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_history_share(
    conversation_id: str,
    recipient_id: str,
    user: User = Depends(require_current_user),
    repository: AccountRepository = Depends(get_account_repository),
    history_service: HistoryService = Depends(get_history_service),
) -> None:
    conversation = require_accessible_conversation(
        conversation_id, user, repository, history_service
    )
    if conversation.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can revoke sharing")
    share = repository.get_share(conversation.id, recipient_id)
    if share is None:
        raise HTTPException(status_code=404, detail="Share not found")
    repository.delete_share(share)
