"""ROUTES: who am I (tests login + profile link end to end)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.schemas.common import CurrentUser

router = APIRouter(tags=["me"])


@router.get("/me", response_model=CurrentUser)
async def me(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return user
