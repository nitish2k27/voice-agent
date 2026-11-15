"""ROUTES: the customer's personal call page /c/:token (no login: the token in the link is the key)."""
import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.schemas.calls import CallTokenOut, OkOut
from app.services import customer_calls

router = APIRouter(prefix="/customer", tags=["customer"])


@router.get("/{token}/events")
async def events(token: str, request: Request):
    """Server-sent events: the current state right away, then a new event each time it changes."""
    try:
        first = await asyncio.to_thread(customer_calls.page_state, token)
    except customer_calls.NotFound as e:
        raise HTTPException(404, "Unknown link") from e

    async def stream():
        last = None
        state = first
        while not await request.is_disconnected():
            # send when the state changes, and every second while ringing (countdown)
            key = (state["state"], state.get("room"))
            if key != last or state["state"] == "ringing":
                yield {"event": state["state"], "data": json.dumps(state)}
                last = key
            await asyncio.sleep(1)
            state = await asyncio.to_thread(customer_calls.page_state, token)

    return EventSourceResponse(stream(), ping=15)


@router.post("/{token}/join", response_model=CallTokenOut)
async def join(token: str):
    try:
        return await asyncio.to_thread(customer_calls.accept, token)
    except customer_calls.NotFound as e:
        raise HTTPException(404, "Unknown link") from e
    except customer_calls.NotRinging as e:
        raise HTTPException(409, "There is no call ringing right now") from e


@router.post("/{token}/decline", response_model=OkOut)
async def decline(token: str):
    try:
        return await customer_calls.decline(token)
    except customer_calls.NotFound as e:
        raise HTTPException(404, "Unknown link") from e
