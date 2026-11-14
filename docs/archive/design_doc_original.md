> **Archived 2026-11-12. Superseded by `docs/architecture.md`.** Kept for reference only. Out of date on audio recording (now transcripts only), query-time embeddings (now ingest-only) and the call queue design.

# Voice Calling Agent — System Design (v1 / v1.5)

Nov 12, 2026 · @nitish

## Overview

A multilingual AI voice agent that makes outbound calls (feedback, follow-ups, confirmations) and answers inbound calls (enquiries, quotes, tentative bookings) for a catering business in Bangalore, then logs every conversation and its key outcomes to Supabase and Google Sheets.

**v1 (this build) uses browser calling, not the phone network.** Customers and the agent meet in a LiveKit room over WebRTC. A phone-style web page simulates incoming and outgoing calls. Everything else is real: Sarvam speech, the LLM, tools, the Celery queue, retries, transcripts, extraction and evaluation.

**v1.5 adds real phone numbers through Plivo.** Plivo is not used in v1 because Indian domestic calling requires a registered Indian business entity and KYC (Certificate of Incorporation + GST), an India-rented caller ID and INR billing. The project has no registered business yet. A business owner with those documents can switch on phone calling without changing agent code (see the v1.5 section).

**v2 (future)** turns the same engine into multi-tenant SaaS: each business uploads its documents and picks its tools; no code changes per client.

| Version | Calls happen over | Who can use it | Needs business KYC |
| --- | --- | --- | --- |
| v1 | Browser (WebRTC, LiveKit rooms) | Anyone with the link | No |
| v1.5 | Phone network (Plivo SIP trunk into LiveKit) | Real customers on their phones | Yes |
| v2 | Both, per tenant | Many businesses | Per tenant |

## Tech stack

Sarvam handles all Indian-language speech; LiveKit runs the real-time call loop; Supabase holds data and vectors; Celery + Redis run the call queue.

