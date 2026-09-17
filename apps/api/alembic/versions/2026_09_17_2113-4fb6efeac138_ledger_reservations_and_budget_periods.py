"""ledger reservations and budget periods

Revision ID: 4fb6efeac138
Revises: 7140db651314
Create Date: 2026-09-17 21:13:47.781169

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4fb6efeac138"
down_revision: str | Sequence[str] | None = "7140db651314"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "budget_periods",
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("period", name=op.f("pk_budget_periods")),
    )
    # `period` is NOT NULL and a FK, but existing rows (settled costs written before the pending
    # pattern) have no period yet: add it nullable, backfill from created_at, then tighten.
    op.add_column("ledger_entries", sa.Column("period", sa.String(length=7), nullable=True))
    op.execute(
        "UPDATE ledger_entries SET period = to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM')"
    )
    op.execute(
        "INSERT INTO budget_periods (period) SELECT DISTINCT period FROM ledger_entries "
        "ON CONFLICT (period) DO NOTHING"
    )
    op.alter_column("ledger_entries", "period", nullable=False)
    op.add_column(
        "ledger_entries",
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "done",
                "possibly_billed",
                "failed",
                name="ledger_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(
        "ledger_entries",
        sa.Column("estimated_credits", sa.Integer(), server_default="0", nullable=False),
    )
    # Rows that exist at this point were written after a successful call: they are settled facts,
    # not reservations, so mark them done with the estimate equal to the reported cost.
    op.execute("UPDATE ledger_entries SET status = 'done', estimated_credits = credits")
    op.create_check_constraint(
        op.f("ck_ledger_entries_estimated_credits_nonnegative"),
        "ledger_entries",
        "estimated_credits >= 0",
    )
    op.add_column("ledger_entries", sa.Column("request_id", sa.String(length=64), nullable=True))
    op.add_column(
        "ledger_entries", sa.Column("failure_reason", sa.String(length=255), nullable=True)
    )
    op.create_index(
        "ix_ledger_entries_period_status", "ledger_entries", ["period", "status"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_ledger_entries_period_budget_periods"),
        "ledger_entries",
        "budget_periods",
        ["period"],
        ["period"],
        ondelete="RESTRICT",
    )
    op.add_column("takes", sa.Column("request_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Downgrade schema. Lossy: pending/failed/possibly_billed rows become plain entries with
    whatever `credits` holds (0 for pending and failed)."""
    op.drop_constraint(
        op.f("ck_ledger_entries_estimated_credits_nonnegative"), "ledger_entries", type_="check"
    )
    op.drop_column("takes", "request_id")
    op.drop_constraint(
        op.f("fk_ledger_entries_period_budget_periods"), "ledger_entries", type_="foreignkey"
    )
    op.drop_index("ix_ledger_entries_period_status", table_name="ledger_entries")
    op.drop_column("ledger_entries", "failure_reason")
    op.drop_column("ledger_entries", "request_id")
    op.drop_column("ledger_entries", "estimated_credits")
    op.drop_column("ledger_entries", "status")
    op.drop_column("ledger_entries", "period")
    op.drop_table("budget_periods")
