from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String
from typing import Optional
from app.db.models.base import Base


class Symbol(Base):
    __tablename__ = "symbols"
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)