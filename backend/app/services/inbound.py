# "Call us" button: start an inbound call in a new LiveKit room with our agent in it.

import uuid

from app.core.config import settings
from app.services import livekit_service, rate_limit


class TooManyCalls(Exception):
    pass


async def start_inbound_call(client_ip, name=None, phone=None):
    # 1. per-IP limit, so a public link can't be used to burn our Sarvam credits
    if not rate_limit.allow(f"rl:inbound:{client_ip}", settings.INBOUND_RATE_LIMIT_PER_IP, 600):
        raise TooManyCalls("Too many calls from your connection. Please try again in a few minutes.")

    # 2. global cap on calls at the same time (LiveKit's room list is the truth)
    active = await livekit_service.list_room_names(prefix="in-")
    if len(active) >= settings.INBOUND_MAX_CONCURRENT:
        raise TooManyCalls("All our lines are busy right now. Please try again in a minute.")

    # 3. room + agent + token for the browser
    room = f"in-{uuid.uuid4().hex[:12]}"
    await livekit_service.create_room(room)
    customer = {"name": name, "phone": phone} if (name or phone) else {}
    await livekit_service.dispatch_agent(room, {
        "tenant_id": settings.TENANT_ID, "direction": "inbound", "call_type": "inbound",
        "customer": customer, "is_test": False,
    })
    return {"room": room, "livekit_url": settings.LIVEKIT_URL,
            "token": livekit_service.join_token(room, name=name or "Caller")}
