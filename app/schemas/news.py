from pydantic import BaseModel, HttpUrl


class NewsItemOut(BaseModel):
    id: str
    ts: str
    title: str
    url: HttpUrl
    source: str
    symbols: list[str] = []


class NewsListResponse(BaseModel):
    items: list[NewsItemOut]
    next_cursor: str | None = None