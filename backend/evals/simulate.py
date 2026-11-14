# Text-mode test suite: the real agent (same prompt, tools, LLM) talks to a simulated caller (Groq LLM).
# No audio, so it only costs a few LLM calls per persona.
#
# From backend/ (venv active):
#     python -m evals.simulate --personas evals/personas.yaml --prompt-version v1
#     python -m evals.simulate --only 12             (just one persona)
#
# Bookings/callbacks made during a run are saved with is_test=true. Results go to eval_runs / eval_results.

import argparse
import asyncio
import logging
import sys
import time

import httpx
import yaml
from livekit.agents import AgentSession

from agent import prompts
from agent.agent import Amrutha, load_config, make_llm, new_call_state, sample_customer
from agent.language import script_language
from app.core.config import settings
from app.db.session import get_sync_conn
from app.repos import eval_repo
from evals.checks import CHECKS

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.WARNING, format="   [log] %(message)s")
logging.getLogger("amrutha").setLevel(logging.INFO)          # shows LANGUAGE switch lines
logging.getLogger("amrutha.tools").setLevel(logging.WARNING)  # tool lines are in the transcript already

CALLER_RULES = (
    "You are a customer on a phone call with a catering company's AI assistant. Stay in character.\n"
    "Reply in 1-2 short spoken sentences, no stage directions, no quotes.\n"
    "When the conversation is naturally over (goodbye said), reply with just: [HANGUP]"
)


def groq_chat(model, messages, max_tokens=300):
    """One chat call to Groq (OpenAI-compatible). Retries a few times on rate limits."""
    for attempt in range(5):
        r = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
            json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.7,
                  "reasoning_effort": "low"},
            timeout=60,
        )
        if r.status_code == 429 or r.status_code == 400 or r.status_code >= 500:
            # 429 = rate limit; 400/5xx happen now and then on the free tier, a retry usually works
            last_error = f"HTTP {r.status_code}: {r.text[:200]}"
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return (r.json()["choices"][0]["message"].get("content") or "").strip()
    raise RuntimeError(f"Groq kept failing: {last_error}")


def caller_says(persona, turns, opening):
    """Ask the simulated caller for its next line. From the caller's point of view the agent is the 'user'."""
    messages = [{"role": "system", "content": CALLER_RULES + "\n\nYour character:\n" + persona["behaviour"]},
                {"role": "user", "content": opening}]
    for t in turns:
        messages.append({"role": "assistant", "content": t["caller"]})
        messages.append({"role": "user", "content": " ".join(t["agent"]) or "(silence)"})
    return groq_chat(settings.SIM_LLM, messages, max_tokens=200)


def make_judge(transcript_text):
    def judge(question):
        answer = groq_chat(settings.JUDGE_LLM, [
            {"role": "system", "content": "You check phone call transcripts. Answer with exactly one word: YES or NO."},
            {"role": "user", "content": f"Transcript:\n{transcript_text}\n\nQuestion: {question}"},
        ], max_tokens=400)
        return answer.upper().startswith("YES")
    return judge


async def run_persona(persona, config, prompt_version, max_turns):
    customer = sample_customer(persona["customer"]) if persona.get("customer") else {}
    meta = {"tenant_id": settings.TENANT_ID, "call_type": persona["call_type"], "customer": customer, "is_test": True}
    config = {**config, "prompt_version": prompt_version}
    state = new_call_state(meta, config)
    agent = Amrutha(state)

    opening = prompts.opening_line(state.direction, config)
    turns = []
    async with AgentSession(userdata=state, llm=make_llm(state.session_id)) as session:
        await session.start(agent)
        for _ in range(max_turns):
            line = caller_says(persona, turns, opening)
            hangup = "[HANGUP]" in line
            line = line.replace("[HANGUP]", "").strip()
            if not line:
                break
            # same path as a spoken sentence: the language switcher sees it first
            await agent.on_customer_sentence(script_language(line), line)
            result = await session.run(user_input=line)
            replies = [ev.item.text_content for ev in result.events
                       if ev.type == "message" and ev.item.role == "assistant" and ev.item.text_content]
            turns.append({"caller": line, "agent": replies})
            if hangup or any(t["name"] == "end_call" for t in state.tool_log):
                break
    return opening, turns, state.tool_log


def as_text(opening, turns):
    lines = [f"AGENT: {opening}"]
    for t in turns:
        lines.append(f"CALLER: {t['caller']}")
        lines += [f"AGENT: {r}" for r in t["agent"]]
    return "\n".join(lines)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--personas", default="evals/personas.yaml")
    parser.add_argument("--prompt-version", default=settings.PROMPT_VERSION)
    parser.add_argument("--only", type=int, nargs="*", help="persona ids to run")
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--show", action="store_true", help="print every transcript")
    args = parser.parse_args()

    personas = yaml.safe_load(open(args.personas, encoding="utf-8"))
    if args.only:
        personas = [p for p in personas if p["id"] in args.only]
    config = await asyncio.to_thread(load_config, settings.TENANT_ID)

    with get_sync_conn() as conn:
        run_id = eval_repo.start_run(conn, settings.TENANT_ID, args.prompt_version, settings.LIVE_LLM,
                                     settings.SIM_LLM, settings.JUDGE_LLM, settings.SEARCH_MODE, len(personas))

    rows = []
    for p in personas:
        print(f"\n=== persona {p['id']}: {p['name']} ===")
        try:
            opening, turns, tool_log = await run_persona(p, config, args.prompt_version, args.max_turns)
            text = as_text(opening, turns)
            passed, why = CHECKS[p["check"]](turns, tool_log, make_judge(text))
        except Exception as e:  # one broken persona shouldn't stop the suite
            opening, turns, tool_log, text = "", [], [], ""
            passed, why = False, f"ERROR {type(e).__name__}: {e}"
        if args.show or not passed:
            print(text)
        print(f"--> {'PASS' if passed else 'FAIL'}: {why}")
        rows.append((p["id"], p["name"], len(turns), passed, why))
        with get_sync_conn() as conn:
            eval_repo.save_result(conn, run_id, p["id"], p["name"], len(turns),
                                  {"opening": opening, "turns": turns}, tool_log, passed, why)

    with get_sync_conn() as conn:
        eval_repo.finish_run(conn, run_id)

    print(f"\n{'id':>3}  {'persona':38} {'turns':>5}  result")
    for pid, name, n, passed, why in rows:
        print(f"{pid:>3}  {name[:38]:38} {n:>5}  {'PASS' if passed else 'FAIL'}")
    print(f"\n{sum(r[3] for r in rows)}/{len(rows)} passed   (prompt {args.prompt_version}, run {run_id[:8]})")


if __name__ == "__main__":
    asyncio.run(main())
