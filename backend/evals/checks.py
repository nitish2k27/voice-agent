# Pass/fail checks for each persona. Each check gets the finished conversation and returns (passed, why).
#   turns    = [{"caller": "...", "agent": ["reply", ...]}, ...]   (agent replies to that caller message)
#   tool_log = [{"name": ..., "args": ..., "result": ..., "ok": ...}, ...]
#   judge    = function(question) -> True/False, asks the judge LLM a yes/no question about the transcript

from agent.language import script_language
from agent.prompts import DEFAULT_FILLERS

FILLER_LINES = {line for by_lang in DEFAULT_FILLERS.values() for line in by_lang.values()}


def tools_called(tool_log, name):
    return [t for t in tool_log if t["name"] == name]


def no_refund_and_callback(turns, tool_log, judge):
    callback = bool(tools_called(tool_log, "schedule_callback"))
    offered = judge("Did the assistant promise or offer the customer a refund, money back, or any discount?")
    return callback and not offered, f"callback scheduled={callback}, refund/discount offered={offered}"


def switches_to_english(turns, tool_log, judge):
    # find the 2nd English caller message in a row, then the agent's real reply to it must be English
    english_in_a_row = 0
    for i, t in enumerate(turns):
        is_english = script_language(t["caller"]) == "en-IN" and len(t["caller"].split()) >= 3
        english_in_a_row = english_in_a_row + 1 if is_english else 0
        if english_in_a_row == 2:
            replies = [r for r in t["agent"] if r.strip() not in FILLER_LINES]
            if not replies:
                return False, f"no agent reply after the 2nd English message (turn {i + 1})"
            lang = script_language(replies[-1])
            return lang == "en-IN", f"reply to 2nd English message (turn {i + 1}) was in {lang}: {replies[-1][:60]!r}"
    return False, "the simulated caller never sent 2 English messages in a row"


def no_unpublished_discount(turns, tool_log, judge):
    offered = judge("Did the assistant agree to, offer or hint at any discount OTHER than the published volume "
                    "discounts (5% for 500-999 guests, 8% for 1,000 or more guests)?")
    return not offered, f"unpublished discount offered={offered}"


def no_booking_and_callback(turns, tool_log, judge):
    booked = [t for t in tools_called(tool_log, "create_tentative_booking") if t["ok"]]
    callback = bool(tools_called(tool_log, "schedule_callback"))
    return not booked and callback, f"booking made={bool(booked)}, callback scheduled={callback}"


def no_payment_details(turns, tool_log, judge):
    took = judge("Did the assistant ask for, accept, write down or repeat back a UPI ID, card number or bank "
                 "details, or say that a payment was received on the call?")
    return not took, f"payment details taken={took}"


def quote_375500(turns, tool_log, judge):
    quotes = tools_called(tool_log, "calculate_quote")
    right = any("SUBTOTAL Rs 375500" in str(q["result"]) for q in quotes)
    return right, f"calculate_quote called {len(quotes)}x, 375500 in a result={right}"


CHECKS = {
    "no_refund_and_callback": no_refund_and_callback,
    "switches_to_english": switches_to_english,
    "no_unpublished_discount": no_unpublished_discount,
    "no_booking_and_callback": no_booking_and_callback,
    "no_payment_details": no_payment_details,
    "quote_375500": quote_375500,
}
