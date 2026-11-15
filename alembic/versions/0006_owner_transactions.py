"""owner_transactions: the owner's tastytrade transactions, encrypted

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-15

ADR 0009 (amended 2026-11-15): the owner's own trades are theirs under
tastytrade's terms, so a copy may be kept, here, one row per transaction
sealed with AES-256-GCM under a key that lives only on Fly
(``app/services/owner_vault.py``). Only the transaction id and whether its
fees were still estimated are in the clear.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "owner_transactions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("key_version", sa.SmallInteger(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("estimated_fee", sa.Boolean(), nullable=False),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("owner_transactions")
