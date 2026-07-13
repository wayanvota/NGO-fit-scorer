"""ORM models. The StrategyProfile carries the org's scoring strategy as data:
dimensions, hard filters, thresholds, and tiers are all editable rows, not code.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(16), default="staff")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Opportunity(Base):
    __tablename__ = "opportunities"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    submitted_by: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"))
    source_type: Mapped[str] = mapped_column(String(8))
    source_url: Mapped[str] = mapped_column(Text, default="")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(String(400), default="")
    parsed: Mapped[dict] = mapped_column(JSON, default=dict)
    parse_confidence: Mapped[str] = mapped_column(String(16), default="unknown")
    variables: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    scores = relationship("Score", back_populates="opportunity", cascade="all, delete-orphan")


class Score(Base):
    __tablename__ = "scores"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    opportunity_id: Mapped[str] = mapped_column(String(32), ForeignKey("opportunities.id"))
    profile_version: Mapped[int] = mapped_column(Integer)
    overall_score: Mapped[float] = mapped_column(Float)
    tier: Mapped[str] = mapped_column(String(32))
    dimension_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    hard_filter_result: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[str] = mapped_column(String(16), default="unknown")
    memo_markdown: Mapped[str] = mapped_column(Text, default="")
    model_used: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    opportunity = relationship("Opportunity", back_populates="scores")


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    score_id: Mapped[str] = mapped_column(String(32), ForeignKey("scores.id"))
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"))
    override_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    override_tier: Mapped[str] = mapped_column(String(32), default="")
    override_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    opportunity_id: Mapped[str] = mapped_column(String(32), ForeignKey("opportunities.id"))
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(16))
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Outcome(Base):
    __tablename__ = "outcomes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    opportunity_id: Mapped[str] = mapped_column(String(32), ForeignKey("opportunities.id"))
    outcome: Mapped[str] = mapped_column(String(16))
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_funding_type: Mapped[str] = mapped_column(String(32), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    resolved_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class StrategyProfile(Base):
    __tablename__ = "strategy_profiles"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    version: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    # Free-form org context the scorer is grounded in (mission, priorities, etc.).
    profile_doc: Mapped[dict] = mapped_column(JSON, default=dict)
    # Data-driven scoring dimensions: [{key,label,description,weight}], weights sum to 100.
    dimensions: Mapped[list] = mapped_column(JSON, default=list)
    # Data-driven knockouts: [{key,label,description,enabled}] (model-judged).
    hard_filters: Mapped[list] = mapped_column(JSON, default=list)
    thresholds: Mapped[dict] = mapped_column(JSON, default=dict)
    tiers: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(255), default="system")
    approved_by: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Recalibration(Base):
    __tablename__ = "recalibrations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    from_profile_version: Mapped[int] = mapped_column(Integer)
    proposed_profile: Mapped[dict] = mapped_column(JSON, default=dict)
    rationale: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    reviewed_by: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    actor: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
