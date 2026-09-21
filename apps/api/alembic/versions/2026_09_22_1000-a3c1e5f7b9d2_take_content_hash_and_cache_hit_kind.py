"""take content_hash and cache_hit ledger kind

Revision ID: a3c1e5f7b9d2
Revises: 4fb6efeac138
Create Date: 2026-09-22 10:00:00.000000

`takes.content_hash` is added NOT NULL without a default: no take has ever been written
before this revision (the first generating endpoint ships with it), so the table is empty
everywhere. If that assumption is wrong, the ALTER fails loudly instead of inventing a hash.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3c1e5f7b9d2"
down_revision: str | Sequence[str] | None = "4fb6efeac138"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KIND_CHECK = "ck_ledger_entries_ledger_kind"
OLD_KINDS = "'tts', 'stt', 'retry_skipped'"
NEW_KINDS = "'tts', 'stt', 'retry_skipped', 'cache_hit'"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("takes", sa.Column("content_hash", sa.String(length=64), nullable=False))
    op.create_index(op.f("ix_takes_content_hash"), "takes", ["content_hash"], unique=False)
    # The kind enum is a VARCHAR + CHECK (ADR-0003): widening it is drop + create.
    op.drop_constraint(op.f(KIND_CHECK), "ledger_entries", type_="check")
    op.create_check_constraint(op.f(KIND_CHECK), "ledger_entries", f"kind IN ({NEW_KINDS})")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM ledger_entries WHERE kind = 'cache_hit'")
    op.drop_constraint(op.f(KIND_CHECK), "ledger_entries", type_="check")
    op.create_check_constraint(op.f(KIND_CHECK), "ledger_entries", f"kind IN ({OLD_KINDS})")
    op.drop_index(op.f("ix_takes_content_hash"), table_name="takes")
    op.drop_column("takes", "content_hash")
