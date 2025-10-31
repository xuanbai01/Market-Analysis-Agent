from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, TIMESTAMP, text
from app.db.models.base import Base


class NewsItemModel(Base):
    __tablename__ = "news_items"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ts: Mapped[str] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    title: Mapped[str] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(String(1024))
    source: Mapped[str] = mapped_column(String(64))