# Milestone 1 check: does the live LLM call our tool reliably?
#
# This talks to Sarvam's chat API directly (text only, no microphone, no LiveKit),
# asks the availability question 10 times, and counts how often the model
# calls check_availability with the right date.
#
# Run from the backend folder:
#     python scripts/test_tool_calling.py
#     python scripts/test_tool_calling.py --model sarvam-105b --tries 5     (try a fallback model)
#
# Cost: about 10 short LLM calls (a few paise).

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so "app" can be imported
from app.core.config import settings  # noqa: E402

QUESTION = "Are you free on 20 December for 300 people?"
EXPECTED_DATE = "2026-12-20"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Check if Amrith Sagar can cater an event on a given date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "event date in YYYY-MM-DD format"},
                    "guests": {"type": "integer", "description": "number of guests"},
                },
                "required": ["date", "guests"],
            },
        },
    }
]

SYSTEM = (
    "You are Amrutha, the AI phone assistant of Amrith Sagar Catering in Bengaluru. "
    "Before saying yes to any date, call check_availability with the date as YYYY-MM-DD and the number of guests. "
    "Today is Sunday, 15 November 2026."
)


def ask_once(model):
    # sarvam-105b-conversations only lives on /v1; the other models use /v2
    version = "v1" if model == "sarvam-105b-conversations" else "v2"
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": QUESTION}],
        "tools": TOOLS,
        "tool_choice": "auto",
        "max_tokens": 250,
        "temperature": 0.3,
    }
    start = time.time()
    r = httpx.post(
        f"https://api.sarvam.ai/{version}/chat/completions",
        headers={"api-subscription-key": settings.SARVAM_API_KEY},
        json=body,
        timeout=60,
    )
    seconds = time.time() - start
    if r.status_code != 200:
        return {"ok": False, "why": f"HTTP {r.status_code}: {r.text[:150]}", "seconds": seconds}

    message = r.json()["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    if not calls:
        return {"ok": False, "why": f"no tool call, said: {(message.get('content') or '')[:80]}", "seconds": seconds}

    args = json.loads(calls[0]["function"]["arguments"] or "{}")
    right = calls[0]["function"]["name"] == "check_availability" and args.get("date") == EXPECTED_DATE and args.get("guests") == 300
    return {"ok": right, "why": f"called with {args}", "seconds": seconds}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=settings.LIVE_LLM)
    parser.add_argument("--tries", type=int, default=10)
    args = parser.parse_args()

    print(f"Model: {args.model}   Question: {QUESTION!r}\n")
    good = 0
    for i in range(1, args.tries + 1):
        result = ask_once(args.model)
        good += result["ok"]
        print(f"try {i:2}: {'PASS' if result['ok'] else 'FAIL'}  {result['seconds']:.1f}s  {result['why']}")

    print(f"\n{good}/{args.tries} correct tool calls")
    if args.tries - good > 2:
        print("More than 2 failures: set LIVE_LLM to a fallback model in .env (see CLAUDE.md) and re-run this script.")


if __name__ == "__main__":
    main()
