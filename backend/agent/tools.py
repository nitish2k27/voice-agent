# The agent's tools. Each one is a plain async function the LLM can call.
# The call's state (customer, pending questions, language, ...) lives in CallState,
# which LiveKit hands to every tool as context.userdata.
#
# Database work is sync psycopg, so we run it with asyncio.to_thread (keeps the voice loop smooth
# and avoids async-psycopg problems with the Windows event loop).

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Literal

from livekit.agents import RunContext, function_tool
from pydantic import BaseModel, Field

from agent import prompts
from app.services import availability, bookings, quote, search

log = logging.getLogger("amrutha.tools")


@dataclass
class CallState:
    tenant_id: str
    call_type: str                      # inbound | post_event_feedback | enquiry_followup | pre_event_confirmation
    direction: str                      # inbound | outbound
    customer: dict                      # CSV row for outbound, {} for inbound
    pending_questions: list             # [{"key": ..., "text": ...}] not answered yet
    config: dict                        # agent_configs row
    current_language: str | None = None # language the agent is told to reply in; None = follow the caller (M3 sets it)
    last_heard_language: str = "en-IN"  # language of the customer's last sentence (filler fallback)
    is_test: bool = True                # console / eval calls don't block real dates
    session_id: str = ""                # random id per call, for Sarvam prompt caching
    call_id: str | None = None          # the calls table row (created in Milestone 4; None until then)
    customer_id: str | None = None
    last_customer_text: str = ""        # the customer's last sentence (end_call safety check)
    turn_count: int = 0                 # messages so far (call_logger keeps it up to date)
    ended_by: str | None = None         # agent | silence | max_duration ... (set by end_call / guardrails)
    asked_before_ending: bool = False   # end_call refused once already -> next one is allowed
    answers: dict = field(default_factory=dict)    # question_key -> answer (English)
    tool_log: list = field(default_factory=list)   # saved to the tool_calls table in Milestone 4

    def build_prompt(self):
        return prompts.build_prompt(self.call_type, self.customer, self.pending_questions,
                                    self.current_language, self.config)


def say_filler(context, key):
    state = context.userdata
    # say() is not async: it queues the line and returns, so the tool keeps working while it plays
    language = state.current_language or state.last_heard_language
    context.session.say(prompts.filler(key, language, state.config))


def remember(state, name, args, started, result, ok=True):
    ms = int((time.time() - started) * 1000)
    state.tool_log.append({"name": name, "args": args, "result": result, "duration_ms": ms, "ok": ok,
                           "turn_index": state.turn_count})
    log.info("TOOL %s %s -> %s (%d ms)", name, json.dumps(args, ensure_ascii=False), str(result)[:160], ms)


# ---------------------------------------------------------------- codes the LLM may use (from the pricing file)
PackageCode = Literal[tuple(quote.package_codes())]
AddOnCode = Literal[tuple(quote.add_on_codes())]
CustomItemName = Literal[tuple(quote.custom_item_names())]


class AddOn(BaseModel):
    code: AddOnCode
    qty: int | None = Field(None, description="only for extra servers, boxes or extra hours")


class CustomItem(BaseModel):
    item: CustomItemName
    diet: Literal["veg", "non_veg"] = "veg"
    count: int = 1


# ---------------------------------------------------------------- tools
@function_tool
async def search_knowledge_base(context: RunContext, query: str) -> str:
    """Search Amrith Sagar's knowledge base: services, menu, packages, policies, areas, FAQs.

    Args:
        query: short ENGLISH keywords, even if the customer speaks another language (e.g. "jain food", "cancellation charge")
    """
    state, started = context.userdata, time.time()
    say_filler(context, "check")
    rows = await asyncio.to_thread(search.search, state.tenant_id, query)
    result = search.results_for_llm(rows)
    remember(state, "search_knowledge_base", {"query": query}, started, f"{len(rows)} chunks: " + ", ".join(r["section"] for r in rows))
    return result


