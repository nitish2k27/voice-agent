# The customer's call page (/c/:token): is a call ringing for me? Accept / decline it.
#
# The state comes from the call_jobs table (the DB is the source of truth). The SSE endpoint reads it
# once a second and sends a new event whenever it changes. Milestone 6's dial_call sets jobs to "ringing".

from datetime import datetime, timezone

from app.core.config import settings
from app.db.session import get_sync_conn
from app.repos import calls_repo, customers_repo
from app.services import livekit_service

BUSINESS_NAME = "Amrith Sagar Catering"


class NotFound(Exception):
    pass


class NotRinging(Exception):
    pass


def page_state(token):
    """{"state": "idle" | "ringing" | "missed" | "in_call", ...} for this customer."""
    with get_sync_conn() as conn:
        customer = customers_repo.get_by_token(conn, token)
        if customer is None:
            raise NotFound()
        job = customers_repo.latest_job(conn, customer["id"])

    base = {"business_name": BUSINESS_NAME, "customer_name": customer["name"]}
    return {**base, **state_from_job(job, datetime.now(timezone.utc))}


def state_from_job(job, now):
    """The page state for the customer's latest job (pure function, easy to test)."""
    if job is None:
        return {"state": "idle"}
    if job["status"] == "ringing" and job["ring_started_at"]:
        waited = (now - job["ring_started_at"]).total_seconds()
        left = int(settings.RING_TIMEOUT_SECONDS - waited)
        if left > 0:
            return {"state": "ringing", "room": job["room_name"], "seconds_left": left}
        return {"state": "missed"}            # rang for 30 s and nobody answered
    if job["status"] == "no_answer":
        return {"state": "missed"}
    if job["status"] == "in_call":
        return {"state": "in_call", "room": job["room_name"]}
    return {"state": "idle"}                  # declined, completed, queued ...


def accept(token):
    """Customer pressed Accept: give them a token for the ringing room."""
    state = page_state(token)
    if state["state"] != "ringing":
        raise NotRinging()
    with get_sync_conn() as conn:
        customer = customers_repo.get_by_token(conn, token)
        job = customers_repo.latest_job(conn, customer["id"])
        if not customers_repo.set_job_status(conn, job["id"], "in_call", only_if="ringing"):
            raise NotRinging()      # timed out at the same moment
    return {"room": job["room_name"], "livekit_url": settings.LIVEKIT_URL,
            "token": livekit_service.join_token(job["room_name"], name=customer["name"] or "Customer")}


async def decline(token):
    """Customer pressed Decline: the job becomes 'declined' and the room is closed (retry is Milestone 6)."""
    with get_sync_conn() as conn:
        customer = customers_repo.get_by_token(conn, token)
        if customer is None:
            raise NotFound()
        job = customers_repo.latest_job(conn, customer["id"])
        changed = job is not None and customers_repo.set_job_status(conn, job["id"], "declined", only_if="ringing")
        if changed:
            calls_repo.mark_declined(conn, job["id"])   # close the call row the agent already opened
    if changed and job["room_name"]:
        await livekit_service.delete_room(job["room_name"])
    return {"ok": True}
