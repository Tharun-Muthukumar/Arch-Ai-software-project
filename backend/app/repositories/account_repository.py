from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.account import (
    AuthSession,
    Conversation,
    ConversationMessage,
    ConversationShare,
    User,
    utc_now,
)
from app.models.workspace import Workspace


class AccountRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_user(self, user_id: str) -> User | None:
        return self.db.get(User, user_id)

    def get_user_by_username(self, username: str) -> User | None:
        return self.db.scalar(
            select(User).where(User.username_key == username.strip().casefold())
        )

    def get_user_by_email(self, email: str) -> User | None:
        return self.db.scalar(select(User).where(User.email_key == email.strip().casefold()))

    def get_user_by_identifier(self, identifier: str) -> User | None:
        key = identifier.strip().casefold()
        return self.db.scalar(
            select(User).where(or_(User.username_key == key, User.email_key == key))
        )

    def add_user(self, user: User) -> User:
        self.db.add(user)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise
        self.db.refresh(user)
        return user

    def save_user(self, user: User) -> User:
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def search_users(self, query: str, exclude_user_id: str) -> list[User]:
        key = query.strip().casefold()
        statement = (
            select(User)
            .where(
                User.id != exclude_user_id,
                or_(
                    User.username_key.contains(key),
                    User.email_key.contains(key),
                ),
            )
            .order_by(User.username_key)
            .limit(10)
        )
        return list(self.db.scalars(statement).all())

    def add_session(self, session: AuthSession) -> AuthSession:
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_session_by_hash(self, token_hash: str) -> AuthSession | None:
        return self.db.scalar(
            select(AuthSession)
            .options(selectinload(AuthSession.user))
            .where(AuthSession.token_hash == token_hash)
        )

    def delete_session_by_hash(self, token_hash: str) -> None:
        session = self.get_session_by_hash(token_hash)
        if session is not None:
            self.db.delete(session)
            self.db.commit()

    def add_conversation(self, conversation: Conversation) -> Conversation:
        self.db.add(conversation)
        self.db.commit()
        return self.get_conversation(conversation.id) or conversation

    def save_conversation(self, conversation: Conversation) -> Conversation:
        self.db.add(conversation)
        self.db.commit()
        return self.get_conversation(conversation.id) or conversation

    def delete_conversation(self, conversation: Conversation) -> None:
        workspace = self.db.get(Workspace, conversation.workspace_id)
        self.db.delete(conversation)
        if workspace is not None:
            self.db.delete(workspace)
        self.db.commit()

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        return self.db.scalar(
            select(Conversation)
            .options(
                selectinload(Conversation.owner),
                selectinload(Conversation.messages),
                selectinload(Conversation.shares).selectinload(ConversationShare.recipient),
            )
            .where(Conversation.id == conversation_id)
        )

    def get_conversation_by_workspace(self, workspace_id: str) -> Conversation | None:
        return self.db.scalar(
            select(Conversation)
            .options(selectinload(Conversation.shares))
            .where(Conversation.workspace_id == workspace_id)
        )

    def list_conversations(self, user_id: str) -> list[Conversation]:
        statement = (
            select(Conversation)
            .outerjoin(ConversationShare)
            .options(
                selectinload(Conversation.owner),
                selectinload(Conversation.shares),
            )
            .where(
                or_(
                    Conversation.owner_id == user_id,
                    ConversationShare.recipient_id == user_id,
                )
            )
            .distinct()
            .order_by(Conversation.updated_at.desc())
        )
        return list(self.db.scalars(statement).unique().all())

    def all_protected_workspace_ids(self) -> set[str]:
        return set(self.db.scalars(select(Conversation.workspace_id)).all())

    def accessible_workspace_ids(self, user_id: str) -> set[str]:
        statement = (
            select(Conversation.workspace_id)
            .outerjoin(ConversationShare)
            .where(
                or_(
                    Conversation.owner_id == user_id,
                    ConversationShare.recipient_id == user_id,
                )
            )
        )
        return set(self.db.scalars(statement).all())

    def add_message(self, message: ConversationMessage) -> ConversationMessage:
        timestamp = message.created_at or utc_now()
        message.created_at = timestamp
        self.db.add(message)
        conversation = self.db.get(Conversation, message.conversation_id)
        if conversation is not None:
            conversation.updated_at = timestamp
        self.db.commit()
        self.db.refresh(message)
        return message

    def get_share(self, conversation_id: str, recipient_id: str) -> ConversationShare | None:
        return self.db.scalar(
            select(ConversationShare).where(
                ConversationShare.conversation_id == conversation_id,
                ConversationShare.recipient_id == recipient_id,
            )
        )

    def add_share(self, share: ConversationShare) -> ConversationShare:
        self.db.add(share)
        self.db.commit()
        self.db.refresh(share)
        return share

    def delete_share(self, share: ConversationShare) -> None:
        self.db.delete(share)
        self.db.commit()
