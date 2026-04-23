from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, TIMESTAMP, text
from app.db.models.base import Base

class NewsItemModel(Base):
    __tablename__ = "news_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ts: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
