"""The owner's trade copy (ADR 0009, amended 2026-11-15): one row per
tastytrade transaction, the transaction itself sealed by ``owner_vault``
(AES-256-GCM). Only the transaction's id, the key version and whether its
fees were still estimated stay outside the ciphertext, and all three are
bound to it; no date, symbol, amount or account number is.

A row is written once. The one update allowed: a row stored while its fees
were estimated is replaced when tastytrade later sends the final figures.
See ``alembic/versions/0006_owner_transactions.py`` for the DDL.
"""
from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, CheckConstraint, LargeBinary, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class OwnerTransaction(Base):
    __tablename__ = "owner_transactions"
    # The migration's check, here too: tests build their tables from the models.
    __table_args__ = (CheckConstraint("octet_length(nonce) = 12", name="owner_transactions_nonce_length"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    key_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    estimated_fee: Mapped[bool] = mapped_column(Boolean, nullable=False)
