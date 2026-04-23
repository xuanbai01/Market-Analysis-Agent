from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class Symbol(Base):
    __tablename__ = "symbols"
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)