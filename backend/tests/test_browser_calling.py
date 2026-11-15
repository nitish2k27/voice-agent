# Milestone 5: customer page states, rate limit and join tokens (no network needed).
# Run from backend/:  pytest tests/test_browser_calling.py -v
from datetime import datetime, timedelta, timezone

import jwt
import redis

from app.core.config import settings
from app.services import livekit_service, rate_limit
from app.services.customer_calls import state_from_job

NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)


def job(status, rang_seconds_ago=None, room="out-1"):
    started = NOW - timedelta(seconds=rang_seconds_ago) if rang_seconds_ago is not None else None
    return {"status": status, "ring_started_at": started, "room_name": room}


def test_page_states():
    assert state_from_job(None, NOW)["state"] == "idle"
    s = state_from_job(job("ringing", 10), NOW)
    assert s["state"] == "ringing" and s["seconds_left"] == settings.RING_TIMEOUT_SECONDS - 10 and s["room"] == "out-1"
    assert state_from_job(job("ringing", 31), NOW)["state"] == "missed"      # rang out
    assert state_from_job(job("no_answer"), NOW)["state"] == "missed"
    assert state_from_job(job("in_call"), NOW)["state"] == "in_call"
    assert state_from_job(job("declined"), NOW)["state"] == "idle"
    assert state_from_job(job("completed"), NOW)["state"] == "idle"


def test_rate_limit_fourth_call_blocked_without_redis(monkeypatch):
    # pretend Redis is down -> the in-memory fallback must still limit
    def broken(*args, **kwargs):
        raise redis.ConnectionError("down")
    monkeypatch.setattr(redis, "from_url", broken)
    rate_limit._memory.clear()
    results = [rate_limit.allow("rl:test:1.2.3.4", 3, 600) for _ in range(4)]
    assert results == [True, True, True, False]
    assert rate_limit.allow("rl:test:5.6.7.8", 3, 600)      # another IP is not affected


def test_join_token_is_for_one_room():
    token = livekit_service.join_token("in-abc123", name="Caller")
    claims = jwt.decode(token, settings.LIVEKIT_API_SECRET, algorithms=["HS256"], options={"verify_aud": False})
    assert claims["video"]["room"] == "in-abc123"
    assert claims["video"]["roomJoin"] is True
    assert claims["name"] == "Caller"
