# The voice agent (LiveKit worker, agent_name="amrutha").
#
# Run from the backend folder (venv active):
#     python -m agent.agent console     -> talk to it with your laptop mic + speakers
#     python -m agent.agent dev         -> connect to LiveKit Cloud and wait for jobs
#
# Console testing of other call types (no dispatch metadata in console mode):
#     $env:CALL_TYPE="post_event_feedback"; $env:CUSTOMER_ID="C001"; python -m agent.agent console
#     (CALL_TYPE: inbound | post_event_feedback | enquiry_followup | pre_event_confirmation,
#      CUSTOMER_ID: a customer_id from backend/data/sample_customers.csv)

import asyncio
import csv
import json
import logging
import os
import uuid

from dotenv import load_dotenv

from app.core.config import REPO_ROOT, settings

# LiveKit and the Sarvam plugin read their keys from environment variables
load_dotenv(REPO_ROOT / ".env")

from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli  # noqa: E402
from livekit.plugins import sarvam  # noqa: E402

from agent import prompts  # noqa: E402
from agent.language import LanguageSwitcher, voice_language_for_reply  # noqa: E402
from agent.tools import CallState, enabled_tools  # noqa: E402
from app.db.session import get_sync_conn  # noqa: E402
from app.repos import agent_config_repo  # noqa: E402
from app.services import campaign_types  # noqa: E402

log = logging.getLogger("amrutha")

# Used when agent_configs.voices in the database has no voice for a language
DEFAULT_VOICES = {
    "kn-IN": "chaitra_kn_conversation",
    "hi-IN": "chaitra_hi_customer",
    "en-IN": "ishita_en_customer",
    "te-IN": "kavitha_te_conversation",
    "ta-IN": "gokul_ta_narration",
}

# Business words, so the speech-to-text recognises them better
STT_HINT = "Amrith Sagar, catering, holige, bale ele oota, Basavanagudi, Jain food, muhurtham, wedding, guests"


# ---------------------------------------------------------------- setting up a call
def load_config(tenant_id):
    with get_sync_conn() as conn:
        return agent_config_repo.get_active(conn, tenant_id) or {}


def sample_customer(customer_id):
    """Console testing: take a customer row from the sample CSV."""
    path = settings.path("./backend/data/sample_customers.csv")
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["customer_id"] == customer_id:
                return row
    raise ValueError(f"customer {customer_id} not in sample_customers.csv")


def read_job_metadata(ctx):
    """Dispatch metadata (see docs/api_contracts.md). Console mode has none, so use env vars instead."""
    if ctx.job.metadata:
        return json.loads(ctx.job.metadata)
    call_type = os.getenv("CALL_TYPE", "inbound")
    customer = sample_customer(os.getenv("CUSTOMER_ID", "C001")) if call_type != "inbound" else {}
    return {"tenant_id": settings.TENANT_ID, "call_type": call_type, "customer": customer, "is_test": True}


def new_call_state(meta, config):
    call_type = meta.get("call_type", "inbound")
    customer = meta.get("customer") or {}
    questions = meta.get("questions") or campaign_types.questions(call_type)
    # outbound: reply in the customer's known language; inbound: not decided yet (follow the caller)
    language = customer.get("language") if customer.get("language") in DEFAULT_VOICES else None
    return CallState(
        tenant_id=meta.get("tenant_id") or settings.TENANT_ID,
        call_type=call_type,
        direction="inbound" if call_type == "inbound" else "outbound",
        customer=customer,
        pending_questions=list(questions),
        config=config,
        current_language=language,
        is_test=meta.get("is_test", False),
        session_id=str(uuid.uuid4()),
        call_id=meta.get("call_id"),
        customer_id=meta.get("customer_id"),
    )


