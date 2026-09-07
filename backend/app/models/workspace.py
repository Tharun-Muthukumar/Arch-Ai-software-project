import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(
        Text, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    original_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    business_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    answers_json: Mapped[dict] = mapped_column(JSON, default=dict)
    requirements_json: Mapped[dict] = mapped_column(JSON, default=dict)
    clarification_json: Mapped[dict] = mapped_column(JSON, default=dict)
    architectures_json: Mapped[list] = mapped_column(JSON, default=list)
    comparison_json: Mapped[dict] = mapped_column(JSON, default=dict)
    recommendation_json: Mapped[dict] = mapped_column(JSON, default=dict)
    diagrams_json: Mapped[dict] = mapped_column(JSON, default=dict)
    database_design_json: Mapped[dict] = mapped_column(JSON, default=dict)
    api_design_json: Mapped[dict] = mapped_column(JSON, default=dict)
    deployment_plan_json: Mapped[dict] = mapped_column(JSON, default=dict)
    causal_graph_json: Mapped[dict] = mapped_column(JSON, default=dict)
    adrs_json: Mapped[list] = mapped_column(JSON, default=list)
    diagram_layouts_json: Mapped[dict] = mapped_column(JSON, default=dict)
    edit_history_json: Mapped[dict] = mapped_column(JSON, default=dict)
    documentation_markdown: Mapped[str] = mapped_column(Text, default="")
    impact_history_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

