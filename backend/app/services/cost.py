# What a call cost us in Sarvam API money (₹, before GST). Rates come from the pricing_rates table.
#
# cost = STT minutes x STT rate
#      + TTS characters / 1000 x TTS rate
#      + uncached input tokens / 1M x input rate + cached tokens / 1M x cached rate + output tokens / 1M x output rate


def usage_totals(session_usage):
    """Add up LiveKit's session.usage (one entry per model) into the numbers we store on the call."""
    totals = {"stt_seconds": 0.0, "tts_characters": 0, "llm_input_tokens": 0,
              "llm_cached_tokens": 0, "llm_output_tokens": 0}
    for u in getattr(session_usage, "model_usage", []) or []:
        kind = getattr(u, "type", "")
        if kind == "stt_usage":
            totals["stt_seconds"] += u.audio_duration
        elif kind == "tts_usage":
            totals["tts_characters"] += u.characters_count
        elif kind == "llm_usage":
            totals["llm_input_tokens"] += u.input_tokens
            totals["llm_cached_tokens"] += u.input_cached_tokens
            totals["llm_output_tokens"] += u.output_tokens
    return totals


def call_cost_inr(totals, rates):
    uncached = max(totals["llm_input_tokens"] - totals["llm_cached_tokens"], 0)
    cost = (
        totals["stt_seconds"] / 60 * rates.get("sarvam_stt", 0)
        + totals["tts_characters"] / 1000 * rates.get("sarvam_tts_v4_flash", 0)
        + uncached / 1_000_000 * rates.get("sarvam_llm_in", 0)
        + totals["llm_cached_tokens"] / 1_000_000 * rates.get("sarvam_llm_cached", 0)
        + totals["llm_output_tokens"] / 1_000_000 * rates.get("sarvam_llm_out", 0)
    )
    return round(cost, 4)
