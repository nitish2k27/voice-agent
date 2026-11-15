# Builds the agent's system prompt from agent/prompts/<version>.txt.
# Static parts first (role, tools, codes, rules), changing parts last (date, customer, questions, language),
# so the start of the prompt stays the same and Sarvam can cache it.

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.services import campaign_types
from app.services.quote import load_pricing

PROMPTS_DIR = Path(__file__).parent / "prompts"

LANGUAGE_NAMES = {"kn-IN": "Kannada", "en-IN": "English", "hi-IN": "Hindi", "ta-IN": "Tamil", "te-IN": "Telugu"}

# Filler lines spoken by slow tools. agent_configs.fillers in the database can override these.
DEFAULT_FILLERS = {
    "check": {
        "en-IN": "One second, let me check that for you.",
        "kn-IN": "ಒಂದು ನಿಮಿಷ, ಚೆಕ್ ಮಾಡ್ತೀನಿ.",
        "hi-IN": "एक सेकंड, मैं चेक करती हूँ।",
        "ta-IN": "ஒரு நிமிஷம், சரி பார்க்கிறேன்.",
        "te-IN": "ఒక్క నిమిషం, చెక్ చేస్తాను.",
    },
    "booking": {
        "en-IN": "Okay, I'm noting the booking now.",
        "kn-IN": "ಸರಿ, ಬುಕಿಂಗ್ ನೋಟ್ ಮಾಡ್ತೀನಿ.",
        "hi-IN": "ठीक है, मैं बुकिंग नोट कर रही हूँ।",
        "ta-IN": "சரி, புக்கிங் குறித்துக்கொள்கிறேன்.",
        "te-IN": "సరే, బుకింగ్ నోట్ చేస్తున్నాను.",
    },
}

# The opening always: (1) says it's an AI, (2) says we keep a written record, (3) asks which language.
# (Old text "This call is transcribed for quality. Kannada or English..." sounded like
#  "I can transcribe in Kannada" in the 2026-11-15 voice test.)
OPENINGS = {
    "inbound": "Namaskara! I'm {persona}, the AI assistant of {business}. "
               "We keep a written record of this call for quality. "
               "Which language are you comfortable with: Kannada, English, Hindi, Tamil or Telugu?",
    "outbound": "Namaskara! I'm {persona}, an AI assistant calling from {business}. "
                "We keep a written record of this call for quality. "
                "Is this a good time to talk for two minutes? Which language are you comfortable with?",
    "outbound_known_language": "Namaskara! I'm {persona}, an AI assistant calling from {business}. "
                               "We keep a written record of this call for quality. "
                               "Is this a good time to talk for two minutes? Shall we talk in {language}, "
                               "or is another language better for you?",
}


def today_text():
    return datetime.now(ZoneInfo(settings.TIMEZONE)).strftime("%A, %d %B %Y")


def package_list():
    lines = []
    for p in load_pricing()["packages"]:
        lines.append(f"- {p['code']}: {p['name']}, minimum {p['min_guests']} guests")
    return "\n".join(lines)


def add_on_list():
    return "\n".join(f"- {a['code']}: {a['name']}" for a in load_pricing()["add_ons"])


def customer_block(customer):
    if not customer:
        return "Unknown caller (inbound). Ask for name and phone only when needed for a booking or callback."
    keys = ["name", "phone", "event_type", "event_date", "venue_area", "package", "guests", "notes"]
    lines = [f"- {k}: {customer[k]}" for k in keys if customer.get(k)]
    if customer.get("language"):
        lines.append(f"- language at the start of the call: {customer['language']} (follow CURRENT LANGUAGE below)")
    return "\n".join(lines)


def pending_questions_text(questions):
    if not questions:
        return "None. Help with anything else the customer asks, then wrap up politely."
    return "\n".join(f"- {q['key']}: {q['text']}" for q in questions)


def build_prompt(call_type, customer, pending_questions, current_language, config=None, version=None):
    """config = the agent_configs row (persona_name, rules ...) or None for defaults."""
    config = config or {}
    version = version or config.get("prompt_version") or settings.PROMPT_VERSION
    template = (PROMPTS_DIR / f"{version}.txt").read_text(encoding="utf-8")
    extra_rules = "\n".join(f"- {r}" for r in (config.get("rules") or []))

    return template.format(
        persona_name=config.get("persona_name") or "Amrutha",
        business_name="Amrith Sagar Catering",
        package_list=package_list(),
        add_on_list=add_on_list(),
        extra_rules=extra_rules,
        call_type_block=campaign_types.call_type_block(call_type),
        today=today_text(),
        customer_block=customer_block(customer),
        pending_questions=pending_questions_text(pending_questions),
        current_language=language_text(current_language),
    )


def language_text(current_language):
    # None = not decided yet (inbound call before Milestone 3's language switching sets it)
    if not current_language:
        return "Reply in the language of the customer's last message."
    name = LANGUAGE_NAMES.get(current_language, current_language)
    if current_language == "en-IN":
        return ("English. The customer is speaking English now: reply ONLY in plain English, with no Kannada, "
                "Hindi or other Indian-language words or script, even if earlier turns of this call were in another language.")
    return (f"{name}. The customer is speaking {name} now: reply ONLY in {name} (in its own script), even if earlier "
            f"turns of this call were in another language. Mixing in English words is fine.")


def opening_line(direction, config=None, known_language=None):
    """known_language = the customer's language from the CSV (outbound), so we can offer it first."""
    config = config or {}
    custom = config.get("greeting_outbound" if direction == "outbound" else "greeting_inbound")
    if custom:
        return custom
    key = direction
    if direction == "outbound" and known_language in LANGUAGE_NAMES:
        key = "outbound_known_language"
    return OPENINGS[key].format(persona=config.get("persona_name") or "Amrutha", business="Amrith Sagar Catering",
                                language=LANGUAGE_NAMES.get(known_language, ""))


def filler(key, language, config=None):
    # database fillers win, but only for the languages they define
    by_language = dict(DEFAULT_FILLERS.get(key, {}))
    by_language.update(((config or {}).get("fillers") or {}).get(key, {}))
    return by_language.get(language) or by_language.get("en-IN") or DEFAULT_FILLERS["check"]["en-IN"]
