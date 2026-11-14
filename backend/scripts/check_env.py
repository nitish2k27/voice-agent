"""Milestone 0: verify .env keys and connect to every external service.

Usage (from repo root):  .venv/Scripts/python backend/scripts/check_env.py
Never prints secret values. Small real calls are made: Sarvam TTS (~10 chars) and LLM (a few tokens),
Gemini (a few tokens), and a test Google Calendar event that is created and deleted immediately.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import httpx
from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parents[2]  # repo root (backend/scripts/ -> backend -> root)
load_dotenv(ROOT / ".env", override=True)

OPTIONAL = {"SARVAM_DICT_ID", "LIVE_LLM_FALLBACK", "GOOGLE_SHEET_ID", "RAZORPAY_WEBHOOK_SECRET",
            "SUPABASE_JWT_SECRET", "JUDGE_LLM", "SIM_LLM", "LIVE_LLM_REASONING"}
results: list[tuple[str, str, str]] = []


def env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def record(name: str, status: str, detail: str = "") -> None:
    secrets = [v for k, v in os.environ.items() if v and len(v) > 8 and any(s in k for s in ("KEY", "SECRET", "PASSWORD"))]
    for s in secrets:
        detail = detail.replace(s, "***")
    detail = re.sub(r"postgresql://[^@\s]+@", "postgresql://***@", detail)
    results.append((name, status, detail[:220]))


def check(name: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        def run() -> None:
            try:
                out = fn()
                if asyncio.iscoroutine(out):
                    out = asyncio.run(out)
                record(name, "OK", out or "")
            except SkipCheck as e:
                record(name, "SKIPPED", str(e))
            except Exception as e:  # noqa: BLE001
                record(name, "FAIL", f"{type(e).__name__}: {e}")
        run.__name__ = fn.__name__
        CHECKS.append(run)
        return fn
    return deco


class SkipCheck(Exception):
    pass


CHECKS: list[Callable] = []


@check("env keys")
def env_keys() -> str:
    example = dotenv_values(ROOT / ".env.example")
    missing = [k for k in example if k not in OPTIONAL and not env(k)]
    if missing:
        raise RuntimeError("empty: " + ", ".join(missing))
    empty_opt = [k for k in example if k in OPTIONAL and not env(k)]
    return "all required set" + (f"; optional empty: {', '.join(empty_opt)}" if empty_opt else "")


@check("supabase postgres (pooler)")
def postgres() -> str:
    import psycopg
    url = env("DATABASE_URL")
    host = re.search(r"@([^:/]+)", url).group(1)
    with psycopg.connect(url, connect_timeout=10, prepare_threshold=None) as conn:
        cur = conn.cursor()
        cur.execute("select count(*) from tenants where id = %s", (env("TENANT_ID"),))
        tenant = cur.fetchone()[0]
        cur.execute("select format_type(atttypid, atttypmod) from pg_attribute "
                    "where attrelid = 'kb_chunks'::regclass and attname = 'embedding'")
        emb = cur.fetchone()[0]
        cur.execute("select count(*) from profiles where role = 'admin' and tenant_id = %s", (env("TENANT_ID"),))
        admins = cur.fetchone()[0]
        cur.execute("select count(*) from pg_tables where schemaname='public' and not rowsecurity")
        no_rls = cur.fetchone()[0]
        cur.execute("select count(*) from agent_configs where tenant_id = %s and is_active", (env("TENANT_ID"),))
        cfg = cur.fetchone()[0]
    problems = []
    if tenant != 1: problems.append("seed tenant missing")
    if emb != "vector(384)": problems.append(f"kb_chunks.embedding is {emb}, expected vector(384) (re-run schema)")
    if admins < 1: problems.append("no admin profile linked to the tenant")
    if no_rls: problems.append(f"{no_rls} public tables without RLS")
    if cfg != 1: problems.append("active agent_config missing")
    region = "Mumbai" if "ap-south-1" in host else f"NOT Mumbai ({host.split('.')[0]})"
    if problems:
        raise RuntimeError("; ".join(problems) + f" | region {region}")
    return f"tenant ok, embedding vector(384), admin ok, RLS on all tables | region {region}"


@check("supabase storage bucket")
def storage() -> str:
    key = env("SUPABASE_SERVICE_KEY")
    headers = {"apikey": key}
    if key.count(".") == 2:  # legacy JWT-style key
        headers["Authorization"] = f"Bearer {key}"
    r = httpx.get(f"{env('SUPABASE_URL')}/storage/v1/bucket/{env('KB_BUCKET')}", headers=headers, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:150]}")
    b = r.json()
    return f"bucket '{b.get('name')}' found, public={b.get('public')}"


@check("redis")
def redis_check() -> str:
    import redis
    r = redis.from_url(env("REDIS_URL"), socket_connect_timeout=3)
    r.ping()
    return "PONG"


@check("livekit cloud")
async def livekit_check() -> str:
    from livekit import api
    url = env("LIVEKIT_URL").replace("wss://", "https://")
    lk = api.LiveKitAPI(url, env("LIVEKIT_API_KEY"), env("LIVEKIT_API_SECRET"))
    try:
        rooms = await lk.room.list_rooms(api.ListRoomsRequest())
        return f"connected, {len(rooms.rooms)} active rooms"
    finally:
        await lk.aclose()


SARVAM_H = lambda: {"api-subscription-key": env("SARVAM_API_KEY")}  # noqa: E731


@check("sarvam tts (bulbul v4 flash, kn voice)")
def sarvam_tts() -> str:
    body = {"text": "ನಮಸ್ಕಾರ", "target_language_code": "kn-IN", "speaker": "chaitra_kn_conversation",
            "model": env("TTS_MODEL"), "speech_sample_rate": 16000}
    r = httpx.post("https://api.sarvam.ai/text-to-speech", headers=SARVAM_H(), json=body, timeout=30)
    if r.status_code == 422 or r.status_code == 400:
        body2 = dict(body); body2["inputs"] = [body2.pop("text")]
        r = httpx.post("https://api.sarvam.ai/text-to-speech", headers=SARVAM_H(), json=body2, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:180]}")
    audios = r.json().get("audios") or []
    return f"audio returned ({len(audios[0]) if audios else 0} b64 chars)"


@check("sarvam llm (live model)")
def sarvam_llm() -> str:
    body = {"model": env("LIVE_LLM"), "max_tokens": 20, "temperature": 0.2,
            "messages": [{"role": "user", "content": "Reply with one word: hello"}]}
    if env("LIVE_LLM_REASONING"):
        body["reasoning_effort"] = env("LIVE_LLM_REASONING")
    r = httpx.post("https://api.sarvam.ai/v1/chat/completions", headers=SARVAM_H(), json=body, timeout=60)
    if r.status_code == 400 and "reasoning" in r.text.lower():
        body.pop("reasoning_effort")
        r = httpx.post("https://api.sarvam.ai/v1/chat/completions", headers=SARVAM_H(), json=body, timeout=60)
        note = " (reasoning_effort rejected; dropped)"
    else:
        note = ""
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:180]}")
    j = r.json()
    usage = j.get("usage") or {}
    rt = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
    text = (j["choices"][0]["message"].get("content") or "").strip()[:30]
    return f"replied '{text}', reasoning_tokens={rt}{note}"


@check("gemini (extraction model)")
def gemini() -> str:
    model = env("EXTRACT_LLM")
    r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                   headers={"x-goog-api-key": env("GEMINI_API_KEY")},
                   json={"contents": [{"parts": [{"text": "Reply with one word: ok"}]}],
                         "generationConfig": {"maxOutputTokens": 20}}, timeout=60)
    if r.status_code == 503:
        return f"{model} exists but is overloaded right now (503); key OK, retry later"
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:180]}")
    return f"{model} responded"


@check("groq (judge / simulated caller)")
def groq() -> str:
    r = httpx.get("https://api.groq.com/openai/v1/models",
                  headers={"Authorization": f"Bearer {env('GROQ_API_KEY')}"}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:150]}")
    ids = sorted(m["id"] for m in r.json().get("data", []) if m.get("active", True))
    chosen = {k: env(k) for k in ("JUDGE_LLM", "SIM_LLM")}
    bad = [f"{k}={v}" for k, v in chosen.items() if v and v not in ids]
    if bad:
        raise RuntimeError("model not available: " + ", ".join(bad))
    unset = [k for k, v in chosen.items() if not v]
    hint = f"; set {', '.join(unset)} from: {', '.join(i for i in ids if 'whisper' not in i and 'tts' not in i and 'guard' not in i)[:200]}" if unset else ""
    return f"key ok, {len(ids)} models{hint}"


@check("google calendar (service account)")
def calendar() -> str:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    path = (ROOT / env("GOOGLE_SERVICE_ACCOUNT_JSON")).resolve()
    creds = service_account.Credentials.from_service_account_file(
        str(path), scopes=["https://www.googleapis.com/auth/calendar.events"])
    svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
    start = (datetime.now() + timedelta(days=400)).replace(hour=10, minute=0, second=0, microsecond=0)
    ev = svc.events().insert(calendarId=env("GOOGLE_CALENDAR_ID"), body={
        "summary": "TEST - voice agent check_env (auto-deleted)",
        "start": {"dateTime": start.isoformat(), "timeZone": env("TIMEZONE") or "Asia/Kolkata"},
        "end": {"dateTime": (start + timedelta(minutes=15)).isoformat(), "timeZone": env("TIMEZONE") or "Asia/Kolkata"},
    }).execute()
    svc.events().delete(calendarId=env("GOOGLE_CALENDAR_ID"), eventId=ev["id"]).execute()
    return f"created + deleted a test event as {creds.service_account_email.split('@')[0]}@..."


@check("google sheets")
def sheets() -> str:
    if not env("GOOGLE_SHEET_ID"):
        raise SkipCheck("GOOGLE_SHEET_ID empty (optional)")
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        str((ROOT / env("GOOGLE_SERVICE_ACCOUNT_JSON")).resolve()),
        scopes=["https://www.googleapis.com/auth/spreadsheets"])
    meta = build("sheets", "v4", credentials=creds, cache_discovery=False).spreadsheets().get(
        spreadsheetId=env("GOOGLE_SHEET_ID")).execute()
    return f"opened '{meta['properties']['title']}'"


@check("razorpay (test mode)")
def razorpay() -> str:
    kid = env("RAZORPAY_KEY_ID")
    if not kid.startswith("rzp_test_"):
        raise RuntimeError("RAZORPAY_KEY_ID is not a test key (must start with rzp_test_)")
    r = httpx.get("https://api.razorpay.com/v1/payments", params={"count": 1},
                  auth=(kid, env("RAZORPAY_KEY_SECRET")), timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:150]}")
    return "test keys accepted"


def main() -> int:
    for run in CHECKS:
        run()
    width = max(len(n) for n, _, _ in results)
    for name, status, detail in results:
        print(f"{name:<{width}}  {status:<7}  {detail}")
    fails = [n for n, s, _ in results if s == "FAIL"]
    print("\nALL OK" if not fails else f"\n{len(fails)} FAILED: {', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
