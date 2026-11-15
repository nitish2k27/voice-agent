"""Pydantic models for the browser calling endpoints."""
from pydantic import BaseModel


class InboundStartIn(BaseModel):
    name: str | None = None
    phone: str | None = None


class CallTokenOut(BaseModel):
    room: str
    token: str
    livekit_url: str


class OkOut(BaseModel):
    ok: bool
