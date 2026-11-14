# Sarvam stack: what we use, when, and how (with LiveKit)

Source: the Sarvam API reference and guides (https://docs.sarvam.ai/api-reference/introduction), plus the LiveKit Sarvam plugin reference, read on 2026-11-12. Anything marked **verify** was unclear or inconsistent in the docs; check it in the installed package during the Milestone 1 spike.

---

## 1. One-page summary

| Sarvam module | Model ID | API used | Where in our system | Version |
|---|---|---|---|---|
| Speech-to-text (live) | `saaras:v4` | streaming WebSocket (through the LiveKit plugin) | customer speech → native-script text + detected language + end-of-turn | v1 |
| LLM (live) | `sarvam-105b-conversations` | `/v1/chat/completions`, streamed (SSE), tool calling | the conversation itself and all tool calls | v1 |
| Text-to-speech (live) | `bulbul:v4-flash` | WebSocket (through the LiveKit plugin) | agent reply text → voice; speaker switched per language | v1 |
| Pronunciation dictionary | (for v3 / v4-flash) | REST, once at setup | "Amrith Sagar", "holige", "bale ele oota", "Basavanagudi" pronounced right | v1 (nice to have) |
| Speech-to-text batch | `saaras:v4` + `with_diarization` | async job | clean speaker-labelled transcript from a recording | only if recording is on (v1.5/v2) |
| Translate | `sarvam-translate:v1` (22 languages) / `mayura:v1` | REST | English transcript for the owner | v2 (v1 uses Gemini, free) |
| Transliterate | `mayura` family | REST | customer names/addresses from native script → Latin for Sheets/CRM | v2 |
| Language identification | `text-lid` | REST | not needed live (we detect script locally); can check post-call | optional |
| LLM (post-call) | `sarvam-105b` (reasoning on) | `/v2/chat/completions` | owner summary in English **and** native script | v2 (v1 uses Gemini, free) |

**Not used:** Sarvam Voice Agents (their managed platform, about ₹3/min; we build our own on LiveKit), voice cloning, dubbing, Document AI. EmbeddingGemma 2 is "provisioned throughput, enabled per organisation", so we keep the local `bge-small-en-v1.5`.

---

## 2. The three ways to call Sarvam

| Type | What it is | Limits that matter | Our use |
|---|---|---|---|
| **REST** (synchronous) | one request, one response | STT: audio < 30 s per request. TTS: ≤ 2,500 chars | `check_env.py`, one-off tests, pre-generating filler audio (v2) |
| **Streaming** (WebSocket; TTS also has HTTP streaming) | audio/text flows both ways while the person talks; partial results | STT WS: 16 kHz or 8 kHz mono PCM/WAV only. TTS WS: ≤ 2,500 chars per message, < 500 recommended | **every live call** (STT + TTS via the LiveKit plugin) |
| **Batch** (async jobs) | upload files, start a job, poll or receive a webhook, download | up to 2 h per file, 20 files per job; diarization up to 20 speakers | only if we keep recordings |

There is **no separate trial plan** in the docs. Pay-as-you-go is the entry tier and includes WebSockets (20 concurrent STT streams, 60 concurrent TTS streams). New verified accounts get **₹100 free credit** that never expires, about 80 minutes of calls at our rate.

---

## 3. Speech-to-text: Saaras

### Models and modes
- `saaras:v4` is the recommended default: 22 Indian languages + Indian English + Global English, code-mixed speech, automatic language detection.
- `saaras:v3-realtime` is the default model of the new realtime WebSocket, and `saaras:v4` is also allowed there.
- `mode` (works on v3 and v4):

| mode | Output | Our use |
|---|---|---|
| `transcribe` | text in the spoken language, native script | **live calls** (the LLM needs the customer's real words) |
| `translate` | English text from any Indian-language speech | not live (we'd lose the customer's language). Possible for batch re-transcription to English |
| `verbatim` | word-for-word including fillers ("umm") | not used |
| `translit` | romanized (Latin script) | not used (TTS quality drops with romanized input) |
| `codemix` | code-mixed output (e.g. English words kept in Latin inside Kannada) | worth testing in the spike for Kanglish callers |

### Two plugin classes in `livekit-plugins-sarvam`

| Class | Endpoint | Language auto-detect | Notes |
|---|---|---|---|
| `sarvam.STT` (used in Sarvam's LiveKit guide) | streaming WS (exact endpoint not shown in the reference) | `language="unknown"` (as in the guide) | server-side VAD; options `high_vad_sensitivity`, `prompt`, `flush_signal` (don't set it), speech-threshold tuning |
| `sarvam.STTRealtime` (newer) | `wss://api.sarvam.ai/speech-to-text-realtime/ws` | `language="auto"` | true partial transcripts (`stream_type="fast"`), live `config.update` mid-call, VAD tuning (`vad_min_silence_ms` …), `prompt`, `return_timestamps` |

**Plan:** start with `sarvam.STT(language="unknown", model="saaras:v4", mode="transcribe")` exactly as the guide shows. In the spike, also try `STTRealtime(language="auto", model="saaras:v4", stream_type="fast")`, compare latency and accuracy, and keep the winner (one config switch, `STT_CLASS`). **Verify:** that the classic `STT` accepts `"unknown"` in the installed version.

### What we get back and how we use it
- Each final transcript gives `text`, `language` and `language_confidence` (`transcript.final`). In LiveKit that is `SpeechData.language`, with confidence in metadata.
  - We feed `language` into the hysteresis (switch after 2 finals of ≥ 3 words).
  - We store both in the transcript JSON (`lang`, `lang_conf`).
- Turn-taking: Sarvam's server-side VAD decides end of speech (`vad.speech_start` / `vad.speech_end`). LiveKit is set to `turn_detection="stt"` with `vad=None`, so there is only one VAD.
- **Domain words:** pass a `prompt` with business words ("Amrith Sagar, holige, bale ele oota, Basavanagudi, Jain, muhurtham, SI-BALE") to bias recognition. Saaras v4 batch also supports `keyterms` (up to 50 terms). **Verify** whether keyterms are accepted in the live plugin.
- Billing: STT costs ₹0.49 per minute of audio streamed, billed per second (`session.end` reports `audio_duration_s`). We count this as `calls.stt_seconds`.

### Phone audio (v1.5)
The STT WebSocket accepts `sample_rate=8000`, so Plivo/SIP audio works without resampling. Re-check accuracy at 8 kHz.

---

## 4. LLM: sarvam-105b-conversations

| Item | Value from the docs | What we do |
|---|---|---|
| Model | `sarvam-105b-conversations`: voice-tuned, 32K context, 10 Indian languages + English (native, romanized, code-mixed) | `LIVE_LLM` |
| Endpoint | `/v1/chat/completions` only (the plugin picks it automatically) | — |
| Tool calling | documented on `/v1` (`tools`, `tool_choice`: none / auto / required / named). The v2 model list does not mention tools for this model | **must pass the Milestone 1 test** (10 tries) |
| Reasoning | **tested 2026-11-13:** `"none"` is rejected (400, only low/medium/high); with the field omitted, no reasoning tokens or `reasoning_content` come back | do **not** send `reasoning_effort` (leave `LIVE_LLM_REASONING` empty); keep checking `reasoning_tokens` in usage |
| `max_tokens` | default 2,048 | set ~250 (1–2 spoken sentences); tool-call turns need room for the arguments |
| Temperature | default 0.2 with reasoning off | keep 0.2–0.4 (stable facts, natural tone) |
| Prompt caching | send header `x-session-affinity: <same id every turn>`; hits show in `usage.prompt_tokens_details.cached_tokens` (`null` = miss) | pass `extra_headers={"x-session-affinity": call_id}` to `sarvam.LLM`; the static prompt prefix goes first (already the rule). Cached input costs ₹5 instead of ₹15 per 1M tokens |
| Streaming usage | `stream_options: {"include_usage": true}` gives a final usage chunk with empty `choices` | read token counts for `calls.llm_*_tokens` (LiveKit's LLM metrics usually expose them too) |
| Price | ₹15 in / ₹5 cached / ₹60 out per 1M tokens | ≈ ₹0.10–0.25 per call minute |
| Rate limit (PAYG) | 60 requests/min for the Sarvam 105B models | fine for 1–2 calls; **throttle the text-mode eval runner** |

**Fallback if tool calling is unreliable** (still one Sarvam key and bill): `sarvam-105b` with `reasoning_effort="none"` (`/v2`, documented for agentic tool use), or the Token Factory models with documented tool calling, e.g. `deepseekv4.1-flash-1017-interactive` (reasoning off with `none`, >200 tokens/s) or `gemma4` (reasoning off by default). Set it in `LIVE_LLM_FALLBACK`. **Verify** that the plugin's model list accepts it, or pass `base_url`.

---

## 5. Text-to-speech: Bulbul v4 Flash

### Model and transport
- `bulbul:v4-flash` is "recommended for new integrations": 200+ persona voices at ₹1 per 1,000 characters. (v3 costs ₹3 per 1,000.)
- Languages: hi, en, en-hi mix, bn, gu, **kn**, mr, pa, **ta**, **te**. No Malayalam or Odia → fall back to en-IN.
- The plugin's `stream()` uses the WebSocket `wss://api.sarvam.ai/text-to-speech/ws`, with a connection pool. It buffers text until `min_buffer_size` (default 50 chars) and splits at `max_chunk_length` (default 150). Short spoken replies (< 500 chars) give the lowest latency.
- `enable_preprocessing` is always on for v3/v4-flash: numbers, dates and currency are normalised for the target language. We still let the LLM write amounts the way people say them.
- No SSML. Use `pace` (0.5–2.0) and split at natural pauses. **Romanized Indic text lowers quality**, so the prompt makes the LLM write native script.
- Sample rate: default 22,050 Hz. Use 16,000 Hz to keep bandwidth low in the browser, and 8,000 Hz for phone (v1.5). The plugin's default output codec is MP3.
- `update_options(target_language_code=..., speaker=...)` validates before committing; a rejected update keeps the old voice. Changing the `model` retires pooled connections; changing language/speaker does not.

### Voices for our persona (from the Voices page; listen to samples before choosing)

| Language | Speaker ID | Note |
|---|---|---|
| kn-IN | `chaitra_kn_conversation` (alt `chetan_kn_conversation`) | primary voice |
| hi-IN | `chaitra_hi_customer` | the **same persona name "Chaitra"** as Kannada, which helps consistency |
| en-IN | `ishita_en_customer` or `simran_en_customer` | no `chaitra_en_*` listed |
| en-hi mix | `ishita_enhi_customer` | Hinglish replies |
| te-IN | `kavitha_te_conversation` (alt `pooja_te_conversation`) | |
| ta-IN | `gokul_ta_narration` / `vijay_ta_narration` | **no conversational or customer Tamil style is listed**; test, and accept narration style |

These go into `agent_configs.voices`. The persona stays "Amrutha" whatever the voice name is.

### Pronunciation dictionary (v1, small win)
Create one dictionary (REST: create/list/get/update/delete) with business words and pass `dict_id` to TTS. Without it, TTS may say "Amrith Sagar", "holige", "bale ele oota", "Basavanagudi" or package codes like "SI-BALE" wrongly.

---

## 6. Text APIs: translate, transliterate, language ID

| API | Endpoint / model | Limits | Price | Our use |
|---|---|---|---|---|
| Translate | `sarvam-translate:v1` (English ↔ all 22 languages, 2,000 chars/request, formal style, numeral format control) / `mayura:v1` (1,000 chars, `source_language_code="auto"`, modes formal / modern-colloquial / classic-colloquial / code-mixed) | 60 req/min | ₹2 per 1,000 chars | **v2:** English transcript. Customer turns only (~1,500 chars → ~₹3/call). v1 uses Gemini in the post-call step for free |
| Transliterate | `mayura` family | 1,000 chars | ₹2 per 1,000 chars | **v2:** "ರಮೇಶ್" → "Ramesh" for Sheets/CRM |
| Language ID | `POST /text-lid` → `language_code` + `script_code` (Knda, Deva, Taml, Telu, Latn …) | 1,000 chars | ₹0.35 per 1,000 chars | not in the call path. We detect script locally from Unicode ranges (free, instant) for TTS voice selection |

---

## 7. Batch STT (only if recording is enabled)
- `POST /speech-to-text/job/v1` with `model="saaras:v4"`, `mode="transcribe"` (or `"translate"` for English directly), `language_code="unknown"`, `with_diarization=true`, `num_speakers=2`, `with_timestamps=true`, optional `keyterms`. Then upload → start → status (or callback webhook) → download.
- Cost ₹0.59/min with diarization. Gives a clean, speaker-labelled transcript to replace the live one when live STT made mistakes.
- Not needed in v1, because the live transcript plus the agent's own text already form a complete conversation.

---

## 8. How it all runs inside LiveKit (v1)

```
Browser mic (WebRTC, Opus) → LiveKit Cloud room → local agent worker (Python, livekit-agents 1.x)
   │ 16 kHz PCM frames
   ▼
sarvam.STT  (WS, saaras:v4, transcribe, auto language, server VAD)
   │ final text + language + confidence, end-of-turn  ──► language.py hysteresis ──► update_instructions(CURRENT LANGUAGE)
   ▼
sarvam.LLM  (/v1 sarvam-105b-conversations, streamed, tools, reasoning none, x-session-affinity=call_id)
   │ ├─ tool call → tools.py (filler via session.say for slow tools) → Postgres / quote.py / bge-small search → result → LLM continues
   │ └─ reply text (native script)
   ▼
tts_node override: detect script of reply → tts.update_options(target_language_code, speaker) if changed
   ▼
sarvam.TTS  (WS, bulbul:v4-flash, dict_id, 16 kHz) → audio frames → room → browser speaker
   │
call_logger: transcript JSON (native), turns + latency metrics, tool_calls, usage → Supabase at shutdown → Celery postcall
```

Sketch (names follow the guide and the plugin reference; **verify** in the installed package):

```python
from livekit.agents import AgentSession, Agent, JobContext, WorkerOptions, cli
from livekit.plugins import sarvam

async def entrypoint(ctx: JobContext):
    meta = load_metadata(ctx)                      # tenant, call_type, customer, questions
    cfg = await load_agent_config(meta.tenant_id)  # voices, fillers, limits
    call_id = await create_call_row(meta)

    session = AgentSession(
        vad=None,
        turn_handling={"turn_detection": "stt", "endpointing": {"min_delay": 0.07}},
        stt=sarvam.STT(language="unknown", model="saaras:v4", mode="transcribe",
                       prompt="Amrith Sagar, holige, bale ele oota, Basavanagudi, Jain, muhurtham"),
        llm=sarvam.LLM(model=settings.LIVE_LLM, max_tokens=250,   # no reasoning_effort: "none" is rejected
                       temperature=0.3, extra_headers={"x-session-affinity": str(call_id)}),
        tts=sarvam.TTS(model="bulbul:v4-flash", target_language_code=start_lang,
                       speaker=cfg.voices[start_lang], speech_sample_rate=16000,
                       dict_id=settings.SARVAM_DICT_ID or None),
    )
    await session.start(room=ctx.room, agent=Amrutha(meta, cfg, call_id))
```

Latency budget per turn (target ≈ 1–1.5 s): end-of-speech detection (~70 ms endpointing + Sarvam VAD silence) + LLM first token + TTS first audio byte + network. All three parts are logged per turn (`eou_delay_ms`, `llm_ttft_ms`, `tts_ttfb_ms`).

---

## 9. Any Indian language in, English out

| Stage | Language | How |
|---|---|---|
| Customer speaks | any Indian language or a mix | Saaras auto-detect |
| Live transcript (stored) | **native script**, as spoken | `mode="transcribe"` → `calls.transcript` |
| Agent's reply | the customer's current language (native script) | prompt rule + hysteresis + script-matched TTS voice |
| Knowledge search query | English keywords | prompt rule (the KB is English) |
| Tool arguments (area, dates, notes) | English / ISO dates | tool docstrings |
| Post-call fields + owner summary | **English** | v1: one Gemini call (free); v2: Sarvam (below) |
| English transcript for the owner | **English** | v1: same Gemini call returns `transcript_en` for non-English turns; v2: `sarvam-translate:v1` |
| Google Sheet row | English | from `extracted` |

### v2 upgrade (all-Sarvam post-call, as you suggested)
- `sarvam-105b` (`/v2`, reasoning `low`, `response_format=json_schema`) writes the fields and the owner summary in **English**, plus an optional **native-script summary** (`owner_summary_native`) for owners who prefer Kannada or Hindi.
- `sarvam-translate:v1` produces the turn-by-turn English transcript.
- Transliteration romanises names and addresses for the CRM.
- One vendor, one bill, better Indic accuracy. Cost per call is about ₹3–5 more than the free Gemini path.

---

## 10. Sarvam usage by version

| | v1 (browser) | v1.5 (phone) | v2 (SaaS) |
|---|---|---|---|
| STT | saaras:v4 streaming, 16 kHz | same, **8 kHz** from SIP; retune VAD | per-tenant `prompt`/keyterms from their KB |
| LLM | sarvam-105b-conversations + tools, caching header | same | same; per-tenant prompt versions; running summary on long calls |
| TTS | bulbul:v4-flash, voices per language, dict_id | `speech_sample_rate=8000` | per-tenant voices + dictionaries; pre-generated greeting/filler audio (REST, cached) |
| Post-call | Gemini (free) → English fields + owner summary + English transcript | same | sarvam-105b + sarvam-translate + transliterate; native-script summary option |
| Recording | off (transcript only) | optional Opus → Supabase; batch STT + diarization for clean transcripts | per-tenant retention setting |

---

## 11. Cost per call minute (pay-as-you-go)

| Part | Rate | Per minute (estimate) |
|---|---|---|
| STT | ₹0.49/min of customer audio streamed | ₹0.49 |
| TTS | ₹1.00 / 1,000 chars | ~₹0.40–0.60 (400–600 chars/min) |
| LLM | ₹15 in (₹5 cached) / ₹60 out per 1M tokens | ~₹0.10–0.25 |
| **Total live** | | **≈ ₹1.0–1.35 per minute** |
| v2 extras | translate ₹2/1,000 chars, LLM summary | +₹3–5 per call |

₹100 free credit ≈ 80 minutes of test calls. Use the text-mode evals (LLM only, no STT/TTS) for most testing.

---

## 12. Check in the Milestone 1 spike (write results to `docs/spike_results.md`)
1. Tool calling on `sarvam-105b-conversations` (10 tries); else switch to `LIVE_LLM_FALLBACK`.
2. Reasoning: `"none"` is rejected (checked); confirm reasoning tokens stay 0 with the field omitted, and compare latency with `"low"`.
3. `x-session-affinity` gives `cached_tokens > 0` from the 2nd turn on.
4. `sarvam.STT(language="unknown")` vs `STTRealtime(language="auto", stream_type="fast")`: latency, Kannada/English detection, Kanglish with `mode="codemix"`.
5. `prompt` (and keyterms, if accepted) improves "holige", "bale ele oota", "Amrith Sagar".
6. Chosen Bulbul voices sound right; Tamil narration voice acceptable; `update_options` switches mid-call without a gap.
7. Per-turn latency, end-of-speech → first audio, typical and P90.
