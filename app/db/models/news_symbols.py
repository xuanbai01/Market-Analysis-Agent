from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class NewsSymbol(Base):
    """
    Many-to-many between news_items and symbols. One article can mention
    multiple tickers; one ticker accumulates many articles. Composite
    PK prevents duplicate (news, symbol) rows; both FKs cascade so
    deleting a symbol or article cleans up the join cleanly.
    """

    __tablename__ = "news_symbols"

    news_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("news_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    symbol: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("symbols.symbol", ondelete="CASCADE"),
        primary_key=True,
    )