@function_tool
async def calculate_quote(
    context: RunContext,
    adults: int,
    package_code: PackageCode | None = None,
    children_5_12: int = 0,
    area: str | None = None,
    add_ons: list[AddOn] | None = None,
    custom_items: list[CustomItem] | None = None,
    event_date: str | None = None,
) -> str:
    """Calculate the price for an event. Always use this for any price or total; never calculate yourself.

    Args:
        adults: number of adult guests (and children above 12)
        package_code: one of the package codes (leave empty when the customer builds a custom menu)
        children_5_12: number of children aged 5 to 12 (children under 5 are free, don't count them)
        area: venue area or town in English letters, e.g. "Jayanagar", "Mysuru"
        add_ons: extra services such as live counters or bar setup
        custom_items: dishes for a custom menu instead of a package (at least 6 dishes)
        event_date: event date as YYYY-MM-DD if known
    """
    state, started = context.userdata, time.time()
    args = {"adults": adults, "package_code": package_code, "children_5_12": children_5_12, "area": area,
            "add_ons": [a.model_dump() for a in add_ons or []],
            "custom_items": [c.model_dump() for c in custom_items or []], "event_date": event_date}
    result = quote.calculate_quote(package_code=package_code, adults=adults, children_5_12=children_5_12,
                                   area=area, add_ons=args["add_ons"], custom_items=args["custom_items"],
                                   event_date=event_date)
    text = quote.quote_for_llm(result)
    remember(state, "calculate_quote", args, started, text, ok=result["ok"])
    return text


@function_tool
async def check_availability(context: RunContext, date: str, guests: int, area: str) -> str:
    """Check if we can cater an event on a date. Call this before promising any date.

    Args:
        date: event date as YYYY-MM-DD
        guests: number of guests
        area: venue area or town in English letters, e.g. "Jayanagar", "Mysuru"
    """
    state, started = context.userdata, time.time()
    say_filler(context, "check")
    result = await asyncio.to_thread(availability.check_availability, state.tenant_id, date, guests, area)
    remember(state, "check_availability", {"date": date, "guests": guests, "area": area}, started,
             result["message"], ok=result["available"])
    return availability.availability_for_llm(result)


@function_tool
async def create_tentative_booking(
    context: RunContext,
    customer_name: str,
    phone: str,
    event_type: str,
    event_date: str,
    venue_area: str,
    guests: int,
    package_code: PackageCode | None = None,
    notes: str = "",
) -> str:
    """Reserve a date for the customer (tentative, held 48 hours). Only after reading back the details and the customer agrees.

    Args:
        customer_name: customer's name
        phone: 10-digit mobile number, read back digit by digit first
        event_type: e.g. "Wedding", "Birthday party"
        event_date: YYYY-MM-DD
        venue_area: venue area or town in English letters
        guests: number of guests
        package_code: chosen package code, if any
        notes: anything else (custom menu wishes, Jain guests, timing)
    """
    state, started = context.userdata, time.time()
    say_filler(context, "booking")
    args = {"customer_name": customer_name, "phone": phone, "event_type": event_type, "event_date": event_date,
            "venue_area": venue_area, "guests": guests, "package_code": package_code, "notes": notes}
    result = await asyncio.to_thread(
        bookings.create_reservation, state.tenant_id, customer_name, phone, event_type, event_date, venue_area,
        guests, package_code, notes, state.call_id, state.customer_id, state.is_test)
    remember(state, "create_tentative_booking", args, started, result["message"], ok=result["ok"])
    return result["message"]


@function_tool
async def schedule_callback(context: RunContext, reason: str, preferred_time: str | None = None) -> str:
    """Ask our team to call the customer back (complaints, exceptions, discounts, big or far orders, wants a person).

    Args:
        reason: short English reason, e.g. "wants 20% discount", "complaint about cold food"
        preferred_time: when the customer wants the call, if they said
    """
    state, started = context.userdata, time.time()
    say_filler(context, "check")
    result = await asyncio.to_thread(
        bookings.schedule_callback, state.tenant_id, reason, preferred_time,
        state.customer.get("name"), state.customer.get("phone"), state.call_id, state.customer_id, state.is_test)
    remember(state, "schedule_callback", {"reason": reason, "preferred_time": preferred_time}, started, result["message"])
    return result["message"]


