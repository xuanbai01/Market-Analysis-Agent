"""Schemas for the owner's routes (``/v1/owner``, ADR 0009)."""
from pydantic import BaseModel


class OwnerStatus(BaseModel):
    """What's set up for the owner. The unlock form reads it to check a key."""

    tastytrade: bool
