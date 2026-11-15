"""ROUTES: the public "Call us" button (no login)."""
from fastapi import APIRouter, HTTPException, Request

from app.schemas.calls import CallTokenOut, InboundStartIn
from app.services import inbound

router = APIRouter(tags=["customer"])


@router.post("/inbound/start", response_model=CallTokenOut)
async def start(request: Request, body: InboundStartIn | None = None):
    body = body or InboundStartIn()
    # behind Cloudflare Tunnel the real IP comes in this header
    ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")
    try:
        return await inbound.start_inbound_call(ip, body.name, body.phone)
    except inbound.TooManyCalls as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
