# Mid-call language switching (Milestone 3).
#
# Two separate decisions:
#   1. Which language the LLM is TOLD to reply in (CURRENT LANGUAGE in the prompt).
#      -> changes only after 2 sentences in a row (3+ words each) in the same new language,
#         so one English word inside a Kannada sentence doesn't flip it.
#   2. Which VOICE reads a reply.
#      -> picked from the script of the reply text itself, so a Kannada voice never reads Hindi text.

# Bulbul v4 Flash has voices for these. Others (Malayalam, Odia, ...) fall back to English.
TTS_LANGUAGES = {"kn-IN", "en-IN", "hi-IN", "ta-IN", "te-IN"}
FALLBACK_LANGUAGE = "en-IN"

# Unicode block of each script -> language code
SCRIPT_RANGES = [
    (0x0C80, 0x0CFF, "kn-IN"),   # Kannada
    (0x0900, 0x097F, "hi-IN"),   # Devanagari (Hindi, Marathi)
    (0x0B80, 0x0BFF, "ta-IN"),   # Tamil
    (0x0C00, 0x0C7F, "te-IN"),   # Telugu
    (0x0D00, 0x0D7F, "ml-IN"),   # Malayalam
    (0x0B00, 0x0B7F, "od-IN"),   # Odia
    (0x0980, 0x09FF, "bn-IN"),   # Bengali
    (0x0A80, 0x0AFF, "gu-IN"),   # Gujarati
]

SWITCH_AFTER = 2      # sentences in a row
MIN_WORDS = 3         # shorter sentences ("ok", "yes please") don't count


def script_language(text):
    """Language of the script most letters are written in. Latin letters -> 'en-IN'. No letters -> None."""
    counts = {}
    for ch in text:
        code = ord(ch)
        if ch.isascii():
            if ch.isalpha():
                counts["en-IN"] = counts.get("en-IN", 0) + 1
            continue
        for start, end, lang in SCRIPT_RANGES:
            if start <= code <= end:
                counts[lang] = counts.get(lang, 0) + 1
                break
    if not counts:
        return None
    return max(counts, key=counts.get)


def speakable(lang):
    """Language the agent can actually speak (has a TTS voice)."""
    return lang if lang in TTS_LANGUAGES else FALLBACK_LANGUAGE


class LanguageSwitcher:
    """Decides the language the LLM should reply in, from the customer's sentences."""

    def __init__(self, current=None):
        self.current = current      # None = not decided yet (inbound call start)
        self.candidate = None
        self.count = 0

    def observe(self, lang, text):
        """Call with every final customer sentence. Returns the new language if it just switched, else None."""
        if not lang or len(text.split()) < MIN_WORDS:
            return None
        lang = speakable(lang)

        if self.current is None:                 # first proper sentence of the call decides
            self.current = lang
            return lang
        if lang == self.current:                 # still the same language: forget any half-switch
            self.candidate, self.count = None, 0
            return None
        if lang == self.candidate:
            self.count += 1
        else:
            self.candidate, self.count = lang, 1
        if self.count >= SWITCH_AFTER:
            self.current, self.candidate, self.count = lang, None, 0
            return lang
        return None


def voice_language_for_reply(reply_text, current_language):
    """Which TTS language should read this reply?

    Native script (Kannada, Hindi ...) -> that language.
    Latin script -> English, unless the call is in Kannada/Hindi/etc. (then it's code-mixing:
    keep that voice, it reads English words fine).
    """
    lang = script_language(reply_text)
    if lang is None:
        return speakable(current_language or "kn-IN")
    if lang == "en-IN" and current_language and current_language != "en-IN":
        return speakable(current_language)
    return speakable(lang)
