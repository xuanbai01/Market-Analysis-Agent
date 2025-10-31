from pydantic import BaseModel


class CursorPage(BaseModel):
    items: list
    next_cursor: str | None = None