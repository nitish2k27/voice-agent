# Milestone 3: language switching rules. Run from backend/:  pytest tests/test_language.py -v
from agent.language import LanguageSwitcher, script_language, voice_language_for_reply


def test_script_detection():
    assert script_language("ನಮಸ್ಕಾರ, ಹೇಗಿದ್ದೀರಾ?") == "kn-IN"
    assert script_language("नमस्ते आप कैसे हैं") == "hi-IN"
    assert script_language("வணக்கம் எப்படி இருக்கீங்க") == "ta-IN"
    assert script_language("నమస్కారం ఎలా ఉన్నారు") == "te-IN"
    assert script_language("Hello, how are you?") == "en-IN"
    assert script_language("ಸರಿ, advance payment ಬಗ್ಗೆ ನಮ್ಮ team ಕಾಲ್ ಮಾಡ್ತಾರೆ") == "kn-IN"   # mostly Kannada letters
    assert script_language("123 ...") is None


def test_switch_needs_two_sentences_in_a_row():
    s = LanguageSwitcher("kn-IN")
    assert s.observe("en-IN", "can you tell me the price") is None      # 1st English sentence: not yet
    assert s.observe("en-IN", "for three hundred guests please") == "en-IN"   # 2nd in a row: switch
    assert s.current == "en-IN"


def test_one_english_sentence_inside_kannada_does_not_switch():
    s = LanguageSwitcher("kn-IN")
    assert s.observe("en-IN", "okay what is the price") is None
    assert s.observe("kn-IN", "ಮುನ್ನೂರು ಜನಕ್ಕೆ ಎಷ್ಟಾಗುತ್ತೆ ಹೇಳಿ") is None   # back to Kannada resets the count
    assert s.observe("en-IN", "and the travel charge please") is None
    assert s.current == "kn-IN"


def test_short_sentences_are_ignored():
    s = LanguageSwitcher("kn-IN")
    assert s.observe("en-IN", "okay") is None
    assert s.observe("en-IN", "yes please") is None
    assert s.observe("en-IN", "fine") is None
    assert s.current == "kn-IN"


def test_inbound_first_sentence_decides():
    s = LanguageSwitcher(None)
    assert s.observe("hi-IN", "मुझे शादी के लिए खाना चाहिए") == "hi-IN"


def test_unsupported_language_falls_back_to_english():
    s = LanguageSwitcher(None)
    assert s.observe("ml-IN", "എനിക്ക് ഒരു കല്യാണത്തിന് ഭക്ഷണം വേണം") == "en-IN"


def test_kannada_to_english_to_hindi():
    s = LanguageSwitcher("kn-IN")
    s.observe("en-IN", "I want to know the price")
    assert s.observe("en-IN", "for a wedding next month") == "en-IN"
    s.observe("hi-IN", "मुझे जैन खाना भी चाहिए")
    assert s.observe("hi-IN", "चालीस लोगों के लिए होगा") == "hi-IN"


def test_voice_follows_reply_script():
    assert voice_language_for_reply("ನಮಸ್ಕಾರ, ಹೇಳಿ", "en-IN") == "kn-IN"     # Kannada text -> Kannada voice
    assert voice_language_for_reply("नमस्ते, बताइए", "kn-IN") == "hi-IN"      # never Kannada voice on Hindi text
    assert voice_language_for_reply("Sure, let me check", "kn-IN") == "kn-IN"  # code-mix: keep Kannada voice
    assert voice_language_for_reply("Sure, let me check", "en-IN") == "en-IN"
    assert voice_language_for_reply("Sure, let me check", None) == "en-IN"
    assert voice_language_for_reply("എന്താണ്", "kn-IN") == "en-IN"           # Malayalam text: no voice -> English
