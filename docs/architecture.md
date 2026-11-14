# Voice Calling Agent — System Design (v1 / v1.5 / v2)

Repo copy of the design doc, and the source of truth. The online version (https://claude.ai/artifact/18i5DKW756CbCWZv2DEopu) predates the 2026-11-12 review: it still mentions audio recordings and query-time embeddings. Where they differ, this file wins.

## Overview

A multilingual AI voice agent that makes outbound calls (feedback, follow-ups, confirmations) and answers inbound calls (enquiries, quotes, tentative bookings) for a Bengaluru catering business. Every conversation is stored as a JSON transcript (no audio). An LLM then condenses it into a short owner summary, which is saved to Supabase and Google Sheets.

| Version | Calls happen over | Who can use it | Needs business KYC |
|---|---|---|---|
| v1 (build now) | Browser (WebRTC, LiveKit rooms) | Anyone with the link | No |
| v1.5 | Phone network (Plivo SIP trunk into LiveKit) | Real customers on their phones | Yes |
| v2 | Both, per tenant | Many businesses (SaaS) | Per tenant |

Plivo is not used in v1: Indian domestic calling needs a registered Indian business entity + KYC (Certificate of Incorporation + GST), an India-rented caller ID and INR billing. The project has no registered business yet.

## Architecture

```
[Business dashboard] [Admin dashboard]        [Customer call page (WebRTC)]
          \              /                               |
           [  FastAPI  ] ── [Celery + Redis] ──dispatch──┐ |  WebRTC (v1)
                 |               |                        v v
                 |               |     ┌──────── LiveKit Cloud room ────────┐
                 |               |     │  Agent worker (runs locally):      │   SIP (v1.5)
                 |               |     │  Sarvam only in the call path:     │ <──── Plivo trunk ── phones
                 |               |     │  Saaras v4 STT → sarvam-105b LLM   │
                 |               |     │  → Bulbul v4 Flash TTS  + Tools    │
                 |               |     └────────────────────────────────────┘
                 |               |          | transcript JSON, timings, tool log
            [Supabase Postgres + pgvector] <──> [Celery postcall: Gemini extract + owner summary, Groq judge] ──> [Google Sheets]
                         ^
                         └── [Celery ingest_document: bge-small-en-v1.5 chunk embeddings, when the company adds context/docs]
```

### Code structure
Repo = `backend/` (all Python) + `frontend/` (React JS) + `supabase/` (schema) + `docs/`, the same pattern as the owner's other projects. Inside `backend/`, the package `app/` is layered like mybackend: `routers/` (thin HTTP) → `services/` (business logic, no FastAPI) → `repos/` (the only SQL) → `db/` (psycopg pools), plus `core/` (config, deps, security) and `schemas/` (Pydantic). The LiveKit worker (`backend/agent/`) and Celery (`backend/worker/`) are separate processes that reuse `app.core`, `app.db`, `app.repos` and `app.services`, never `app.routers`/`app.main`. Full tree: CLAUDE.md → Repo layout.

### What runs during a call, and what doesn't
- **In the call path:** Sarvam STT, LLM and TTS; Postgres queries for tools; pure-Python quote maths; and one tiny query embedding per knowledge search.
- **Not in the call path:** Gemini, Groq, document embedding.

### Embedding model and hybrid search
| Item | Choice | Why |
|---|---|---|
| Model | `BAAI/bge-small-en-v1.5` | 33M params, ~130 MB, 384 dims; strong English retrieval. The KB is English and the LLM always writes English keyword queries, so a multilingual model (BGE-M3, ~2.2 GB) is not needed |
| Runtime | `fastembed` (ONNX Runtime, CPU) | no torch; loads in ~1 s; ~5–20 ms per short query on a laptop; ~200 MB RAM per agent process |
| When chunks are embedded | Celery `ingest_document` (onboarding / doc upload / re-ingest) | batch, normalised vectors → `kb_chunks.embedding vector(384)` |
| When queries are embedded | inside `search_knowledge_base`, model loaded once in the agent's `prewarm` | exact-text LRU cache for repeated questions |
| Keyword side | Postgres full-text, OR-joined English keywords, `ts_rank_cd` | Supabase free has no true BM25; close enough for a ~100-chunk KB |
| Fusion | reciprocal rank fusion in SQL `hybrid_search` (k=50, top 5) | catches paraphrases ("veg guests who skip onion" → Jain FAQ) that keywords miss, and exact codes/numbers that vectors miss |
| Rule | same model for docs and queries | changing the model means re-ingesting every document |

`SEARCH_MODE=keyword` (null embedding) is the fallback and the baseline for the keyword-vs-hybrid eval table.

## Free-tier setup (₹0 except Sarvam)

| Part | Free option | Limit that matters |
|---|---|---|
| Voice rooms | LiveKit Cloud Build plan | 5,000 WebRTC minutes/month, hard cap. Agent-session minutes count only for agents deployed to LiveKit Cloud → worker runs locally |
| Database + vectors | Supabase free | 500 MB DB, 1 GB storage (KB documents only); pauses after 7 days idle. **Connect through the Supavisor pooler**: the direct host is IPv6-only |
| Queue | Redis in Docker + Celery | local |
| Embeddings | bge-small-en-v1.5 via fastembed on CPU | local (~130 MB download); no API cost |
| Extraction + owner summary | Gemini free tier | one call per answered call + one per finished campaign; synthetic data only |
| Judge + simulated caller | Groq free tier | per-model daily limits; model name in config |
| Sheets | Google Sheets API | free |
| Calendar | Google Calendar API (same service account; business calendar shared with it) | free |
| Payments | Razorpay **test mode**: booking advance payment links (v1) + wallet top-ups (v2 demo) | no real money; live mode needs business KYC |
| Hosting | Cloudflare Pages (frontend); laptop for API/worker/agent | Cloudflare Tunnel for public demo; **HTTPS is required for mic access on phones** |

## End-to-end flows

### 0. Company onboarding (where chunks are embedded)
1. Owner signs up (Supabase Auth). A trigger creates a `profiles` row.
2. Onboarding: company name, city, phone, short description → tenant + default `agent_configs` (v1 links to the seeded Amrith Sagar tenant).
3. Owner pastes context or uploads documents (English) → `kb_documents` → Celery `ingest_document`: parse → chunk by heading/FAQ item (~150–400 tokens) → bge-small-en-v1.5 embeddings → `kb_chunks` → tenant `ready`.
4. Adding or replacing documents later re-runs only that document's ingest.

### 1. Outbound campaign (v1)
1. Business creates a campaign (type → default questions from `backend/data/campaign_types.json`) and uploads a customer CSV.
2. FastAPI validates rows, upserts `customers` (by phone, each gets a personal link `/c/{token}`), creates one `call_jobs` row per customer.
3. **Scheduler:** Celery beat `campaign_tick` every 30 s. If no call is ringing or in progress, it picks the next due job (campaign running, inside the IST calling window, attempts left) and sends `dial_call`. Pause/resume/cancel just change `campaigns.status`. Retries are `next_attempt_at` rows in the DB, not hidden broker tasks.
4. `dial_call` → `place_call(job)`: creates the room, dispatches the agent with metadata, marks the job `ringing`, publishes a `ring` event. **The server owns the 30 s ring timeout.** If the customer page opens late, it learns the current state when the SSE connection opens.
5. Accept → join → conversation (flow 3). Decline / 30 s → `declined`/`no_answer`, `next_attempt_at = +30 min`, max 3 attempts.
6. `dial_call` waits for the agent's end mark, and checks LiveKit's room list as a backup (agent crash → `failed`, move on).
7. When nothing is left to call, the campaign becomes `completed` and gets one **campaign digest** for the owner.

### 2. Inbound call (v1)
1. Customer opens "Call us" link / QR → presses Call (rate limited per IP; max 2 at once).
2. FastAPI creates room `in-{uuid}`, dispatches the agent with tenant config, returns a token.
3. Agent greets (AI + transcription disclosure), asks Kannada or English, then follows the caller's language.
4. Answers from documents, quotes, checks dates, reserves dates (calendar + payment link), callbacks.
5. Same logging + `postcall`.

### 3. Live conversation loop
1. Customer speaks → Saaras v4 streams transcript + detected language.
2. **Language:** after 2 consecutive final utterances (≥3 words) in a new language, Python updates CURRENT LANGUAGE in the prompt. The TTS language/speaker is picked per reply from the **script of the LLM's text** (in a `tts_node` override), so the voice always matches what was written.
3. sarvam-105b-conversations reads the system prompt (static persona/rules/tools first; dynamic date, customer, pending questions, language last) + the conversation.
4. Needs a fact/action → tool call; slow tools speak a filler first. Knowledge searches always use English keywords.
5. Customer answers a campaign question → `record_answer` → Python removes it from the pending list and updates the instructions.
6. Reply streams to Bulbul v4 Flash (target ≈1–1.5 s end-of-speech → reply audio). Barge-in supported.
7. Guardrails: max call length (default 8 min, wrap-up at −30 s), silence hang-up (20 s + one "are you still there?"), outbound waits ≤45 s for the customer to join.
8. On shutdown: transcript JSON, turns, tool calls, usage and cost are written; the job status is set; `postcall` is enqueued.

### 4. Post-call processing (Celery `postcall`)
1. Input: transcript JSON + tool log + live answers. No audio.
2. **One Gemini call** returns the campaign fields (English JSON, validated with Pydantic), **the owner summary** (headline, key points, sentiment, action items, money mentioned, booking id, urgency; small talk dropped) and an **English transcript** of the non-English turns. Whatever language the customer spoke, everything the owner reads is English; the native-script transcript is kept as spoken. v2 does this step with Sarvam (`sarvam-105b` + `sarvam-translate:v1`) and adds a native-script summary (`docs/sarvam_stack.md`).
3. Groq judge scores the transcript against the tool log and raises flags.
4. Save `call_results`, append to the campaign's Google Sheet tab, show on dashboards (the calls list shows the headline; the detail page shows summary → fields → full transcript).

### 5. Reservation, calendar and payment link
1. Customer wants to book → agent checks availability, reads back date, guests, package, area → customer agrees.
2. `create_tentative_booking`: booking row `tentative` (48 h hold, availability re-checked), advance = 40% of the quote (Python), Razorpay test Payment Link created (expires with the hold), link pushed to the customer (v1: on their call page; v1.5: SMS), `sync_calendar` adds "RESERVED – name – guests – area" to the business Google Calendar.
3. Agent says: "I've reserved the date under your name and sent a payment link for the advance. Once you pay, your confirmation comes there." Never "confirmed".
4. Customer pays → Razorpay webhook (signature verified) → booking `confirmed` → calendar event → CONFIRMED → customer page shows the confirmation; owner sees it on the Bookings page.
5. Not paid in 48 h → beat task expires the booking and the link, removes the calendar event. Staff can confirm or cancel manually at any time.

## Business client dashboard (pages)
Login · **Onboarding** (company details + context/doc upload → ingest status) · Home (cards: calls today, completed, no-answer, bookings, avg satisfaction, open callbacks) · Business knowledge (upload English docs, ingest status, "test a question") · Agent settings (persona, greeting, voices per language, fillers, rules, tools on/off, blocked dates, call limits) · Campaigns (type, CSV upload, questions, calling window, live progress, pause/resume/cancel, **campaign digest**) · Inbound (Call-us link + QR; v1.5: number + forwarding) · Calls (table with owner headline; detail with owner summary, extracted fields, transcript, tool calls; CSV download, Sheet link) · Bookings & callbacks · Billing (v2).

## Customer call page (v1)
Incoming call screen (Accept/Decline, countdown from the server's `seconds_left`), "missed call" state, "Call us" button, in-call screen (timer, mute, speaker, hang up, optional live captions), thanks screen. Mic permission once; Chrome on Android/desktop; served over HTTPS. The agent can't tell this page from a phone caller: both are LiveKit room participants.

## Admin and evaluation dashboard
v1 core metrics: response latency, question coverage, completion rate, groundedness score, cost per call. All metrics exclude `is_test` rows.

| Group | Metrics | Source |
|---|---|---|
| Latency | avg / P90 response; EOU/LLM/TTS breakdown; slow turns (>3 s) % | `turns` (LiveKit metrics) |
| Task success | question coverage (live `record_answer` + extraction), completion, goal achieved, tool success, handoff rate | calls / tool_calls / call_results |
| Quality | naturalness, on-topic, groundedness, policy, empathy, language match, task success (1–5) | LLM judge |
| Conversation | interruption rate, talk ratio, dead air, "please repeat" count, language switches | turns + transcript |
| Reliability | system failures, retry success, API errors per provider | outcomes + logs |
| Cost | cost per call/minute, per completed survey/booking | usage counters × `pricing_rates` |

Targets v1: avg response <1.5 s, P90 <2.5 s, slow turns <5%. Offline test suite: simulated personas in text mode after every prompt change (`eval_runs` / `eval_results`).

## Data model
`tenants, profiles, agent_configs, blocked_dates, kb_documents, kb_chunks (vector(384) + fts), customers, campaigns, call_jobs, calls (transcript + live_answers), turns, tool_calls, call_results (extracted + owner_summary + judge), bookings, callbacks, eval_runs, eval_results` + billing `wallets, payments, usage_ledger, pricing_rates`. RLS enabled, deny-all; backend uses the service role. Full SQL: `supabase/schema.sql`.

## Security
- RLS deny-all on every table; the anon key in the frontend can only do Auth.
- Customer links use 24-hex-char random tokens; `/join` only works while that customer's job is ringing.
- `/inbound/start` rate limited per IP + global concurrency cap; every call has a max length.
- Secrets only in `.env` (never committed); service key and DB URL only on the server side.
- Data: synthetic customers only; transcripts kept in Supabase; no audio stored.

## Billing and minute plans (v2 demo)
The admin pays the APIs; businesses buy prepaid minutes.

Cost per call minute (estimates): STT ₹0.49 + TTS ~₹0.50 (~500 chars) + LLM input ₹0.08–0.23 + output ₹0.02 + post-call ~₹0.05 → **~₹1.1–1.3 (browser), ~₹1.5–1.7 with Plivo (₹0.38/min)**. LiveKit paid usage not included (free tier in dev).

Formula: `cost = STT_min×r_stt + TTS_chars/1000×r_tts + tok_in/1e6×r_in + tok_cached/1e6×r_cached + tok_out/1e6×r_out + postcall + telephony` (rates in `pricing_rates`).

Plans (example): Pay-as-you-go ₹4/min (top-up from ₹500) · 500 min ₹1,750 · 1,000 min ₹3,000 · 5,000 min ₹12,500 · Custom calculator at slab rate. Validity 12 months.

Metering: wallet in seconds; no call below 60 s balance (campaign pauses); per-second metering; agent wraps up at 30 s left; append-only `usage_ledger`; unanswered calls not billed; low-balance alert at 10%; Razorpay checkout + verified webhook (test mode only). Admin margin view: revenue vs API cost per tenant.

## Current scope limits
- No payments in conversations: the agent never takes card/UPI/bank details; it sends a payment link instead.
- Reservations are held 48 h; a booking is confirmed only when the 40% advance is paid via the link (auto, by webhook) or by staff.
- Razorpay test mode only in the college build; payment links shown on the customer's web page (v1), SMS in v1.5.
- No audio recording; transcripts only.
- Future: WhatsApp messages, balance reminder calls, two-way calendar sync (reading the owner's manual calendar entries as blocked dates).

## v1.5: real phone numbers with Plivo
Setup for a registered business: Plivo India account + KYC → rent a Bangalore number (~₹200/month) → LiveKit project region India → inbound trunk + dispatch rule → outbound trunk (termination SIP domain + credentials) → dashboard telephony mode "Phone" → ask Plivo about 160-series for service calls. Outbound: `place_call(job)` creates a SIP participant on the outbound trunk instead of publishing a ring event; SIP status (busy/no answer) maps to the same job states. Inbound: number → LiveKit SIP → dispatch rule → agent. Keep the existing business mobile via conditional call forwarding to the Plivo number. Retune for 8 kHz audio. Compliance: existing customers only, AI disclosure, calling hours, data kept in India. A personal SIM via GSM gateway is not allowed (internet↔PSTN bridging needs a licence; TRAI keeps automated calls off 10-digit numbers).

## v2: tenant document ingestion (any file, any language)

**v1 scope (now):** we ingest our own clean English `docs/knowledge_base.md` and plain typed PDF/DOCX/TXT with basic text extraction. No OCR, no table handling, no translation. Markdown tables stay in one chunk together with their heading. Prices never come from search (`calculate_quote` reads the pricing JSON), so imperfect table retrieval is harmless. A file that can't be parsed is marked `failed`.

**v2 (many businesses upload their own context):** the same Celery `ingest_document` task grows into a pipeline:

| Step | What happens | Tool |
|---|---|---|
| 1. Detect | file type and whether a PDF has a text layer (typed) or is scanned/image-only | pypdf text check, MIME type |
| 2. Parse | typed PDF/DOCX/TXT → text with headings; scanned PDF / photos → OCR with tables preserved as Markdown/HTML | pypdf / python-docx; **Sarvam Document AI / Vision** (22 Indian languages + English, about ₹0.50/page) |
| 3. Normalise | table rows → sentences ("SI-BALE, Bale Ele Oota: ₹650 per plate, min 100 guests…"); drop repeated headers/footers and page numbers; keep the heading path | Python |
| 4. Language | non-English text (Kannada, Hindi, …) → English, so one English embedding model works for every tenant | `text-lid` to detect, **`sarvam-translate:v1`** (2,000 chars/request, chunked) |
| 5. Chunk | split by heading/FAQ item, 200–350 tokens, ~15% overlap only for long sections, heading path prefixed to every chunk | Python |
| 6. Embed + store | bge-small-en-v1.5 (384 dims) → `kb_chunks` with `tenant_id`, `document_id`, `section` | fastembed, pgvector |
| 7. Review | owner sees a preview of the parsed sections/chunks and the "test a question" box before the agent goes live; can re-upload or edit | Knowledge page |
| 8. Structured data | price lists / menus found in documents are offered as a draft pricing JSON for the owner to confirm (prices must stay out of the LLM's own maths) | LLM extraction + owner approval |

Also in v2:
- Store the original file in Storage (`kb-docs/{tenant_id}/…`) and keep `kb_documents.status` + an error message per step.
- Re-ingesting a document replaces only its own chunks (`on delete cascade` by `document_id`) and clears that tenant's search cache.
- Track per-tenant ingest cost (OCR pages, translated characters) in `usage_ledger`.
- Alternative to translating: switch the embedding model to `multilingual-e5-small` (also 384 dims). Translation is preferred because the agent's search queries are English anyway.

## v2 optimizations
| Optimization | Saves |
|---|---|
| Prompt caching (static prefix first; cached input ₹5 vs ₹15 per 1M) | up to ~2/3 of LLM input cost |
| Pre-generated greeting/disclosure/filler/goodbye audio per voice | TTS cost + first-word delay |
| Answer cache in Redis per tenant keyed by normalised English query (cleared on doc upload) | repeated search time |
| Business data (menu, prices, areas, config) in memory at call start | tool latency |
| 60 s availability cache | DB calls |
| Worker prewarm + reused Sarvam WebSocket connections | first-response delay |
| Running summary after ~20 turns; low max_tokens | tokens on long calls |
| Judge on a sample (20%) + all flagged calls | post-call cost |
| Voicemail detection (v1.5 phone) | wasted minutes |

Scaling: RLS policies by `tenant_id`, per-tenant concurrency + Celery routing, more agent workers, space out new Sarvam WebSocket connections. Every optimization measured before/after on the same test suite.

## Build roadmap
1. Talking agent (console) + one verified tool call
2. Knowledge base + tools (hybrid search, quote, availability, reservation, record_answer, fillers) + small text-mode eval harness
3. Language switching
4. Call logging (transcript JSON, turns, tool calls, cost) + guardrails
5. Calling flow (customer page, inbound, scheduler, retries, windows)
6. Post-call owner summaries + Sheets, dashboards, full simulated-caller suite
7. v1.5 phone calls (when a registered business is on board)
8. v2 SaaS (multi-tenant onboarding, document ingestion pipeline with OCR/translation, billing, caching, RLS policies, MCP tool connections)

Deliverables: working v1 demo, 2-minute screen recording of a call, architecture diagram, eval results table across prompt versions, README stating that business data is synthetic and telephony is simulated over WebRTC, with a documented production path.

## Sources
- Sarvam + LiveKit: https://docs.sarvam.ai/api/integration/build-voice-agent-with-live-kit
- Sarvam models: https://docs.sarvam.ai/api/getting-started/models.md
- Sarvam pricing: https://docs.sarvam.ai/api/getting-started/pricing
- Plivo India calling: https://docs.plivo.com/docs/faq/voice-api-and-SIP-trunking/india-calling
- Plivo LiveKit guide: https://www.plivo.com/docs/voice-agents/sip-trunking/integration-guides/livekit.md
- LiveKit Sarvam plugin: https://docs.livekit.io/reference/python/v1/livekit/plugins/sarvam/index.html
- LiveKit quotas: https://docs.livekit.io/cloud/quotas-and-limits
- Supabase connection pooler (IPv4): https://supabase.com/docs/guides/database/connecting-to-postgres
