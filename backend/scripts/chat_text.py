# Talk to the agent in TEXT (no microphone, no speech costs). Same prompt, tools and LLM as the voice agent.
#
# From backend/ (venv active):
#     python scripts/chat_text.py                                   -> type messages, empty line to quit
#     python scripts/chat_text.py "message 1" "message 2" ...       -> run a fixed conversation
#     python scripts/chat_text.py --call-type post_event_feedback --customer C001 "Yes, tell me"
#
# Bookings/callbacks made here are saved with is_test=true, so they never block real dates.

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # Kannada/Hindi text in the Windows console

from livekit.agents import AgentSession  # noqa: E402

from agent.agent import Amrutha, load_config, make_llm, new_call_state, sample_customer  # noqa: E402
from agent.call_logger import CallLogger  # noqa: E402
from agent.language import script_language  # noqa: E402
from app.core.config import settings  # noqa: E402


def print_events(result):
    for ev in result.events:
        if ev.type == "function_call":
            print(f"   [tool call] {ev.item.name}({ev.item.arguments})")
        elif ev.type == "function_call_output":
            print(f"   [tool result] {str(ev.item.output)[:200]}")
        elif ev.type == "message" and ev.item.role == "assistant":
            print(f"AGENT: {ev.item.text_content}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("messages", nargs="*")
    parser.add_argument("--call-type", default="inbound")
    parser.add_argument("--customer", default="C001", help="customer_id from sample_customers.csv (outbound only)")
    args = parser.parse_args()

    customer = sample_customer(args.customer) if args.call_type != "inbound" else {}
    meta = {"tenant_id": settings.TENANT_ID, "call_type": args.call_type, "customer": customer, "is_test": True}
    state = new_call_state(meta, await asyncio.to_thread(load_config, settings.TENANT_ID))

    logger = CallLogger(state, room_name="text-chat")   # saves the chat like a real call (is_test=true)
    await logger.start()
    logger.mark_answered()

    async with AgentSession(userdata=state, llm=make_llm(state.session_id)) as session:
        session.on("conversation_item_added", logger.on_item)
        agent = Amrutha(state)
        await session.start(agent)

        messages = args.messages
        interactive = not messages
        while True:
            if interactive:
                text = input("\nYOU: ").strip()
                if not text:
                    break
            else:
                if not messages:
                    break
                text = messages.pop(0)
                print(f"\nYOU: {text}")
            await agent.on_customer_sentence(script_language(text), text)   # same path as a spoken sentence
            result = await session.run(user_input=text)
            print_events(result)
            if state.ended_by:          # the agent called end_call
                break

        await logger.finish(session.usage, ended_by=state.ended_by or "customer", has_audio=False)

    print(f"\ncall saved: {state.call_id}")
    print(f"answers saved: {state.answers}")
    print(f"pending questions left: {[q['key'] for q in state.pending_questions]}")


if __name__ == "__main__":
    asyncio.run(main())
