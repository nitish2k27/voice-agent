# API contracts

Base URL (dev): `http://localhost:8000`. Auth: Supabase JWT in `Authorization: Bearer <token>` for business/admin routes. Verify it with the project's JWKS endpoint (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`), or with the legacy `SUPABASE_JWT_SECRET` if your project still uses HS256. Customer routes use the unguessable `customers.token`. Tenant for v1: `00000000-0000-0000-0000-000000000001`.

The frontend calls Supabase **only for Auth**. All data goes through these endpoints (RLS is deny-all, see `supabase/schema.sql`).

## Agent dispatch metadata (JSON passed to the LiveKit agent)

```json
{
  "tenant_id": "uuid",
  "direction": "outbound | inbound",
  "call_type": "post_event_feedback | enquiry_followup | pre_event_confirmation | inbound",
  "job_id": "uuid | null",
  "campaign_id": "uuid | null",
  "customer_id": "uuid | null",
  "customer": { "name": "...", "phone": "...", "language": "kn-IN", "event_type": "...", "event_date": "YYYY-MM-DD", "venue_area": "...", "zone": 1, "package": "SI-BALE", "guests": 450, "notes": "..." },
  "questions": [ { "key": "food_rating", "text": "How was the food overall? (rating 1-5)" } ],
  "prompt_version": "v1",
  "is_test": false
}
```

At session start the agent loads `agent_configs` (persona, voices, fillers, rules, tools, max_call_seconds, silence_timeout_seconds) by `tenant_id`, and creates the `calls` row.

## Agent lifecycle (v1 guardrails)

| Event | Behaviour |
|---|---|
| Job starts | Create `calls` row (`started_at`). Outbound: wait ≤ 45 s for the customer participant, otherwise outcome `no_answer`, delete the room, exit |
| Customer joins | `answered_at`, speak the opening (`session.say`) |
| Silence ≥ `silence_timeout_seconds` | "Are you still there?" once; another 10 s of silence → goodbye, `ended_by='silence'` |
| `max_call_seconds − 30` reached | Polite wrap-up line; at the max → `ended_by='max_duration'` |
| Customer leaves | `ended_by='customer'` |
| `end_call` tool | Goodbye already said → `ended_by='agent'` |
| Shutdown (always) | Write transcript, turns, tool_calls, usage, cost; set `call_jobs.status`; enqueue `postcall(call_id)`; delete the room |

## Transcript JSON (`calls.transcript`)

