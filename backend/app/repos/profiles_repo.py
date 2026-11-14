"""REPO LAYER: profiles. Only SQL here: no HTTP errors, no business rules."""
from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection


async def get_by_user_id(conn: AsyncConnection, user_id: str) -> dict[str, Any] | None:
    cur = await conn.execute(
        "select user_id::text, tenant_id::text, role, display_name from profiles where user_id = %s",
        (user_id,),
    )
    return await cur.fetchone()
