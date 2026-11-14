"""Shared Pydantic models."""
from __future__ import annotations

from pydantic import BaseModel


class HealthOut(BaseModel):
    status: str
    db: str | None = None


class CurrentUser(BaseModel):
    user_id: str
    email: str | None = None
    tenant_id: str | None = None
    role: str
    display_name: str | None = None
