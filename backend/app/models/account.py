from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        Text, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    username_key: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_key: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    received_shares: Mapped[list[ConversationShare]] = relationship(
        back_populates="recipient",
        cascade="all, delete-orphan",
        foreign_keys="ConversationShare.recipient_id",
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(
        Text, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped[User] = relationship(back_populates="sessions")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        Text, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    preview: Mapped[str] = mapped_column(String(280), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    owner: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list[ConversationMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.created_at",
    )
    shares: Mapped[list[ConversationShare]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(
        Text, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    result_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class ConversationShare(Base):
    __tablename__ = "conversation_shares"
    __table_args__ = (
        UniqueConstraint("conversation_id", "recipient_id", name="uq_conversation_recipient"),
    )

    id: Mapped[str] = mapped_column(
        Text, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipient_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission: Mapped[str] = mapped_column(String(16), nullable=False, default="VIEW")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    conversation: Mapped[Conversation] = relationship(back_populates="shares")
    recipient: Mapped[User] = relationship(
        back_populates="received_shares", foreign_keys=[recipient_id]
    )
