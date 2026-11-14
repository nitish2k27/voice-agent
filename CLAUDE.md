# CLAUDE.md — Amrith Sagar Voice Calling Agent

Context file for Claude Code. Read this first, then `docs/build_plan.md` for the current milestone. `docs/sarvam_stack.md` explains how each Sarvam API is used inside LiveKit. `docs/review_and_task_list.md` explains why the design looks the way it does.

## What we are building

A multilingual AI voice agent ("Amrutha") for **Amrith Sagar Catering** (mock business, Bengaluru) that:

1. **Outbound:** calls customers from a CSV one after another (post-event feedback, enquiry follow-up, pre-event confirmation), talks naturally, asks the campaign questions with follow-ups, and saves answers live.
2. **Inbound:** answers customer calls: questions from the knowledge base, price quotes, date availability, tentative bookings, callback requests.
3. **Logs every conversation as a JSON transcript (no audio recording)**, plus per-turn timings and tool calls. After each call an LLM turns the transcript into structured fields **and a short owner summary** (only what matters). After a campaign it writes a campaign digest. Saved to Supabase + Google Sheets.
4. **Evaluates itself:** admin dashboard with latency, task success, LLM-judge quality scores, cost per call; simulated-caller test suite.

College final-year project (B.Tech CSE AI/ML). Must be demo-able, well documented, and cost ₹0 apart from Sarvam API credits.

## Versions

- **v1 (build now):** calls happen in the **browser over WebRTC** (LiveKit rooms). A phone-style web page simulates incoming/outgoing calls. No telephony provider.
- **v1.5 (later, documented only):** real phone numbers via Plivo SIP trunk → LiveKit SIP. Needs a registered business + KYC, so not built now. Only the dial step changes.
- **v2 (future):** multi-tenant SaaS, minute-based billing (Razorpay test mode), caching optimizations. Keep `tenant_id` on every table from day one.

## Tech stack (fixed — do not swap without asking)