@function_tool
async def record_answer(context: RunContext, question_key: str, answer: str) -> str:
    """Save the customer's answer to one of the QUESTIONS STILL TO COVER as soon as they answer it.

    Args:
        question_key: the key of the question, exactly as listed (e.g. "food_rating")
        answer: the answer in short English, e.g. "5 - loved the holige"
    """
    state, started = context.userdata, time.time()
    keys = [q["key"] for q in state.pending_questions]
    if question_key not in keys:
        result = f"'{question_key}' is not a pending question. Pending: {', '.join(keys) or 'none'}"
        remember(state, "record_answer", {"question_key": question_key, "answer": answer}, started, result, ok=False)
        return result

    state.answers[question_key] = answer
    state.pending_questions = [q for q in state.pending_questions if q["key"] != question_key]
    # rebuild the prompt so the answered question disappears from QUESTIONS STILL TO COVER
    await context.session.current_agent.update_instructions(state.build_prompt())

    left = [q["key"] for q in state.pending_questions]
    result = f"Saved. Still to cover: {', '.join(left) if left else 'nothing, wrap up politely'}"
    remember(state, "record_answer", {"question_key": question_key, "answer": answer}, started, result)
    return result


@function_tool
async def end_call(context: RunContext, reason: str) -> str:
    """End the call. Only after you have said goodbye, or when the customer asks to end.

    Args:
        reason: short English reason, e.g. "customer said goodbye"
    """
    state, started = context.userdata, time.time()

    # Safety net (console test 2026-11-15: "ಏನಿಲ್ಲಮ್ಮ" was taken as goodbye and the call was cut).
    # If the customer's last words weren't clearly a goodbye, refuse ONCE and make the agent ask first.
    said_bye = any(word in state.last_customer_text.lower() for word in GOODBYE_WORDS)
    if not said_bye and not state.asked_before_ending:
        state.asked_before_ending = True
        result = ("Not ended: the customer did not clearly say goodbye. Ask if there is anything else you can "
                  "help with, and end only after they say goodbye.")
        remember(state, "end_call", {"reason": reason}, started, result, ok=False)
        return result

    remember(state, "end_call", {"reason": reason}, started, "ending")
    state.ended_by = "agent"
    context.session.shutdown(drain=True)   # let the goodbye finish playing, then close
    return "Call ended."


GOODBYE_WORDS = ["bye", "thank", "that's all", "thats all", "nothing else", "no more",
                 "ಧನ್ಯವಾದ", "ಬೈ", "ಸಾಕು", "धन्यवाद", "शुक्रिया", "बाय", "बस", "நன்றி", "போதும்", "ధన్యవాదాలు", "చాలు"]


@function_tool
async def switch_language(context: RunContext, language: Literal["kn-IN", "en-IN", "hi-IN", "ta-IN", "te-IN"]) -> str:
    """Call when the customer ASKS you to speak a particular language (e.g. "please talk in Kannada").

    Args:
        language: kn-IN Kannada, en-IN English, hi-IN Hindi, ta-IN Tamil, te-IN Telugu
    """
    state, started = context.userdata, time.time()
    agent = context.session.current_agent
    new_language = agent.switcher.force(language)
    await agent.apply_language(new_language, "asked")
    result = f"Switched. Reply in {prompts.LANGUAGE_NAMES.get(new_language, new_language)} from now on."
    remember(state, "switch_language", {"language": language}, started, result)
    return result


ALL_TOOLS = [search_knowledge_base, calculate_quote, check_availability, create_tentative_booking,
             schedule_callback, record_answer, switch_language, end_call]


def enabled_tools(config):
    """Only the tools switched on in agent_configs.tools_enabled (all of them if not set)."""
    names = (config or {}).get("tools_enabled")
    if not names:
        return ALL_TOOLS
    return [t for t in ALL_TOOLS if t.info.name in names]