| Layer | Choice | Role |
| --- | --- | --- |
| Frontend | React + JavaScript | Business dashboard, admin dashboard, customer call page |
| API | FastAPI | Auth, campaigns, configs, uploads, room tokens |
| Database + vectors | Supabase Postgres + pgvector | All tables, document chunks, hybrid search (vector + full-text) |
| Queue | Celery + Redis (Docker), Celery beat | Calls one after another, retries, scheduled campaigns; ARQ as fallback |
| Voice framework | LiveKit Agents; rooms on LiveKit Cloud Build plan (free), agent worker runs locally | Rooms, streaming pipeline, turn-taking, interruptions |
| Speech to text | Sarvam Saaras v4 (language auto-detect) | Live transcription, code-mixed speech |
| Text to speech | Sarvam Bulbul v4 Flash | Voice output, switched per detected language |
| Live LLM | sarvam-105b-conversations (reasoning off) | The conversation itself, tool calls |
| Post-call extraction | Gemini Flash | Transcript to structured JSON in English |
| Evaluation judge + simulated caller | Groq free tier (a model still on Groq's free list) or Gemini as backup | LLM-as-judge scores, persona test suite |
| Embeddings | BGE-M3 (local, CPU) | Multilingual embeddings for the knowledge base |
| Output | Supabase tables + Google Sheets (gspread) | Results the business reads |
| Telephony | None in v1; Plivo in v1.5 | Phone network access |

Each LLM is a config value (`LIVE_LLM`, `EXTRACT_LLM`, `JUDGE_LLM`), so models can be swapped and compared.

### Free-tier setup (₹0 except Sarvam)

Every part runs on a free tier or on the laptop; only Sarvam (STT, TTS, live LLM) is paid, from existing credits.

| Part | Free option | Limit that matters |
| --- | --- | --- |
| Voice rooms | LiveKit Cloud Build plan | 5,000 WebRTC minutes a month; hard cap, no surprise bills. Agent session minutes (1,000) count only for agents deployed to LiveKit Cloud, so the worker runs locally |
| Database + vectors | Supabase free | 500 MB database, 1 GB file storage; pauses after 7 days idle (open it weekly or run a scheduled ping) |
| Queue | Redis in Docker + Celery | Runs locally |
| Embeddings | BGE-M3 on CPU | Runs locally (\~2 GB download) |
| Extraction | Gemini API free tier (Flash or Flash-Lite) | Low daily request limits; one call per finished call. Synthetic data only on free tiers |
| Judge + simulated caller | Groq free tier | Per-model daily limits; model name kept in config because free models change |
| Recordings | Agent saves audio to Supabase Storage | Inside the 1 GB free storage |
| Sheets | Google Sheets API (gspread) | Free |
| Payments (billing demo) | Razorpay test mode | No real money |
| Hosting | Frontend on Cloudflare Pages; API, worker and agent on the laptop | Cloudflare Tunnel for a public demo link |

Rule: Sarvam handles every turn of the conversation; free LLM tiers are used only after the call (one extraction, one judge score), and prompt testing is done in text mode against the simulated caller to save Sarvam credits.

## System architecture

&#91;embedded content: system architecture · v1 browser calls, v1.5 phone path dashed\]

Dashboards talk to FastAPI; Celery dispatches the agent into a LiveKit room; the customer joins by WebRTC in v1 or by phone through Plivo in v1.5; every call is logged to Supabase and processed after hang-up into Google Sheets.

## End-to-end flows

Four flows make up the system: outbound campaign, inbound call, the live conversation loop shared by both, and post-call processing.

### 1. Outbound campaign (v1)

1. Business uploads a customer CSV and picks a campaign type in the dashboard.
2. FastAPI validates rows, creates a `campaigns` row and one `call_jobs` row per customer, then enqueues one Celery `dial_call` task per job on the `calls` queue.
3. The `calls` worker runs with concurrency 1, so customers are called one after another, only inside the calling window (Celery beat schedules the start).
4. `dial_call` creates a LiveKit room, dispatches the agent with metadata (customer row + agent config + campaign questions), and sends a "ring" event to that customer's call page.
5. Customer accepts → joins the room → conversation (flow 3). Declines or no response in 30 s → job marked `no_answer` and retried after 30 minutes, at most 3 attempts.
6. On hang-up the agent writes the call, transcript and turn timings to Supabase and enqueues `postcall` (flow 4). The `calls` worker moves to the next customer.

### 2. Inbound call (v1)

1. Customer opens the "Call us" link (or scans the QR code) and presses Call.
2. FastAPI issues a room token; LiveKit creates the room and dispatches the agent with the business config (no customer row).
3. Agent greets in Kannada and English, then follows the caller's language.
4. Conversation (flow 3): answers from documents, gives quotes, checks dates, makes tentative bookings, or logs a callback request.
5. On hang-up: same logging and `postcall` as outbound.

### 3. Live conversation loop

1. Customer speaks → Sarvam Saaras v4 streams the transcript with the detected language.
2. Language changed for 2 consecutive utterances (3+ words each) → Bulbul voice and language are switched before the next reply.
3. sarvam-105b-conversations reads the system prompt (persona, goal, customer row, pending questions, rules) plus the conversation so far.
4. Needs a fact or an action → it calls a tool. The tool first speaks a filler ("One second, let me check that date"), then runs. Knowledge searches always use an English query against the English documents.
5. Reply streams to Bulbul v4 Flash, which starts speaking the first sentence while the rest is still being generated (target: about 1–1.5 s from end of speech to start of reply).
6. Customer can interrupt at any point; the agent stops and listens.
7. Python tracks which campaign questions are answered and keeps the remaining ones in the prompt, so the agent returns to topic after tangents.

### 4. Post-call processing (`postcall` queue)

1. Re-transcribe the recording with Sarvam batch STT + diarization for a clean, speaker-labelled transcript.
2. Gemini Flash extracts the campaign's fields into English JSON (e.g. food rating, complaints, would rebook).
3. Groq judge scores the transcript (groundedness, policy, naturalness, on-topic, language match) and raises flags.
4. Results are saved to `call_results`, appended to the Google Sheet, and shown on both dashboards.

## What the business client sees

The business owner logs in to a dashboard with seven pages; nothing on it requires code, and evaluation internals stay hidden (admin only).

1. **Login / onboarding**
   - Sign in (email + password via Supabase Auth).
   - First-time setup wizard: business name, address, service areas, working hours, languages to support (Kannada, English, Hindi, Tamil, Telugu).
2. **Home (overview)**
   - Cards: calls today, completed, no-answer, bookings created, average satisfaction.
   - Recent calls list with outcome badges and a link to each call.
3. **Business knowledge**
   - Upload documents in English: menu, packages and per-plate prices, FAQs, policies (PDF, DOCX, TXT).
   - Shows each document's status: uploaded, chunked, indexed, failed.
   - "Test a question" box: type a question, see the answer and which document chunk it came from.
4. **Agent settings**
   - Agent persona: name, tone, greeting line, voice per language.
   - Rules: never offer discounts, hand complaints to a human, AI disclosure line at call start.
   - Tools on/off: availability check, quote calculator, tentative booking, callback request.
   - Booked dates and daily capacity (or a connected Google Calendar).
5. **Campaigns (outbound)**
   - New campaign: pick type (post-event feedback, enquiry follow-up, pre-event confirmation), upload customer CSV, review the question list, set the calling window.
   - CSV columns: name, phone, language, event date, event type, package, guest count, notes.
   - Live progress: queued, calling, completed, no answer (retry at …), failed.
   - Pause, resume, cancel.
6. **Inbound**
   - In v1: the shareable "Call us" link and its QR code for customers.
   - In v1.5: the business phone number and call-forwarding instructions.
   - List of inbound calls with what was asked and what was done.
7. **Calls and results**
   - Filterable table of every call: customer, type, language, duration, outcome.
   - Call detail: audio recording, full transcript (original language + English), extracted fields, follow-up flag.
   - Download as CSV and a link to the connected Google Sheet.

An eighth page, **Billing**, shows minutes left, usage, plans and invoices (see Billing and minute plans).

Example of the results a feedback campaign writes per call: customer, event date, food rating, service rating, complaints, would rebook, referral given, summary.

## Customer call page (v1)

In v1 the customer's "phone" is a mobile-friendly web page that behaves like a call screen; it joins a LiveKit room and talks to the agent by voice.

- **Incoming call (outbound campaign):** the customer opens their personal link (sent once, e.g. on WhatsApp). When the queue reaches them, the page rings: "Incoming call from \<business name>" with Accept and Decline. Accept joins the room; Decline or no response in 30 seconds counts as "no answer" and is retried later.
- **Call us (inbound):** a public page with one "Call us" button. Pressing it creates a room, the agent joins and greets the caller.
- **During the call:** caller name or number, call timer, mute, speaker, hang up, and a small live-caption strip (optional, helps the demo).
- **After the call:** "Thanks for calling" screen; the call is already queued for post-call processing.
- **Permissions:** the page asks for microphone access once; works in Chrome on Android and desktop.

The agent cannot tell this page from a phone caller: both are participants in a LiveKit room, so the same agent code serves v1 and v1.5.

## Admin and evaluation dashboard

The admin (developer) dashboard is separate from the client's and measures how well the agent performs; v1 starts with five core metrics: response latency, question coverage, completion rate, groundedness score and cost per call.

| Metric group | Metrics | How it is measured |
| --- | --- | --- |
| Latency | Average and P90 response time; STT / LLM / TTS / tool breakdown; slow turns (>3 s) % | Per-turn timings from LiveKit metrics events |
| Task success | Question coverage %, completion rate, goal achieved %, tool success rate, handoff rate | Call and turn tables + post-call extraction |
| Conversation quality | Naturalness, on-topic, groundedness (no invented facts), policy compliance, empathy, language match (1–5 each) | LLM-as-judge (Groq) on each transcript |
| Speech | Interruption rate, talk ratio, dead-air gaps, "please repeat" count, offline word error rate | Turn timings; hand-checked sample of \~20 clips |
| Reliability | System-caused failures, retry success rate, API errors per provider | Call outcomes + error logs |
| Cost | Cost per call and per minute; cost per completed survey or booking | STT minutes, TTS characters, LLM tokens |

Targets for v1: average response under 1.5 s, P90 under 2.5 s, slow turns under 5%.

**Offline test suite:** a simulated caller (Groq) plays 20–30 personas: happy customer, angry about cold food, Kanglish speaker, one-word answers, off-topic talker, asks for a discount, asks for an unavailable date. It runs in text mode after every prompt change, so prompt versions can be compared in one table.

**Admin pages:** top-line cards; latency over time with breakdown; quality scores per prompt version; flagged calls (hallucination, policy break, slow, dropped) opening to transcript, recording and per-turn timings; test-suite results per version.

## Billing and minute plans

The admin pays every API bill, so each business buys prepaid call minutes, priced from the measured cost per minute plus a margin; calls run until the balance is used up.

### Cost per call minute (what the admin pays)

Estimates for one minute of conversation, using published rates; the admin dashboard replaces them with measured averages once real calls exist.

| Cost item | Rate | Assumption per call minute | Approx. cost per minute |
| --- | --- | --- | --- |
| Sarvam STT (Saaras) | ₹0.49 per audio minute | 1 minute streamed | ₹0.49 |
| Sarvam TTS (Bulbul v4 Flash) | ₹1.00 per 1,000 characters | \~500 characters spoken by the agent | ₹0.50 |
| Live LLM input (sarvam-105b-conversations) | ₹15 per 1M tokens (₹5 cached) | \~5 turns × \~3,000 tokens of context | ₹0.08–₹0.23 |
| Live LLM output | ₹60 per 1M tokens | \~5 turns × \~60 tokens | ₹0.02 |
| Post-call extraction + judge (Gemini / Groq) | per token | spread over the call's minutes | \~₹0.10 |
| LiveKit Cloud agent and room minutes | per LiveKit plan | free tier during development | check current pricing |
| Plivo telephony (v1.5 only) | \~₹0.38 per minute, 30-second pulse | 1 minute | ₹0.38 |
| **Total** |  |  | **\~₹1.2–₹1.4 (browser), \~₹1.6–₹1.8 (phone)** |

Formula used by the backend for every call:

```latex
\text{cost} = \text{STT}_{min} \times r_{stt} + \frac{\text{TTS}_{chars}}{1000} \times r_{tts} + \frac{\text{tok}_{in}}{10^6} r_{in} + \frac{\text{tok}_{cached}}{10^6} r_{cached} + \frac{\text{tok}_{out}}{10^6} r_{out} + \text{post-call} + \text{telephony}
```

The rates live in a `pricing_rates` table, so a provider price change is a data update, not a code change.

### Plans the business can buy (example prices)

Prices are set at roughly 2–3× the cost per minute to cover failed calls, testing and margin. For comparison, Sarvam's own hosted voice agents start from ₹3 a minute.

| Plan | Minutes | Price | Per minute | Validity |
| --- | --- | --- | --- | --- |
| Pay as you go | any top-up from ₹500 | ₹4.00 per minute | ₹4.00 | 12 months |
| Starter pack | 500 | ₹1,750 | ₹3.50 | 12 months |
| Growth pack | 1,000 | ₹3,000 | ₹3.00 | 12 months |
| Business pack | 5,000 | ₹12,500 | ₹2.50 | 12 months |
| Custom | any amount the business enters | calculated live | slab rate for that amount | 12 months |

The Custom option shows a calculator: enter minutes (or expected calls × average call length), see the price at the slab rate, pay.

### How metering works

1. **Wallet:** each business has a balance in seconds. Purchases add seconds; calls subtract them.
2. **Before a call:** the queue checks the balance. Below 60 seconds → the call is not placed, the campaign pauses, and the owner is notified.
3. **During a call:** usage is metered per second. The agent receives the remaining balance; at 30 seconds left it wraps up politely ("I'll have our team call you back") and ends the call.
4. **After a call:** billed seconds are written to an append-only `usage_ledger` (call ID, seconds, billed amount, actual API cost). Unanswered calls are not billed.
5. **Low balance:** an alert at 10% remaining, and an optional auto top-up.
6. **Payments:** Razorpay checkout; the payment webhook (signature verified) credits the wallet. The college build uses Razorpay test mode only, with no real money.

### Billing page (client)

Shows minutes left, a usage graph by day, cost per campaign, a plan picker with the custom calculator, invoices with GST, and transaction history.

### Margin view (admin)

For every business: revenue from minutes sold vs actual API cost (from the ledger), margin per minute, and the cost split by provider, so pricing can be adjusted when real averages differ from the estimates above.

## Data model (Supabase)

Nine tables cover v1; every table carries `tenant_id` from day one so v2 multi-tenancy needs no migration.

| Table | Key columns | Purpose |
| --- | --- | --- |
| tenants | id, name, city, languages, created\_at | One row per business (one in v1) |
| agent\_configs | tenant\_id, persona, greeting, rules, voices (per language), tools\_enabled, prompt\_version | Everything that makes the agent this business's agent |
| kb\_documents | tenant\_id, file\_name, status, uploaded\_at | Uploaded business documents |
| kb\_chunks | tenant\_id, document\_id, content, embedding vector(1024), fts tsvector | Chunks for hybrid search (HNSW + GIN indexes) |
| campaigns | tenant\_id, type, questions, extraction\_schema, call\_window, status | One outbound campaign |
| call\_jobs | campaign\_id, customer (jsonb), status, attempts, next\_attempt\_at, celery\_task\_id | One customer to call; mirrors Celery state for the dashboard |
| calls | tenant\_id, job\_id, direction, language, room\_name, started\_at, ended\_at, outcome, ended\_by, recording\_url, transcript (jsonb), cost fields | One row per call |
| turns | call\_id, index, speaker, text, language, stt\_ms, llm\_ttft\_ms, tts\_ms, total\_ms, interrupted, tool\_name, tool\_ms, tool\_ok | Per-turn timing and tool data for evaluation |
| call\_results | call\_id, extracted (jsonb), questions\_answered, judge\_scores (jsonb), flags, synced\_to\_sheet | Post-call extraction and evaluation |

Booked dates live in a small `bookings` table (date, guests, status: tentative / confirmed) unless Google Calendar is connected.

Billing adds four tables: `wallets` (tenant\_id, balance\_seconds, low\_balance\_alert, auto\_topup), `payments` (tenant\_id, razorpay\_order\_id, amount, minutes, status), `usage_ledger` (append-only: call\_id, seconds, billed\_amount, api\_cost) and `pricing_rates` (provider, unit, rate, valid\_from).

## v1.5: real phone numbers with Plivo

A registered business owner can move from browser calls to real phone calls by adding a Plivo India number and two LiveKit SIP trunks; the agent, tools, queue and dashboards stay the same.

**Why it is not in v1:** Plivo allows domestic Indian calling only for businesses registered in India, after KYC. It needs a Certificate of Incorporation and GST certificate, the caller ID must be a Plivo India number, call media must stay in India, and billing is in INR on an Indian card. Voice KYC takes about an hour to one business day. Using a personal or business mobile SIM through a GSM gateway instead is not allowed (internet-to-phone-network bridging needs a licence), and TRAI rules keep automated calls off ordinary 10-digit numbers.

**Setup for a business owner:**

1. Request a Plivo India-region account and submit KYC (Certificate of Incorporation + GST).
2. After approval, rent one Bangalore number (about ₹200 per month at the published rate).
3. In LiveKit Cloud, set the project region to India (required for Indian calls).
4. Create an **inbound trunk**: point the Plivo number at the LiveKit SIP URI, and add a dispatch rule that sends each call to a new room with the catering agent.
5. Create an **outbound trunk**: Plivo termination SIP domain + username/password, stored in LiveKit.
6. In the dashboard's Agent settings, switch telephony mode from "Browser" to "Phone" and enter the trunk ID and number.
7. Ask Plivo whether outbound feedback calls at your volume need a 160-series (service/transactional) number.

**How calls flow in v1.5:**

- **Outbound:** Celery `dial_call` dispatches the agent to a new room → the agent asks LiveKit to create a SIP participant on the outbound trunk → Plivo rings the customer's phone → on answer, the customer's audio enters the room. No answer or busy comes back as a SIP status and is retried as in v1.
- **Inbound:** customer dials the Plivo number → Plivo sends the call to LiveKit SIP → the dispatch rule creates a room and the agent joins → same conversation loop.
- **Keeping the existing business mobile number:** set conditional call forwarding (busy / no answer) on the business mobile to the Plivo number. Customers keep dialling the number they know; missed calls go to the AI receptionist. Operator charges for forwarded calls apply.

**What changes in code:** only the dial step. In v1 it sends a "ring" event to the customer's web page; in v1.5 it creates a SIP participant. Phone audio is 8 kHz, so re-check speech recognition accuracy after switching.

**Compliance basics:** call only existing customers who expect contact, disclose at the start that this is an AI assistant, respect calling hours, and keep recordings and transcripts in India (Supabase region + LiveKit India region).

## v2 optimizations

v2 cuts cost per minute and latency mainly through caching, with smaller gains from shorter LLM context and cheaper post-call work; each change is measured against the v1 baseline on the admin dashboard.

| Optimization | What it does | Saves |
| --- | --- | --- |
| Prompt caching | Static part of the prompt (persona, rules, business facts, tool definitions) always comes first and stays identical; the customer row and pending questions come after. Repeated prefixes bill at the cached input rate (₹5 vs ₹15 per 1M tokens). | Up to \~2/3 of LLM input cost |
| Pre-generated phrase audio | Greetings, AI disclosure, fillers ("One second, let me check"), goodbyes and the low-balance wrap-up are synthesized once per voice and language, stored, and played directly. | TTS cost on those phrases; zero delay on the first words |
| Semantic answer cache | Redis cache per tenant keyed by the embedding of the English search query; a close match (similarity above a tuned threshold) returns the stored knowledge-base chunks without a vector search. Cleared when the tenant uploads new documents. | Search time on repeated questions (prices, packages, Jain/veg options) |
| Embedding cache | Query embeddings cached by exact text, so repeated queries skip the BGE-M3 call. | CPU time per turn |
| Business data in memory | Menu, packages, prices and config loaded into Redis or the worker's memory at call start, not read from Postgres on every tool call. | Tool latency |
| Short-lived tool cache | Availability for a date cached for about 60 seconds, so the same date asked twice in a call is not re-checked. | Database and calendar calls |
| Warm workers and connections | LiveKit worker prewarm loads models before calls arrive; Sarvam WebSocket connections are reused from the plugin's pool. | First-response delay |
| Shorter context | After about 20 turns, older turns are replaced by a short running summary; output capped with a low max\_tokens. | LLM input tokens and latency on long calls |
| Cheaper post-call work | Extraction on a small, fast model; the LLM judge runs on a sample (e.g. 20% of calls) plus every flagged or low-score call. | Post-call cost |
| Call guardrails | Maximum call length, hang-up after a long silence, voicemail detection so unanswered calls do not consume minutes. | Wasted minutes (the business's balance and the admin's API bill) |

**Scaling for many businesses:** Row Level Security on every table by `tenant_id`; per-tenant concurrency limits and Celery queues routed by tenant; more agent workers added as call volume grows; rate limits kept under Sarvam's per-account WebSocket limits by spacing out new connections.

**How it is evaluated:** cost per minute, average and P90 latency, and judge scores before and after each optimization, on the same simulated-caller test suite, so a saving never silently lowers quality.

## Current scope limits

The agent books tentatively and never handles money; payment collection, payment verification and booking confirmation stay manual in this version.

- **No payments in conversations:** the agent never collects or verifies card, UPI or bank details. Customers are told the team will share payment details after the call.
- **Tentative bookings only:** a booking made by the agent is held for 48 hours. Staff confirm it manually after the 40% advance arrives and update its status in the dashboard.
- **No automatic confirmation messages:** written confirmations are sent by staff.
- **Future scope:** payment links over SMS/WhatsApp (e.g. Razorpay payment links), a payment webhook that auto-confirms the booking, reminder calls for balance payments, and calendar sync.

This is separate from the Billing section above, which covers businesses paying the platform for call minutes, not customers paying the caterer.

## Build roadmap

Build in six steps, each usable on its own; steps 1–4 are a complete v1 for the college project.

1. **Talking agent:** `agent.py console` with Sarvam STT/TTS + sarvam-105b-conversations; Kannada ↔ English switching works; one tool call (`check_availability`) confirmed.
2. **Knowledge + tools:** upload page, chunking + BGE-M3 + pgvector hybrid search, `search_knowledge_base`, `calculate_quote` (math in Python), `create_tentative_booking`, filler lines during tool calls.
3. **Calling flow:** customer call page (incoming + Call us), Celery + Redis queue, campaigns from CSV, retries, call windows.
4. **Post-call + dashboards:** diarized transcript, Gemini extraction, Google Sheets sync, client dashboard pages, admin metrics (the five core ones first), simulated-caller test suite.
5. **v1.5 phone calls:** Plivo trunk + LiveKit SIP once a registered business is on board; 8 kHz re-tuning; call forwarding from the business mobile.
6. **v2 SaaS:** multi-tenant onboarding (upload documents, pick tools, pick voices), minute plans and Razorpay billing, the caching and cost optimizations, Row Level Security per tenant, tool connections (Google Calendar, later via MCP), per-tenant evaluation.

**Deliverables for evaluation:** working v1 demo, a 2-minute recorded call, the architecture diagram, the evaluation results table across prompt versions, and a README stating that business data is synthetic and the telephony leg is simulated over WebRTC with a documented production path.

### Sources

- [Sarvam: build a voice agent with LiveKit](https://docs.sarvam.ai/api/integration/build-voice-agent-with-live-kit)
- [Sarvam models overview](https://docs.sarvam.ai/api/getting-started/models.md)
- [Sarvam pricing](https://docs.sarvam.ai/api/getting-started/pricing)
- [Plivo: India calling requirements](https://docs.plivo.com/docs/faq/voice-api-and-SIP-trunking/india-calling)
- [Plivo: requirements for calls to India](https://old-support.plivo.com/hc/en-us/articles/45875255505305-Requirements-for-Sending-SMS-and-Calls-to-India)
- [Plivo LiveKit integration guide](https://www.plivo.com/docs/voice-agents/sip-trunking/integration-guides/livekit.md)
- [LiveKit Python reference: Sarvam plugin](https://docs.livekit.io/reference/python/v1/livekit/plugins/sarvam/index.html)
