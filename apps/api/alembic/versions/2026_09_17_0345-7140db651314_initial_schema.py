"""initial schema

Revision ID: 7140db651314
Revises:
Create Date: 2026-09-17 03:45:34.181492

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7140db651314"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("voice_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column(
            "voice_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
    )
    op.create_table(
        "segments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("paragraph_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "paragraph_index >= 0", name=op.f("ck_segments_paragraph_index_nonnegative")
        ),
        sa.CheckConstraint("position >= 0", name=op.f("ck_segments_position_nonnegative")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_segments_version_positive")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_segments_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_segments")),
        sa.UniqueConstraint("project_id", "position", name=op.f("uq_segments_project_id_position")),
    )
    op.create_index(op.f("ix_segments_project_id"), "segments", ["project_id"], unique=False)
    op.create_table(
        "takes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("segment_id", sa.Uuid(), nullable=False),
        sa.Column("segment_version", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "generating",
                "done",
                "failed",
                name="take_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("audio_key", sa.String(length=255), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("credits", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "NOT is_active OR status = 'done'", name=op.f("ck_takes_active_requires_done")
        ),
        sa.CheckConstraint("attempt >= 1", name=op.f("ck_takes_attempt_positive")),
        sa.CheckConstraint("credits >= 0", name=op.f("ck_takes_credits_nonnegative")),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name=op.f("ck_takes_duration_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["segments.id"],
            name=op.f("fk_takes_segment_id_segments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_takes")),
        sa.UniqueConstraint(
            "segment_id",
            "segment_version",
            "attempt",
            name=op.f("uq_takes_segment_id_segment_version_attempt"),
        ),
    )
    op.create_index(op.f("ix_takes_segment_id"), "takes", ["segment_id"], unique=False)
    op.create_index(
        "ux_takes_one_active",
        "takes",
        ["segment_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("take_id", sa.Uuid(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "omission",
                "repetition",
                "substitution",
                "silence",
                "truncation",
                name="finding_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "fixed",
                "ignored",
                name="finding_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name=op.f("ck_findings_confidence_unit_interval")
        ),
        sa.CheckConstraint("end_ms >= start_ms", name=op.f("ck_findings_end_after_start")),
        sa.CheckConstraint("start_ms >= 0", name=op.f("ck_findings_start_nonnegative")),
        sa.ForeignKeyConstraint(
            ["take_id"], ["takes.id"], name=op.f("fk_findings_take_id_takes"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_findings")),
    )
    op.create_index("ix_findings_take_id_status", "findings", ["take_id", "status"], unique=False)
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("take_id", sa.Uuid(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "tts",
                "stt",
                "retry_skipped",
                name="ledger_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("credits >= 0", name=op.f("ck_ledger_entries_credits_nonnegative")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_ledger_entries_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["take_id"],
            ["takes.id"],
            name=op.f("fk_ledger_entries_take_id_takes"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_entries")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_ledger_entries_idempotency_key")),
    )
    op.create_index(
        "ix_ledger_entries_project_id_created_at",
        "ledger_entries",
        ["project_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_ledger_entries_project_id_created_at", table_name="ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_index("ix_findings_take_id_status", table_name="findings")
    op.drop_table("findings")
    op.drop_index("ux_takes_one_active", table_name="takes", postgresql_where=sa.text("is_active"))
    op.drop_index(op.f("ix_takes_segment_id"), table_name="takes")
    op.drop_table("takes")
    op.drop_index(op.f("ix_segments_project_id"), table_name="segments")
    op.drop_table("segments")
    op.drop_table("projects")
