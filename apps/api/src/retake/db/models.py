"""SQLAlchemy models for the five tables in docs/ARCHITECTURE.md.

Invariants live in the database (constraints and indexes), not only in code.
Enums are stored as text with a CHECK constraint, ids are uuid4 (ADR-0003).
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Deterministic constraint names so Alembic can drop them again on downgrade.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _text_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Enum stored as VARCHAR + CHECK constraint instead of a Postgres ENUM type (ADR-0003)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )


# ---------------------------------------------------------------- enums


class TakeStatus(StrEnum):
    PENDING = "pending"
    GENERATING = "generating"
    DONE = "done"
    FAILED = "failed"


class FindingType(StrEnum):
    OMISSION = "omission"
    REPETITION = "repetition"
    SUBSTITUTION = "substitution"
    SILENCE = "silence"
    TRUNCATION = "truncation"


class FindingStatus(StrEnum):
    OPEN = "open"
    FIXED = "fixed"
    IGNORED = "ignored"


class LedgerKind(StrEnum):
    TTS = "tts"
    STT = "stt"
    RETRY_SKIPPED = "retry_skipped"


class LedgerStatus(StrEnum):
    PENDING = "pending"  # reserved before the API call, counts at the estimate
    DONE = "done"  # settled with the reported cost
    POSSIBLY_BILLED = "possibly_billed"  # sent, no response; counts at the estimate
    FAILED = "failed"  # nothing billed, counts zero


# ---------------------------------------------------------------- tables


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    voice_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    voice_settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    segments: Mapped[list["Segment"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Segment.position"
    )


class Segment(Base):
    __tablename__ = "segments"
    __table_args__ = (
        UniqueConstraint("project_id", "position"),  # stable position within a project (R2)
        CheckConstraint("position >= 0", name="position_nonnegative"),
        CheckConstraint("paragraph_index >= 0", name="paragraph_index_nonnegative"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    paragraph_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Bumped when the manuscript text of this segment changes; takes are bound to a version.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="segments")
    takes: Mapped[list["Take"]] = relationship(
        back_populates="segment", cascade="all, delete-orphan"
    )


class Take(Base):
    """One generated audio for one segment version.

    Invariant "exactly one active take per segment once any take is done":
    - at most one:      partial unique index ux_takes_one_active (below)
    - only a done one:  CHECK active_requires_done
    - at least one:     cannot be expressed as a constraint; the service activates the first
                        take that reaches DONE. Covered by a service test in week 7.
    """

    __tablename__ = "takes"
    __table_args__ = (
        # One row per attempt; a retried job for the same (segment, version, attempt) upserts
        # instead of inserting twice.
        UniqueConstraint("segment_id", "segment_version", "attempt"),
        Index("ux_takes_one_active", "segment_id", unique=True, postgresql_where=text("is_active")),
        CheckConstraint("NOT is_active OR status = 'done'", name="active_requires_done"),
        CheckConstraint("attempt >= 1", name="attempt_positive"),
        CheckConstraint("credits >= 0", name="credits_nonnegative"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="duration_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    segment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("segments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    segment_version: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[TakeStatus] = mapped_column(
        _text_enum(TakeStatus, "take_status"),
        nullable=False,
        default=TakeStatus.PENDING,
        server_default=TakeStatus.PENDING.value,
    )
    audio_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # ElevenLabs `request-id` header of the generation, for support and reconciliation.
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Denormalised cache of the matching ledger_entries.credits. The ledger is the source of
    # truth; this column exists so the review UI can show cost per take without a join.
    # Week 2 decides whether it stays.
    credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    segment: Mapped[Segment] = relationship(back_populates="takes")
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="take", cascade="all, delete-orphan"
    )


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (
        CheckConstraint("start_ms >= 0", name="start_nonnegative"),
        CheckConstraint("end_ms >= start_ms", name="end_after_start"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_unit_interval"),
        Index("ix_findings_take_id_status", "take_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    take_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("takes.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[FindingType] = mapped_column(
        _text_enum(FindingType, "finding_type"), nullable=False
    )
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    # 0..1; a probability, not money, so float is fine here.
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[FindingStatus] = mapped_column(
        _text_enum(FindingStatus, "finding_status"),
        nullable=False,
        default=FindingStatus.OPEN,
        server_default=FindingStatus.OPEN.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    take: Mapped[Take] = relationship(back_populates="findings")


class BudgetPeriod(Base):
    """One row per billing period (`YYYY-MM`). Exists to be locked: `reserve()` takes
    `SELECT ... FOR UPDATE` on it so budget check and insert are serialised per period."""

    __tablename__ = "budget_periods"

    period: Mapped[str] = mapped_column(String(7), primary_key=True)  # "2026-09"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class LedgerEntry(Base):
    """Source of truth for credits spent. Every ElevenLabs call writes one row (hard rule 2).

    idempotency_key = f"{kind}:{segment_id}:{segment_version}:{attempt}"; the UNIQUE
    constraint is what makes a duplicate job delivery harmless (R7).
    """

    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint("credits >= 0", name="credits_nonnegative"),
        CheckConstraint("estimated_credits >= 0", name="estimated_credits_nonnegative"),
        Index("ix_ledger_entries_project_id_created_at", "project_id", "created_at"),
        Index("ix_ledger_entries_period_status", "period", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # A take may be cleaned up later; the cost stays as a fact, hence SET NULL.
    take_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("takes.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[LedgerKind] = mapped_column(_text_enum(LedgerKind, "ledger_kind"), nullable=False)
    period: Mapped[str] = mapped_column(
        ForeignKey("budget_periods.period", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[LedgerStatus] = mapped_column(
        _text_enum(LedgerStatus, "ledger_status"),
        nullable=False,
        default=LedgerStatus.PENDING,
        server_default=LedgerStatus.PENDING.value,
    )
    # What we expected to pay (len(text)); kept next to the reported cost for comparison.
    estimated_credits: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # What the API reported (`character-cost`), or the estimate for possibly_billed.
    credits: Mapped[int] = mapped_column(Integer, nullable=False)  # integer, hard rule 7
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    project: Mapped[Project] = relationship()
    take: Mapped[Take | None] = relationship()