# ---------------------------------------------------------------- the agent
class Amrutha(Agent):
    def __init__(self, state):
        super().__init__(instructions=state.build_prompt(), tools=enabled_tools(state.config))
        self.state = state
        self.switcher = LanguageSwitcher(state.current_language)
        self.voices = {**DEFAULT_VOICES, **(state.config.get("voices") or {})}
        self.voice_language = state.current_language or "kn-IN"   # the voice the TTS was created with

    async def on_enter(self):
        # fixed opening line, so the AI + transcription disclosure is always said first
        self.session.say(prompts.opening_line(self.state.direction, self.state.config))

    async def on_customer_sentence(self, lang, text):
        """Every final customer sentence comes here (from STT in calls, from the text in evals)."""
        if lang:
            self.state.last_heard_language = lang
        new_language = self.switcher.observe(lang, text)
        if new_language and new_language != self.state.current_language:
            log.info("LANGUAGE switch %s -> %s", self.state.current_language, new_language)
            self.state.current_language = new_language
            await self.update_instructions(self.state.build_prompt())   # CURRENT LANGUAGE in the prompt

            # The prompt's language rule sits far up at the top; a short note near the end of the
            # conversation is followed much more reliably on the very next reply.
            name = prompts.LANGUAGE_NAMES.get(new_language, new_language)
            chat = self.chat_ctx.copy()
            only = "plain English, no Indian-language words or script" if new_language == "en-IN" else name
            chat.add_message(role="system", content=f"Language note: the customer is now speaking {name}. "
                                                    f"Reply only in {only} from now on.")
            await self.update_chat_ctx(chat)

    async def stt_node(self, audio, model_settings):
        # pass Sarvam's transcripts through; each final sentence feeds the language switcher
        async for event in Agent.default.stt_node(self, audio, model_settings):
            if getattr(event, "type", None) == "final_transcript" and event.alternatives:
                heard = event.alternatives[0]
                log.info("STT final | lang=%s | %s", heard.language, heard.text)
                await self.on_customer_sentence(heard.language, heard.text)
            yield event

    async def tts_node(self, text, model_settings):
        # Look at the first few words of the reply, pick the voice from their script, then speak it all.
        chunks = text.__aiter__()
        first = ""
        async for piece in chunks:
            first += piece
            if sum(ch.isalpha() for ch in first) >= 12:   # enough letters to know the script
                break

        self.set_voice(voice_language_for_reply(first, self.state.current_language))

        async def whole_text():
            yield first
            async for piece in chunks:   # the rest of the same reply
                yield piece

        async for frame in Agent.default.tts_node(self, whole_text(), model_settings):
            yield frame

    def set_voice(self, language):
        if language == self.voice_language:
            return
        self.session.tts.update_options(target_language_code=language, speaker=self.voices[language])
        log.info("VOICE %s -> %s (%s)", self.voice_language, language, self.voices[language])
        self.voice_language = language


# ---------------------------------------------------------------- Sarvam STT / LLM / TTS
def make_stt():
    if settings.STT_CLASS == "realtime":
        return sarvam.STTRealtime(language="auto", stream_type="fast", mode=settings.STT_MODE, prompt=STT_HINT)
    return sarvam.STT(language="unknown", model=settings.STT_MODEL, mode=settings.STT_MODE, prompt=STT_HINT)


def make_llm(call_id):
    options = {
        "model": settings.LIVE_LLM,
        "max_tokens": settings.LIVE_LLM_MAX_TOKENS,
        "temperature": 0.3,
        "extra_headers": {"x-session-affinity": call_id},   # lets Sarvam cache the prompt between turns
    }
    if settings.LIVE_LLM_REASONING:   # conversations model rejects "none", so only send if set
        options["reasoning_effort"] = settings.LIVE_LLM_REASONING
    return sarvam.LLM(**options)


def make_tts(state):
    voices = {**DEFAULT_VOICES, **(state.config.get("voices") or {})}
    language = state.current_language or "kn-IN"   # starting voice; tts_node switches it per reply
    return sarvam.TTS(
        model=settings.TTS_MODEL,
        target_language_code=language,
        speaker=voices[language],
        speech_sample_rate=settings.TTS_SAMPLE_RATE,
        dict_id=settings.SARVAM_DICT_ID or None,
    )


# ---------------------------------------------------------------- latency print
def print_latency(event, last_user):
    msg = event.item
    role = getattr(msg, "role", None)
    m = getattr(msg, "metrics", None) or {}
    if role == "user":
        last_user["eou"] = m.get("end_of_turn_delay")
        return
    if role == "assistant":
        def ms(x):
            return f"{x * 1000:.0f}ms" if x is not None else "-"
        log.info("LATENCY | total=%s | end-of-turn=%s llm_first_token=%s tts_first_audio=%s",
                 ms(m.get("e2e_latency")), ms(last_user.get("eou")), ms(m.get("llm_node_ttft")), ms(m.get("tts_node_ttfb")))


# ---------------------------------------------------------------- entrypoint
server = AgentServer()


@server.rtc_session(agent_name=settings.AGENT_NAME)
async def entrypoint(ctx: JobContext):
    meta = read_job_metadata(ctx)
    config = await asyncio.to_thread(load_config, meta.get("tenant_id") or settings.TENANT_ID)
    state = new_call_state(meta, config)
    log.info("New %s call %s | customer=%s | questions=%d | language=%s",
             state.call_type, state.session_id, state.customer.get("name", "-"), len(state.pending_questions), state.current_language)

    session = AgentSession(
        userdata=state,                  # tools read the call state from context.userdata
        stt=make_stt(),
        llm=make_llm(state.session_id),
        tts=make_tts(state),
        vad=None,                        # Sarvam STT does voice detection itself
        turn_handling={"turn_detection": "stt", "endpointing": {"min_delay": 0.07}},
    )

    last_user = {}
    session.on("conversation_item_added", lambda ev: print_latency(ev, last_user))
    session.on("close", lambda ev: log.info("Call ended | answers=%s | tools used=%d", state.answers, len(state.tool_log)))

    await session.start(agent=Amrutha(state), room=ctx.room)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cli.run_app(server)
