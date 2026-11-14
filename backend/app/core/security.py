"""Verify Supabase Auth access tokens (the JWT the frontend gets from supabase-js).

New Supabase projects sign tokens with asymmetric keys (verified via the project's JWKS);
older ones use the HS256 legacy secret. We support both: the token header's `alg` decides.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient #for supabse login it just cehcks the the jwt with the public key and verfiyes the autheneication

from app.core.config import settings

AUDIENCE = "authenticated"


class InvalidToken(Exception):
    pass


@lru_cache
def _jwks_client() -> PyJWKClient:
    return PyJWKClient(f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json", cache_keys=True, lifespan=3600)


def verify_access_token(token: str) -> dict[str, Any]:
    """Return the token claims (sub = user id, email, role ...) or raise InvalidToken."""
    try:
        alg = jwt.get_unverified_header(token).get("alg", "")
        if alg == "HS256":
            if not settings.SUPABASE_JWT_SECRET:
                raise InvalidToken("HS256 token but SUPABASE_JWT_SECRET is not set")
            key: Any = settings.SUPABASE_JWT_SECRET
        else:
            key = _jwks_client().get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=[alg], audience=AUDIENCE)
    except InvalidToken:
        raise
    except Exception as e:  # noqa: BLE001  (expired, bad signature, unknown kid, network ...)
        raise InvalidToken(str(e)) from e
