from pydantic import BaseModel


class SymbolOut(BaseModel):
    symbol: str
    name: str | None = None


class SymbolCreate(BaseModel):
    symbol: str
    name: str | None = None