| Layer | Choice |
|---|---|
| Frontend | React + **JavaScript** (Vite). **No TypeScript.** `livekit-client` + `@livekit/components-react`, `@supabase/supabase-js` (**Auth only**; all data via FastAPI) |
| API | FastAPI (Python 3.11) |
| DB + vectors | Supabase Postgres + pgvector (free tier). Driver: `psycopg` v3 (sync in Celery, async in FastAPI/agent). **Connect through the Supavisor session pooler** (direct host is IPv6-only) |
| Auth + file storage | Supabase Auth (email/password), Supabase Storage (uploaded KB docs only, no audio) |
| Queue | Celery + Redis (Redis in Docker, the only Docker use). Celery beat = scheduler. ARQ only if Celery becomes painful |
| Voice framework | LiveKit Agents (Python) `livekit-agents[sarvam]>=1.8.6,<2`; rooms on LiveKit Cloud Build plan (free); **agent worker runs locally** |
| STT | Sarvam Saaras v4, `language="unknown"` (auto-detect), `mode="transcribe"` |
| TTS | Sarvam Bulbul **v4 Flash** (`bulbul:v4-flash`) — NOT v3 |
| Live LLM | `sarvam-105b-conversations` via the Sarvam LiveKit plugin |
| Post-call extraction + owner summary | Gemini API free tier (Flash / Flash-Lite), one call per answered call |
| Judge + simulated caller | Groq free tier (pick a model currently on Groq's free list) — Gemini as fallback |
| Embeddings | `BAAI/bge-small-en-v1.5` via **fastembed** (ONNX, no torch; ~130 MB, 384 dims, English). Documents embedded at ingest (onboarding / doc upload); during calls only the short English query is embedded (~5–20 ms on CPU), model loaded once in the agent's `prewarm` |
| Sheets + Calendar | Google Sheets API via `gspread` + Google Calendar API, same service account |
| Booking payments | Razorpay **test mode** Payment Links (40% advance), webhook auto-confirms |

All model names live in config/env (`LIVE_LLM`, `EXTRACT_LLM`, `JUDGE_LLM`, `SIM_LLM`, `STT_MODEL`, `TTS_MODEL`). Retrieval mode: `SEARCH_MODE=hybrid` (default) | `keyword` (fallback / eval comparison).

## Repo layout (target)

Same pattern as the owner's other projects (mybackend: layered `app/`; llm-project: `backend/` + `frontend/` + `supabase/` + `docs/`).

```
Voice-Agent/
├── CLAUDE.md  README.md  .env.example  .env (git-ignored)  docker-compose.yml (redis only)  Procfile (honcho)
├── .venv/                       # Python 3.11 venv (repo root; activate, then work inside backend/)
├── secrets/                     # google-service-account.json (git-ignored)
├── docs/                        # architecture, knowledge_base, build_plan, prompts, api_contracts, sarvam_stack, review_and_task_list, spike_results
├── supabase/
│   └── schema.sql               # run once in the Supabase SQL editor (idempotent)
├── backend/                     # ALL Python lives here; run every Python command from this folder
│   ├── app/                     # shared package: FastAPI app + everything the agent and worker reuse
│   │   ├── main.py              # FastAPI app: CORS, lifespan (db pools), include_router(...) for every router, /health
│   │   ├── core/                # config.py (pydantic-settings, reads ../.env), deps.py (get_db, get_current_user, require_admin),
│   │   │                        # security.py (Supabase JWT/JWKS verify), logging.py
│   │   ├── db/                  # session.py: psycopg v3 pools (sync for Celery, async for FastAPI/agent), get_conn()
│   │   ├── schemas/             # Pydantic request/response models: campaigns, calls, kb, bookings, onboarding, agent_config, admin, customer
│   │   ├── repos/               # REPO LAYER: the only place with SQL (tenants, customers, campaigns, jobs, calls, turns, tool_calls,
│   │   │                        # kb, bookings, callbacks, results, evals). No HTTP errors, no business rules
│   │   ├── services/            # SERVICE LAYER: business logic, no FastAPI imports: quote, areas, availability, bookings, search,
│   │   │                        # embedder, kb_ingest, campaign_types, livekit_service, telephony (place_call), events (Redis pub/sub),
│   │   │                        # rate_limit, calendar, payments, extraction, judge, sheets, cost
│   │   └── routers/             # ROUTES: thin HTTP layer → services: onboarding, inbound, customer, campaigns, calls, kb,
│   │                            # agent_config, bookings, payments, admin, billing
│   ├── agent/                   # LiveKit worker (separate process): agent.py (entrypoint, agent_name="amrutha"), prompts.py,
│   │   │                        # prompts/v1.txt, tools.py, language.py, guardrails.py, call_logger.py
│   ├── worker/                  # Celery: celery_app.py, tasks.py (campaign_tick, dial_call, postcall, campaign_digest,
│   │                            # ingest_document, sync_calendar, expire_tentative_bookings)
│   ├── evals/                   # personas.yaml, simulate.py, report.py
│   ├── data/                    # amrith_sagar_pricing.json (prices + quote_rules), areas.json, campaign_types.json, sample_customers.csv
│   ├── scripts/                 # check_env.py, test_search.py, one-off CLIs
│   ├── tests/                   # pytest: test_quote.py, test_areas.py, test_availability.py, test_search.py ...
│   ├── requirements.txt         # -r requirements/*.txt
│   ├── requirements/            # base.txt, agent.txt, api.txt, ingest.txt, dev.txt
│   └── pytest.ini
└── frontend/                    # React + JavaScript (Vite); its own .env with VITE_* public values only
    └── src/
        ├── main.jsx  App.jsx
        ├── lib/                 # api.js (FastAPI client + JWT), supabase.js (Auth only), auth.jsx, livekit.js
        ├── hooks/  components/  styles/
        └── pages/
            ├── business/        # Onboarding, Home, Knowledge, AgentSettings, Campaigns, Inbound, Calls, CallDetail, Bookings, Billing
            ├── admin/           # Overview, Latency, Quality, FlaggedCalls, TestSuite
            └── customer/        # IncomingCall (/c/:token), CallUs
```

Layer rule (as in mybackend): **routers → services → repos → db**. Routers hold no SQL, repos hold no business rules, services never import FastAPI. No ORM: tables come from `supabase/schema.sql`, repos use plain SQL through psycopg.

## Verified technical facts (from Sarvam + LiveKit docs, Nov 2026)

- Install: `pip install "livekit-agents[sarvam]>=1.8.6,<2"`.
- Session config recommended by Sarvam's LiveKit guide:
  ```python
  session = AgentSession(
      vad=None,  # Sarvam STT does VAD server-side; omitting vad installs Silero → two VADs disagree
      turn_handling={"turn_detection": "stt", "endpointing": {"min_delay": 0.07}},
  )
  stt = sarvam.STT(language="unknown", model="saaras:v4", mode="transcribe")
  llm = sarvam.LLM(model="sarvam-105b-conversations")
  tts = sarvam.TTS(target_language_code="kn-IN", model="bulbul:v4-flash", speaker="<name>_kn_<style>")
  ```
- Do **not** set `flush_signal=True` on STT inside AgentSession (no effect).
- Bulbul v4 Flash speaker IDs are `name_language_style` (e.g. `chaitra_kn_conversation`); speaker language must match `target_language_code`; v3 short names (`priya`) are rejected. Full list: Sarvam Voices page.
- Bulbul v4 Flash languages: hi, en, en-hi, bn, gu, kn, mr, pa, ta, te (no Malayalam/Odia → fall back to en-IN/kn-IN).
- Bulbul v3 is end-of-life for voice agents (Nov 2026) — use v4 Flash.
- `sarvam.TTS.update_options(target_language_code=..., speaker=...)` exists and validates before committing (rejected update leaves old options).
- STT `SpeechData.language` holds the detected language; `language_confidence` is in `metadata`.
- `sarvam-105b-conversations`: voice-tuned, 32K context, `/v1` only. Reasoning tokens add latency on sarvam-105b; check plugin/API options to keep reasoning off.
- **Tool calling with sarvam LLM must be verified on day 1** (Milestone 1). `/v1` documents `tools`/`tool_choice`; the v2 model list doesn't list tools for the conversations model. If unreliable, switch to `LIVE_LLM_FALLBACK` (`sarvam-105b` with reasoning none, or Token Factory `deepseekv4.1-flash-1017-interactive` / `gemma4`, same Sarvam key).
- Tested 2026-11-13: `sarvam-105b-conversations` **rejects `reasoning_effort="none"`** (400: only low/medium/high) and returns no reasoning tokens when the field is omitted, so do **not** send it (`LIVE_LLM_REASONING` empty). `gemini-2.5-flash` is closed to new users → `EXTRACT_LLM=gemini-3.8-flash`. Groq: `JUDGE_LLM=openai/gpt-oss-120b`, `SIM_LLM=openai/gpt-oss-20b`. Send header `x-session-affinity: <call_id>` (`extra_headers`) for prompt caching; hits appear in `usage.prompt_tokens_details.cached_tokens`.
- Live STT: the guide uses `sarvam.STT(language="unknown", model="saaras:v4")`. The plugin also has `sarvam.STTRealtime` (new `/speech-to-text-realtime/ws`, `language="auto"`, partials, live `config.update`); compare both in M1. STT `prompt` biases domain words. STT WS accepts 16 kHz or 8 kHz mono.
- Bulbul v4 Flash voices we start with: `chaitra_kn_conversation`, `chaitra_hi_customer`, `ishita_en_customer`, `kavitha_te_conversation`, `gokul_ta_narration` (no conversational Tamil voice listed). Pronunciation dictionary via `dict_id`. No SSML; native script only (romanized Indic lowers quality). WS text ≤ 2,500 chars/message, < 500 for lowest latency.
- Pay-as-you-go limits: 20 concurrent STT WS, 60 concurrent TTS WS, 60 LLM req/min (throttle evals). ₹100 free credit on signup.
- Pricing (₹, ex-GST): STT ₹0.49/min; Bulbul v4 Flash ₹1.00 / 1,000 chars; sarvam-105b ₹15 / ₹5 cached / ₹60 per 1M tokens (in / cached / out).
- LiveKit Build plan: free, hard caps; 5,000 WebRTC participant minutes/month; 1,000 agent-session minutes only apply to agents deployed to LiveKit Cloud — we run the agent locally.
- Supabase free tier: direct DB host is IPv6-only → use the pooler URL (session mode 5432; if you use transaction mode 6543, set psycopg `prepare_threshold=None`). Projects pause after 7 days idle.
- Browser mic (`getUserMedia`) needs HTTPS except on `localhost` → test phones through Cloudflare Tunnel or `vite --https`.
- To verify in the installed package before use: `Agent.update_instructions`, `tts_node` override signature, metrics event class names, text-only test mode for evals.

## Core design rules

1. **Prices are never computed by the LLM.** `calculate_quote` reads `backend/data/amrith_sagar_pricing.json` (`quote_rules`) and does the math in Python. Tool schemas use enums for package/add-on/item codes.
2. **Knowledge base is English only.** The live LLM writes `search_knowledge_base(query=...)` in English keywords, whatever language the customer speaks. Reply in the customer's language.
3. **Hybrid retrieval with a small model.** bge-small-en-v1.5 (fastembed, 384 dims) embeds chunks in the Celery `ingest_document` task and embeds the English query at search time (the same model on both sides, always). Search = SQL `hybrid_search`: pgvector cosine + Postgres full-text (OR-joined English keywords, `ts_rank_cd` as the BM25 stand-in) fused with RRF. `SEARCH_MODE=keyword` passes a null embedding (fallback). Chunk by markdown heading / FAQ item, ~150–400 tokens. Never load BGE-M3 (~2.2 GB) or torch in the agent.
4. **No audio recording.** Store the conversation as JSON (`calls.transcript`, native script as spoken), plus `turns`, `tool_calls` and `live_answers`. Post-call, one Gemini call produces `extracted` + `owner_summary` + `transcript_en`: **everything the owner reads is English**. A completed campaign gets a `digest`. v2: Sarvam does post-call (sarvam-105b + sarvam-translate) and adds a native-script summary.
5. **Live question tracking:** `record_answer(question_key, answer)` saves answers during the call and removes them from the prompt's pending list (`update_instructions`).
6. **Language switching:** the instructed language switches only after 2 consecutive final utterances (≥3 words) in the same new language. The TTS language/speaker follows the **script of each LLM reply** (`tts_node`). One persona name; unsupported languages fall back.
7. **Fillers:** tools that can take >300 ms (`search_knowledge_base`, `check_availability`, `create_tentative_booking`, `schedule_callback`) first `await context.session.say(<filler in current language>)`. `calculate_quote` gets none.
8. **Prompt** = static part first, dynamic tail last (today's date in IST, customer, pending questions, current language). Versioned templates in `backend/agent/prompts/`.
9. **Scope limits (v1):** no payment details on calls; a reservation is held 48 h under the customer's name, mirrored to Google Calendar, and a Razorpay (test) payment link for the 40% advance is sent; the booking is confirmed only when paid (webhook) or by staff. The agent says "reserved", never "confirmed". No discounts beyond published volume slabs, no policy exceptions (log a callback instead). See `docs/knowledge_base.md` → Agent persona, rules and scope limits.
10. **Disclosure** in the first sentence of every call: AI assistant + "this call is transcribed for quality".
11. **Guardrails in v1:** max call length (wrap-up at −30 s), silence hang-up, outbound waits ≤45 s for the customer, `/inbound/start` rate limited + concurrency cap.
12. **Everything carries `tenant_id`** (single tenant in v1: Amrith Sagar). **RLS enabled deny-all**; server code uses the pooler DB URL / service key.
13. **The DB is the queue's source of truth.** `campaign_tick` (beat) picks the next due job; retries = `next_attempt_at`; pause/resume = campaign status. No `self.retry(countdown=...)` for no-answers.
14. **Free tiers:** Gemini/Groq used only post-call and in text-mode evals. Synthetic data only. Test/eval rows carry `is_test=true` and are excluded from metrics and availability.
15. **Telephony abstraction:** the dial step is the only thing that differs between v1 (send "ring" event to the customer web page) and v1.5 (create SIP participant). Keep it behind one function `place_call(job)`.
16. **Shared code lives in `backend/app/`.** `agent/` and `worker/` import only `app.core`, `app.db`, `app.repos` and `app.services`, never `app.routers` or `app.main`.

## v1 call mechanics (browser)

- **Outbound:** beat `campaign_tick` (30 s) → if nothing is `ringing`/`in_call`, pick the next due job inside the IST window → `dial_call(job_id)` → `place_call(job)`: create room `out-{job_id}-{attempt}` → explicit agent dispatch (`agent_name="amrutha"`, metadata = customer row + call type + questions) → job `ringing` + `ring_started_at` → publish `{"type":"ring",...}` to Redis `customer:{customer_token}`. Customer page (SSE `/customer/{token}/events`, sends current state on connect) rings → Accept: `/customer/{token}/join` → LiveKit token → joins. Decline → `declined`; **30 s timeout enforced by `dial_call`** → `no_answer`; both set `next_attempt_at = now()+30 min` (max 3 attempts) and delete the room. After accept, `dial_call` waits for the agent's end mark and checks LiveKit `list_rooms` every 15 s (room gone, no end mark → `failed`). `calls` queue concurrency 1 → strictly one call at a time.
- **Inbound:** "Call us" page → `POST /inbound/start` (rate limited) → room `in-{uuid}` + dispatch with tenant config → token → join.
- **Agent end of call:** write `calls` (transcript JSON, live answers, usage, cost), `turns`, `tool_calls` → set job status → enqueue `postcall(call_id)` → delete room.
- **Post-call:** Gemini (extracted + owner summary) → Groq judge → `call_results` → Sheet row.

## Commands (expected)

From the repo root: `docker compose up -d redis`, `.venv\Scripts\activate`, `honcho start` (Procfile runs everything below).
All Python commands run **inside `backend/`** (so `app`, `agent`, `worker`, `evals` import as top-level packages):

```bash
cd backend
pip install -r requirements.txt
python scripts/check_env.py
uvicorn app.main:app --reload --port 8000   # or: python -m app  (Windows-safe loop for async psycopg; see app/__main__.py)
python -m agent.agent dev            # or: python -m agent.agent console  (talk in terminal)
celery -A worker.celery_app worker -Q calls -c 1 -n calls@%h --pool=solo     # --pool=solo on Windows
celery -A worker.celery_app worker -Q postcall -c 1 -n postcall@%h --pool=solo
celery -A worker.celery_app beat
python -m app.services.kb_ingest ../docs/knowledge_base.md   # seed the KB (chunk embeddings computed here)
python -m evals.simulate --personas evals/personas.yaml --prompt-version v1
pytest
```

Frontend: `cd frontend && npm run dev`.

## Working style for Claude Code

- Follow `docs/build_plan.md` milestone by milestone; finish acceptance criteria before moving on.
- Before using a library API you're unsure of (LiveKit Agents, Sarvam plugin, livekit-api dispatch), check the installed package source or official docs rather than guessing.
- Keep functions small and typed with Python type hints; Pydantic models for API I/O.
- Never commit `.env` or `secrets/`. Read secrets via `backend/app/core/config.py` (pydantic-settings).
- Write a short test or script for each milestone (e.g. `backend/tests/test_quote.py`).
- Log per-turn latency from day one — it is the core evaluation data.

## Reference docs (online)

The online docs predate the 2026-11-12 review. The repo files win where they differ (transcript-first, bge-small hybrid search).
- Design doc: https://claude.ai/artifact/18i5DKW756CbCWZv2DEopu
- Knowledge base doc: https://claude.ai/artifact/CaM9hgYCJLkcH7VFweensX
- Sarvam + LiveKit guide: https://docs.sarvam.ai/api/integration/build-voice-agent-with-live-kit
- LiveKit Sarvam plugin reference: https://docs.livekit.io/reference/python/v1/livekit/plugins/sarvam/index.html
- Sarvam models: https://docs.sarvam.ai/api/getting-started/models.md
- Sarvam pricing: https://docs.sarvam.ai/api/getting-started/pricing
