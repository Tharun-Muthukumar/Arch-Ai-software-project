from app.models.account import Conversation, ConversationMessage, ConversationShare, User
from app.repositories.account_repository import AccountRepository
from app.schemas.account import (
    ConversationDetail,
    ConversationMessageResponse,
    ConversationShareResponse,
    ConversationSummary,
    UserLookup,
)
from app.schemas.domain import WorkspaceResponse


class HistoryService:
    def __init__(self, repository: AccountRepository) -> None:
        self.repository = repository

    def create_for_workspace(
        self,
        owner: User,
        workspace: WorkspaceResponse,
        prompt: str,
    ) -> Conversation:
        preview_source = workspace.requirements.summary or prompt
        conversation = Conversation(
            owner_id=owner.id,
            workspace_id=workspace.id,
            title=workspace.title[:160],
            preview=self._preview(preview_source),
            messages=[
                ConversationMessage(role="user", content=prompt),
                ConversationMessage(
                    role="assistant",
                    content=(
                        f"Generated {len(workspace.architectures)} architecture options for "
                        f"{workspace.requirements.domain}. Recommended: "
                        f"{workspace.recommendation.recommended_architecture_name}."
                    ),
                    result_reference=workspace.id,
                ),
            ],
        )
        return self.repository.add_conversation(conversation)

    def record_exchange(
        self,
        workspace_id: str,
        user_content: str,
        assistant_content: str,
    ) -> None:
        conversation = self.repository.get_conversation_by_workspace(workspace_id)
        if conversation is None:
            return
        self.repository.add_message(
            ConversationMessage(
                conversation_id=conversation.id,
                role="user",
                content=user_content,
            )
        )
        self.repository.add_message(
            ConversationMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=assistant_content,
                result_reference=workspace_id,
            )
        )

    def permission_for(self, conversation: Conversation, user: User | None) -> str | None:
        if user is None:
            return None
        if conversation.owner_id == user.id:
            return "OWNER"
        if any(share.recipient_id == user.id for share in conversation.shares):
            return "VIEW"
        return None

    def workspace_permission(self, workspace_id: str, user: User | None) -> str | None:
        conversation = self.repository.get_conversation_by_workspace(workspace_id)
        if conversation is None:
            return "LEGACY"
        return self.permission_for(conversation, user)

    def filter_workspace_ids(self, workspace_ids: list[str], user: User | None) -> set[str]:
        protected_ids = self.repository.all_protected_workspace_ids()
        visible_ids = set(workspace_ids) - protected_ids
        if user is not None:
            visible_ids.update(self.repository.accessible_workspace_ids(user.id))
        return visible_ids

    def list_for_user(self, user: User) -> list[ConversationSummary]:
        return [
            self.to_summary(conversation, user)
            for conversation in self.repository.list_conversations(user.id)
        ]

    def to_summary(self, conversation: Conversation, user: User) -> ConversationSummary:
        permission = self.permission_for(conversation, user)
        if permission not in {"OWNER", "VIEW"}:
            raise PermissionError("Conversation is not accessible")
        return ConversationSummary(
            id=conversation.id,
            workspace_id=conversation.workspace_id,
            title=conversation.title,
            preview=conversation.preview,
            owner=self._user_lookup(conversation.owner),
            permission=permission,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )

    def to_detail(
        self,
        conversation: Conversation,
        user: User,
        workspace: WorkspaceResponse,
    ) -> ConversationDetail:
        summary = self.to_summary(conversation, user)
        shares = (
            [
                ConversationShareResponse(
                    recipient=self._user_lookup(share.recipient),
                    permission="VIEW",
                    created_at=share.created_at,
                )
                for share in conversation.shares
            ]
            if summary.permission == "OWNER"
            else []
        )
        return ConversationDetail(
            **summary.model_dump(),
            messages=[
                ConversationMessageResponse(
                    id=message.id,
                    role=message.role,
                    content=message.content,
                    result_reference=message.result_reference,
                    created_at=message.created_at,
                )
                for message in conversation.messages
            ],
            shares=shares,
            workspace=workspace,
        )

    def share_with(
        self,
        conversation: Conversation,
        recipient: User,
    ) -> ConversationShare:
        existing = self.repository.get_share(conversation.id, recipient.id)
        if existing is not None:
            return existing
        return self.repository.add_share(
            ConversationShare(
                conversation_id=conversation.id,
                recipient_id=recipient.id,
                permission="VIEW",
            )
        )

    @staticmethod
    def _user_lookup(user: User) -> UserLookup:
        return UserLookup(id=user.id, username=user.username, email=user.email)

    @staticmethod
    def _preview(value: str) -> str:
        compact = " ".join(value.split())
        return compact if len(compact) <= 280 else f"{compact[:277]}..."
