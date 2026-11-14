"""DEPENDENCIES: small functions routes ask for with Depends(...).

get_current_user is the guard for every business/admin route; require_admin on top of it for admin pages.
Customer routes don't use these (they use the unguessable customers.token instead).
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request, status
from psycopg import AsyncConnection

from app.core.security import InvalidToken, verify_access_token
from app.db.session import get_async_conn
from app.repos import profiles_repo
from app.schemas.common import CurrentUser


async def get_db() -> AsyncIterator[AsyncConnection]:
    async with get_async_conn() as conn:
        yield conn


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return header[7:]


async def get_current_user(request: Request, db: AsyncConnection = Depends(get_db)) -> CurrentUser:
    try:
        claims = verify_access_token(_bearer_token(request))
    except InvalidToken as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from e

    profile = await profiles_repo.get_by_user_id(db, claims["sub"])
    if profile is None or profile["tenant_id"] is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No business linked to this account yet")
    return CurrentUser(email=claims.get("email"), **profile)


async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user
