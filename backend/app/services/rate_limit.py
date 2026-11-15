# Simple "max N requests per window" limiter for the public Call-us button.
# Uses Redis when it's running (works across processes); falls back to memory (one API process) when it isn't.

import time

import redis

from app.core.config import settings

_memory = {}   # key -> list of request times (fallback only)


def allow(key, limit, window_seconds):
    """True if this request is allowed, False if the limit is reached."""
    try:
        r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5, socket_timeout=0.5)
        count = r.incr(key)
        if count == 1:
            r.expire(key, window_seconds)
        return count <= limit
    except redis.RedisError:
        now = time.time()
        recent = [t for t in _memory.get(key, []) if now - t < window_seconds]
        if len(recent) >= limit:
            _memory[key] = recent
            return False
        _memory[key] = recent + [now]
        return True
