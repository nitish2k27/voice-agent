# Talking to LiveKit Cloud: rooms, sending the agent into a room, and join tokens for the browser.
# (The agent itself runs as its own process; this file only gives instructions to LiveKit.)

import json
import uuid
from datetime import timedelta

from livekit import api

from app.core.config import settings


def lk():
    """A LiveKit API client. Use it with `async with lk() as client:` so it closes cleanly."""
    return api.LiveKitAPI(settings.LIVEKIT_URL.replace("wss://", "https://"),
                          settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)


async def create_room(name, empty_timeout=60):
    async with lk() as client:
        await client.room.create_room(api.CreateRoomRequest(name=name, empty_timeout=empty_timeout))


async def delete_room(name):
    try:
        async with lk() as client:
            await client.room.delete_room(api.DeleteRoomRequest(room=name))
    except Exception:
        pass   # already gone


async def list_room_names(prefix=""):
    async with lk() as client:
        rooms = await client.room.list_rooms(api.ListRoomsRequest())
    return [r.name for r in rooms.rooms if r.name.startswith(prefix)]


async def dispatch_agent(room, metadata):
    """Explicit dispatch: ask LiveKit to send our agent (agent_name="amrutha") into this room."""
    async with lk() as client:
        await client.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
            agent_name=settings.AGENT_NAME, room=room, metadata=json.dumps(metadata)))


def join_token(room, identity=None, name="Customer", minutes=15):
    """Token the browser uses to join one room (mic on, can hear the agent)."""
    token = (api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
             .with_identity(identity or f"customer-{uuid.uuid4().hex[:8]}")
             .with_name(name)
             .with_ttl(timedelta(minutes=minutes))
             .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True)))
    return token.to_jwt()