No audio is stored. The agent appends one item per final customer utterance and per agent reply (from the session's conversation events):

```json
[
  {"i": 0, "speaker": "agent",    "text": "Namaskara, I'm Amrutha...", "lang": "en-IN", "t": 0.0},
  {"i": 1, "speaker": "customer", "text": "ಹೌದು, ಹೇಳಿ",                 "lang": "kn-IN", "t": 4.8, "lang_conf": 0.93},
  {"i": 2, "speaker": "agent",    "text": "...", "lang": "kn-IN", "t": 6.1, "interrupted": false, "tools": ["search_knowledge_base"]}
]
```
`t` = seconds since `answered_at`.

## Agent tools (function signatures)

The tool schemas use **enums** so the LLM can't invent codes. Package codes, add-on codes and custom item keys are generated from `backend/data/amrith_sagar_pricing.json` at startup.

| Tool | Args | Returns | Filler |
|---|---|---|---|
| `search_knowledge_base` | `query: str` (English keywords) | top 5 chunks as compact text `section: content` | yes (`check`) |
| `calculate_quote` | `package_code: enum \| None`, `custom_items: list[{item: enum, diet: "veg"\|"non_veg", count: int}] \| None`, `adults: int`, `children_5_12: int = 0`, `area: str \| None`, `zone: int \| None`, `add_ons: list[{code: enum, qty: int \| None}] = []`, `event_date: str \| None` | `{ok, line_items[], food_total, discount, add_ons_total, travel, subtotal, gst_note, notes[], errors[]}`. Rules: `quote_rules` in the pricing JSON | no (pure Python) |
| `check_availability` | `date: str (YYYY-MM-DD)`, `guests: int`, `area: str` (English letters) | `{available: bool, reason, area_matched, zone, min_notice_days}` | yes (`check`) |
| `create_tentative_booking` | `customer_name, phone, event_type, event_date, venue_area, guests, package_code, notes` | `{booking_id, hold_until, status: "tentative", advance_amount, payment_link_sent: bool}`. Writes the booking (re-checks availability in the same transaction), creates a Razorpay test Payment Link (40% advance, expires at `hold_until`), pushes the link to the customer (see Booking payments), enqueues `sync_calendar` | yes (`booking`) |
| `schedule_callback` | `reason: str`, `preferred_time: str \| None` | `{callback_id}` | yes (`check`) |
| `record_answer` | `question_key: enum (pending keys)`, `answer: str` (English, short) | `{ok, remaining: [keys]}`; updates `calls.live_answers` and the prompt's pending list | no |
| `end_call` | `reason: str` | ends the session after the goodbye | no |

Every tool call is written to `tool_calls` (args, result, duration_ms, ok).

**Availability rules:** area → zone from `backend/data/areas.json` (unknown → `available=false, reason="unknown_area"`; zone null → `"outside_karnataka"`). Date ≥ today + 15 days (20 for zone 3/4). Date not in `blocked_dates`. Sum of guests in `tentative`+`confirmed` bookings that day (excluding `is_test`) + new guests ≤ 5,000. Guests ≤ 3,000 per event. Zone 3/4 need ≥ 150 guests.

**Search:** `search_knowledge_base` embeds the English query with bge-small-en-v1.5 (fastembed, loaded once in `prewarm`, ~5–20 ms; exact-text LRU cache), then calls SQL `hybrid_search(tenant, query, embedding, 5)` = pgvector cosine + full-text with RRF. `SEARCH_MODE=keyword` passes `null` (fallback if the model fails to load, and for the keyword-vs-hybrid eval).

## Latency definitions (per agent turn, from LiveKit metrics events)

| Column | Meaning | Source (verify names in installed `livekit.agents.metrics`) |
|---|---|---|
| `eou_delay_ms` | customer stopped speaking → end of turn decided | `EOUMetrics.end_of_utterance_delay` |
| `llm_ttft_ms` | LLM request → first token | `LLMMetrics.ttft` |
| `tts_ttfb_ms` | TTS request → first audio byte | `TTSMetrics.ttfb` |
| `total_response_ms` | sum of the three above (server-side perceived latency; browser network not included) | computed |

## REST endpoints

### Customer (no login)
| Method | Path | Body / Notes | Response |
|---|---|---|---|
| POST | `/inbound/start` | `{}` (optional `{name, phone}`). **Rate limited:** 3 per IP per 10 min, max 2 concurrent inbound calls (Redis counters) | `{room, token, livekit_url}` or 429 |
| GET | `/customer/{token}/events` | SSE. On connect, first sends the **current state** (`ringing {room, business_name, seconds_left}` / `idle` / `missed`), then live events `ring`, `cancel` | — |
| POST | `/customer/{token}/join` | accept the ringing call (only while job is `ringing`) | `{room, token, livekit_url}` |
| POST | `/customer/{token}/decline` | decline | `{ok}` |

### Business
| Method | Path | Purpose |
|---|---|---|
| POST | `/onboarding/company` | `{name, city, phone, description}` → creates tenant (v2) / updates the seeded tenant (v1), links `profiles.tenant_id`, creates default `agent_configs` |
| POST | `/onboarding/context` | `{text}` or multipart files → `kb_documents` + enqueue `ingest_document` (chunks embedded here) |
| GET/PUT | `/agent-config` | persona, greetings, voices, fillers, rules, tools_enabled, call limits |
| GET/POST/DELETE | `/blocked-dates` | dates the business can't take |
| POST | `/kb/upload` | multipart file → Storage `kb-docs` → enqueue `ingest_document` |
| GET | `/kb/documents` | list with status + chunk_count |
| POST | `/kb/test` | `{question}` → retrieved chunks (same `hybrid_search` the agent uses) |
| POST | `/campaigns` | `{name, type, questions?, call_window_start, call_window_end}`; questions default from `backend/data/campaign_types.json` |
| POST | `/campaigns/{id}/upload-csv` | multipart CSV → validate columns of `backend/data/sample_customers.csv` → upsert `customers` (by phone) → `call_jobs` |
| POST | `/campaigns/{id}/start` \| `/pause` \| `/resume` \| `/cancel` | set `campaigns.status` (the scheduler reads it) |
| GET | `/campaigns/{id}` | campaign + job counts + `digest` |
| GET | `/campaigns/{id}/jobs` | job list with status + customer link `/c/{token}` |
| GET | `/calls?direction=&from=&to=&outcome=` | call table (headline from `owner_summary`) |
| GET | `/calls/{id}` | call + transcript + turns + tool_calls + result (owner_summary, extracted, judge) |
| GET | `/bookings` / PATCH `/bookings/{id}` | staff confirm/cancel tentative bookings |
| GET | `/callbacks` / PATCH `/callbacks/{id}` | mark done |
| GET | `/billing/wallet` · POST `/billing/order` · POST `/billing/webhook` | v2 demo (Razorpay test mode) |
| POST | `/payments/razorpay/webhook` | public; verify `X-Razorpay-Signature` with `RAZORPAY_WEBHOOK_SECRET`; `payment_link.paid` → booking `confirmed`, `payment_status='paid'`, `paid_at`, `sync_calendar`, confirmation event to the customer page. Idempotent by payment id |

### Admin
| Method | Path | Purpose |
|---|---|---|
| GET | `/admin/metrics/overview?from=&to=` | calls, completion %, avg/P90 latency, avg judge, cost/call (excludes `is_test`) |
| GET | `/admin/metrics/latency` | time series + eou/LLM/TTS breakdown + slow-turn % |
| GET | `/admin/metrics/quality?group_by=prompt_version` | judge averages |
| GET | `/admin/flagged` | calls with flags |
| GET | `/admin/evals` · `/admin/evals/{run_id}` | `eval_runs` / `eval_results` |

## Celery tasks

The DB is the queue's source of truth. Celery `timezone="Asia/Kolkata"`, `worker_prefetch_multiplier=1`, `task_acks_late=True`.

| Task | Queue | Behaviour |
|---|---|---|
| `campaign_tick()` | beat, every 30 s → `calls` | If any job is `ringing`/`in_call` → return. Else pick the oldest `queued`/`no_answer`/`declined` job with `attempts < max_attempts`, `next_attempt_at <= now()`, campaign `running`, now inside the campaign window (IST) → `dial_call.delay(job_id)`. Also: campaign with no pending jobs left → status `completed` + `campaign_digest.delay(id)` |
| `dial_call(job_id)` | `calls` (concurrency 1) | `attempts += 1`, `place_call(job)` (v1: create room `out-{job_id}-{attempt}`, dispatch agent, set `ringing` + `ring_started_at`, publish `ring`). Ring timeout **30 s owned here** → `no_answer`, publish `cancel`, delete room, `next_attempt_at = now()+30 min`. On accept → wait until the agent marks the call ended; every 15 s also check LiveKit `list_rooms`: room gone and no end mark → `failed` (agent crash). Hard timeout = `max_call_seconds + 120` |
| `postcall(call_id)` | `postcall` | skip if outcome is `no_answer`/`declined` → one Gemini call (extraction + owner summary) → Groq judge → `call_results` → Sheets append. 429 → exponential backoff, max 5 retries |
| `campaign_digest(campaign_id)` | `postcall` | one Gemini call over all `owner_summary` rows → `campaigns.digest` |
| `ingest_document(document_id)` | `postcall` | parse (md/pdf/docx/txt) → chunk → **bge-small-en-v1.5 embed (batch, normalised)** → `kb_chunks` → status `indexed`, `tenants.onboarding_status='ready'` |
| `expire_tentative_bookings()` | beat, every 15 min | `tentative` with `hold_until < now()` and not paid → `expired`, `payment_status='expired'`, cancel the payment link, `sync_calendar` |
| `sync_calendar(booking_id)` | `postcall` | create / update / delete the Google Calendar event: "RESERVED – name – guests – area" (tentative), "CONFIRMED – …" (paid or staff-confirmed), removed when expired/cancelled. The DB stays the source of truth for availability |

## Booking payments (advance via payment link)

- The agent never takes payment details. After a reservation it sends a **Razorpay Payment Link** (test mode in v1) for 40% of the quote, expiring with the 48 h hold.
- **v1 (browser):** the link is pushed to the customer's open page: SSE event `payment_link {booking_id, amount, url}` on `/c/:token` (outbound), or a LiveKit data message to the inbound call page. It stays visible on the thanks screen. Razorpay's own email/SMS notify is optional.
- **v1.5 (phones):** Razorpay Payment Link `notify: {sms: true}` (Razorpay handles SMS compliance) or WhatsApp later.
- Paid → webhook confirms the booking → calendar shows CONFIRMED → the customer page shows "Booking confirmed". Staff can still confirm or cancel manually (`PATCH /bookings/{id}`).

## Redis channels and keys

- `customer:{customer_token}` (pub/sub) → `{"type":"ring","room":"out-<job_id>-<n>","business_name":"Amrith Sagar Catering","seconds_left":30}` / `{"type":"cancel"}` / `{"type":"payment_link","booking_id":...,"amount":...,"url":...}` / `{"type":"booking_confirmed","booking_id":...}`
- `job:{job_id}:status` (pub/sub, optional) → live dashboard updates
- `rl:inbound:{ip}` (counter, TTL 600 s), `inbound:active` (counter) → inbound rate limits

## Key metrics SQL (examples)

```sql
-- avg and P90 response latency, last 7 days
select avg(total_response_ms) avg_ms,
       percentile_cont(0.9) within group (order by total_response_ms) p90_ms,
       avg((total_response_ms > 3000)::int) slow_turn_rate
from turns t join calls c on c.id = t.call_id
where t.speaker = 'agent' and t.total_response_ms is not null
  and not c.is_test and c.started_at > now() - interval '7 days';

-- question coverage and completion (answered calls only)
select avg(questions_answered::float / nullif(questions_total,0)) coverage,
       avg((c.outcome = 'completed')::int) completion_rate
from call_results r join calls c on c.id = r.call_id
where not c.is_test;

-- groundedness and cost per completed call
select avg((r.judge_scores->'groundedness'->>'score')::numeric) groundedness,
       avg(c.api_cost_inr) cost_per_call
from call_results r join calls c on c.id = r.call_id
where not c.is_test and c.outcome = 'completed';
```
