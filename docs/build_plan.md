# Build plan — milestones for Claude Code

Work through these in order. Each milestone has a goal, tasks, and acceptance criteria. Don't start the next milestone until the current one passes. Milestones 0–8 = complete v1 for the college project. 9–10 are stretch.

Suggested prompt to Claude Code at each step:
> Read CLAUDE.md and docs/build_plan.md. Implement Milestone N. Check the installed library source for any API you are not sure about. When done, show me how to verify the acceptance criteria.

Global rules that apply to every milestone:
- No audio recording. Calls are stored as a JSON transcript (`calls.transcript`) and summarised for the owner after the call.
- Embedding model = `BAAI/bge-small-en-v1.5` via fastembed (384 dims) for both chunks (ingest) and queries (search). Never BGE-M3 or torch.
- Layout: `backend/` (all Python; run commands from there) + `frontend/` + `supabase/` + `docs/`. Inside `backend/app/`: routers → services → repos → db, plus core/ and schemas/ (CLAUDE.md → Repo layout). `agent/` and `worker/` reuse `app.services`/`app.repos`, never `app.routers`.
- Mark everything created by tests/evals with `is_test=true`.

---

## Milestone 0 — Accounts, keys, scaffold

**Do by hand (Nitish):**
1. LiveKit Cloud: create a free project (Build plan) → copy `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`.
2. Sarvam: API key from dashboard.
3. Supabase: new project (region: Mumbai/ap-south-1) → run `supabase/schema.sql` in the SQL editor → copy `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`. For `DATABASE_URL` use **Connect → Session pooler** (`postgresql://postgres.<ref>:<password>@aws-0-ap-south-1.pooler.supabase.com:5432/postgres`), not the direct `db.<ref>.supabase.co` host (IPv6-only). Create the private Storage bucket `kb-docs` (no recordings bucket: audio is not stored).
4. Google AI Studio: Gemini API key. Groq console: API key; note a model currently on the free list.
5. Google Cloud: service account with Sheets API **and Calendar API** enabled → download JSON to `secrets/` → share a Google Sheet "Amrith Sagar — Call Results" and a Google Calendar "Amrith Sagar — Bookings" ("Make changes to events") with the service account email.
5b. Razorpay: test-mode account → test key id/secret → webhook secret (webhook URL is set in Milestone 7.5).
6. Install Docker Desktop (only for Redis), Python 3.11, Node 20.
7. Sign up once in the app later (Milestone 8) or in Supabase Auth → run the commented `update profiles ...` line at the bottom of `schema.sql` to make yourself admin of the tenant.

**Claude Code tasks:**
- Repo layout from CLAUDE.md (folders and `__init__.py` files already created): `backend/app/core/config.py` (pydantic-settings, reads the repo-root `.env`, resolves data/secret paths from the repo root), `app/core/deps.py`, `app/core/security.py`, `app/db/session.py` (psycopg v3 pools with the pooler URL), `app/main.py` with `/health`, loaders `app/services/campaign_types.py` and `app/services/areas.py`.
- `backend/requirements/` split (already created): `base.txt`, `agent.txt`, `api.txt`, `ingest.txt` (pypdf, python-docx), `dev.txt` (pytest, ruff, honcho). Pin versions after the first working install. `backend/requirements.txt` includes all for convenience.
- `docker-compose.yml` (Redis), Vite React JS app in `frontend/` (layout in `frontend/README.md`, env in `frontend/.env.example`), root `Procfile` for `honcho start` (each line `cd backend && …`: api, agent, calls worker, postcall worker, beat; plus `cd frontend && npm run dev`).
- `backend/scripts/check_env.py`: verifies every key in `.env.example` is set and connects to Supabase (pooler, `select 1`), Redis, LiveKit (list rooms), Sarvam (tiny TTS call), Gemini, Groq, Google Calendar (create + delete a test event). Google Sheets is optional: checked only if `GOOGLE_SHEET_ID` is set, otherwise reported as SKIPPED.

**Accept when:** `python backend/scripts/check_env.py` prints OK for all services; `docker compose up -d redis` works; `npm run dev` shows a blank app.

---

## Milestone 1 — Talking agent in the terminal (de-risk spike)

**Tasks:**
- `backend/agent/agent.py` using the session config in CLAUDE.md (vad=None, turn detection "stt", min_delay 0.07), Saaras v4 `language="unknown"`, `sarvam-105b-conversations` (find the option that turns reasoning off), Bulbul v4 Flash.
- Register the worker with `agent_name="amrutha"` (explicit dispatch).
- Temporary system prompt: Amrutha persona + AI disclosure + today's date + "reply in the customer's language".
- One dummy tool `check_availability(date: str, guests: int)` returning a fixed string, with a spoken filler before it.
- Log every final STT event: text, `language`, `language_confidence`. Print per-turn latency (EOU + LLM TTFT + TTS TTFB).
- Work through the checklist in `docs/sarvam_stack.md` §12 (tool calling, reasoning none, caching header, STT vs STTRealtime, prompt biasing, voices, latency) and write findings in `docs/spike_results.md`.

**Accept when:**
- `cd backend && python -m agent.agent console` → you can talk in Kannada, then English, then Kannada; logs show the detected language per utterance.
- "Are you free on 20 December for 300 people?" makes the LLM **call the tool** with `date="2026-12-20"` (logged). If tool calling fails in more than 2 of 10 tries → configure `LIVE_LLM` fallback and note it.
- Typical response latency printed per turn.

---

## Milestone 2 — Knowledge base + real tools

**Tasks:**
- `backend/app/services/quote.py`: `calculate_quote(...)` implementing `quote_rules` in `backend/data/amrith_sagar_pricing.json` (paying guests, child pricing, slabs, zone travel, add-on units, bar setup tiers, min-guest checks, 2027 note). Returns line items + subtotal + `gst_note`.
- `backend/tests/test_quote.py` (pytest) with at least these cases:
  1. 600 adults SI-BALE zone 3 → 375,500 (doc example)
  2. 500 adults SI-CLASSIC zone 3 → 5% discount, travel 8,000 (not "above 500")
  3. 501 adults SI-CLASSIC zone 3 → travel 5,000
  4. 1,000 adults NI-VEG zone 1 → 8% discount
  5. 100 adults + 20 children NI-VEG + LIVE-CHAAT → child plates at 60%, add-on on 120
  6. 25 adults JP-CLASSIC → ok=false (min 30)
  7. 120 adults zone 3 → ok=false (zone min 150)
  8. Zone 4 → travel null + "quoted by our team" note
  9. Custom menu with 5 dishes → ok=false (min 6); with 6 → base 120 + items
  10. 250 guests BAR-SETUP → tier 500; 600 guests → ok=false
  11. Event in 2027 → revision note
- `backend/app/services/areas.py`: lookup from `backend/data/areas.json` (exact alias → fuzzy ≥0.85 → unknown).
- `backend/app/services/availability.py`: rules in `docs/api_contracts.md` (notice days by zone, `blocked_dates`, 5,000 plates/day, 3,000 per event, zone 3/4 min 150; ignore `is_test` bookings).
- `backend/app/services/bookings.py`: reservation (hold 48 h, availability re-checked in the same transaction, advance = 40% of quote), callbacks. Payment link + calendar come in M7.5.
- `backend/app/services/kb_ingest.py` + Celery task `ingest_document` (v1 scope: clean markdown + plain typed PDF/DOCX/TXT only; no OCR/translation, which are v2, see `docs/architecture.md` → v2: tenant document ingestion): parse md/pdf/docx/txt, keep markdown tables in one chunk with their heading, split by markdown headings, FAQs per question, keep `section` path, **embed with bge-small-en-v1.5 via fastembed (normalised, batch)**, insert into `kb_chunks`. CLI (from `backend/`): `python -m app.services.kb_ingest ../docs/knowledge_base.md` (source `seed`).
- `backend/app/services/embedder.py`: fastembed `TextEmbedding("BAAI/bge-small-en-v1.5")`, lazy singleton, LRU cache by query text; agent loads it in `prewarm`.
- `backend/app/services/search.py`: `search(tenant_id, query_en, k=5)` → embed query → SQL `hybrid_search`; `SEARCH_MODE=keyword` passes `null` (fallback).
- `backend/agent/tools.py`: `search_knowledge_base`, `calculate_quote` (enums from the pricing JSON), `check_availability`, `create_tentative_booking`, `schedule_callback`, `record_answer` (updates live answers + `update_instructions`), `end_call`. Fillers only on the slow tools (see `docs/prompts.md`). Log every call to an in-memory tool log (persisted in M4).
- `backend/agent/prompts.py` + `backend/agent/prompts/v1.txt`: build the prompt from the template + `agent_configs` + customer row + `backend/data/campaign_types.json` + today's date (IST).

**Accept when:**
- Ingest creates chunks with 384-dim embeddings; `python scripts/test_search.py "jain food price"` (from `backend/`) returns the Jain FAQ; the paraphrase "veg guests who don't eat onion garlic" returns it in hybrid mode; "cancel charge refund" returns the cancellation policy; query embedding + search < 150 ms.
- All quote tests pass.
- In console: "What's the price for a South Indian wedding feast for 600 people in Mysuru?" → agent quotes ₹3,75,500 plus GST; "Can I pay now?" → refuses; "Book it for 10 Jan" → reads back details, creates a tentative booking row; in a feedback test call, answering "food was 5 out of 5" triggers `record_answer("food_rating", ...)` and the question disappears from the prompt.

---

## Milestone 2.5 — Minimal text-mode eval harness (moved up from M9)

**Tasks:** `backend/evals/personas.yaml` with the starter set (personas 2, 6, 7, 10, 11, 12 from `docs/prompts.md`), `backend/evals/simulate.py` using LiveKit Agents' text-only test mode (same `Agent` class and tools, no audio) against a Groq simulated caller, max 20 turns, all DB writes `is_test=true`; expected checks asserted in code; results to `eval_runs` / `eval_results`.

**Accept when:** `cd backend && python -m evals.simulate --personas evals/personas.yaml --prompt-version v1` prints pass/fail per persona. Re-run after every prompt change from now on.

---

## Milestone 3 — Mid-call language switching

**Tasks:** `backend/agent/language.py`:
- Hysteresis on STT finals: switch CURRENT LANGUAGE after 1 full sentence (≥3 words) in an Indian language, or 2 in a row into English → rebuild the prompt tail → `update_instructions` (+ language note). `switch_language` tool for explicit requests. (Changed from "2 for every language" after the 2026-11-15 voice test.)
- `tts_node` override: detect the script of each LLM reply (Kannada / Devanagari / Tamil / Telugu / Latin) → `tts.update_options(target_language_code, speaker)` before synthesis. Latin with a Hindi or Kannada session → keep that language's voice (code-mix).
- `VOICES` map per language with real Bulbul v4 Flash speaker IDs from Sarvam docs (same persona feel where possible); unsupported language (ml, or) → fall back to en-IN.
- Pass the current language to tools for filler phrases.

**Accept when:** in console, switching Kannada → English → Hindi changes the agent's language within 2 utterances; a single English word inside Kannada does **not** switch; the voice never reads text in the wrong script (persona 6 passes).

---

## Milestone 4 — Call logging + guardrails (no audio)

**Tasks:** `backend/agent/call_logger.py`:
- Create the `calls` row at start; build the transcript JSON (format in `docs/api_contracts.md`) from conversation events; write `turns` with EOU/TTFT/TTFB/total from LiveKit metrics events; flush the tool log to `tool_calls`; usage counters (STT seconds, TTS chars, tokens) and `api_cost_inr` from `pricing_rates`.
- Guardrails from `docs/api_contracts.md` → Agent lifecycle: wait-for-participant 45 s, silence timeout, max call length with wrap-up, room deletion.
- On shutdown (always, also on errors): finalise the call row, update `call_jobs.status`, enqueue `postcall`.

**Accept when:** after a console call, `calls` (with transcript JSON and live_answers), `turns` and `tool_calls` exist; average and P90 latency come from the one SQL query in `api_contracts.md`; a call left silent ends itself.

---

## Milestone 5 — Browser calling (customer pages + inbound)

**Tasks:**
- `backend/app/services/livekit_service.py`: create/delete room, explicit agent dispatch with metadata, access tokens, list rooms.
- Backend: `POST /inbound/start` (room `in-{uuid}`, dispatch, token; Redis rate limit + concurrency cap), `GET /customer/{token}/events` (SSE; sends current state on connect), `POST /customer/{token}/join`, `POST /customer/{token}/decline`.
- Frontend: `CallUs` page (one big button, mic permission, call screen with timer, mute, hang up, optional live captions) and `IncomingCall` page (`/c/:token`) that rings on `ring` with Accept/Decline, countdown from `seconds_left`, and a "missed call" state.
- Serve over HTTPS for the phone test (Cloudflare Tunnel or `vite --https`).

**Accept when:** on a phone browser over HTTPS, "Call us" connects to Amrutha and a full conversation works; the call appears in `calls` with its transcript; a 4th inbound attempt within 10 minutes from the same IP gets 429.

---

## Milestone 6 — Outbound campaigns (Celery + Redis)

**Tasks:** campaign CRUD (questions default from `backend/data/campaign_types.json`) + CSV upload (validate columns of `backend/data/sample_customers.csv`, upsert `customers` by phone, create `call_jobs`); Celery app (IST timezone, prefetch 1, acks_late) with `calls` queue (concurrency 1) and `postcall` queue; beat `campaign_tick` (30 s) as the scheduler; `dial_call(job_id)` → `place_call(job)` (v1 = ring event), server-owned 30 s ring timeout, wait for the end mark + LiveKit room check, retry by setting `next_attempt_at` (+30 min, max 3); pause/resume/cancel via campaign status; beat `expire_tentative_bookings` (15 min).

**Accept when:** uploading the sample CSV for a feedback campaign rings each customer page one after another; declining schedules a retry visible in the DB; pausing stops new calls within 30 s; closing the customer tab during ringing still moves the job to `no_answer` after 30 s; killing the agent mid-call marks the job `failed` and the queue continues.

---

## Milestone 7 — Post-call pipeline (owner summary)

**Tasks:** `postcall(call_id)`: (1) skip unanswered calls; (2) **one Gemini call** with transcript JSON + tool log + live answers → `{extracted, owner_summary}` (prompt in `docs/prompts.md` §2), validate with Pydantic models built from `backend/data/campaign_types.json`, one retry with the error; (3) Groq judge rubric → `judge_scores` + flags; (4) save `call_results` (questions_answered from live answers ∪ extraction); (5) **optional:** if `GOOGLE_SHEET_ID` is set, append a row to the campaign's Sheet tab via gspread (column order = `sheet_columns`); always offer a per-call Markdown summary and a per-campaign CSV download from the dashboard (`GET /calls/{id}/export.md`, `GET /campaigns/{id}/export.csv`). `campaign_digest(campaign_id)` when a campaign completes. Handle free-tier 429s with backoff + retry.

**Accept when:** each finished call produces a valid `call_results` row with an owner summary (and a Sheet row if Sheets is configured) within ~1 minute; a completed campaign gets a digest.

---

## Milestone 7.5 — Reservation: Google Calendar + payment link

**Tasks:** `backend/app/services/calendar.py` (Calendar API via service account: create/update/delete event), Celery `sync_calendar(booking_id)`; `backend/app/services/payments.py` (Razorpay test Payment Link for the advance, expires at `hold_until`; cancel on expiry); `create_tentative_booking` creates the link and pushes it to the customer (SSE `payment_link` on `/c/:token`, LiveKit data message on the inbound page); `POST /payments/razorpay/webhook` (signature check, idempotent) → booking `confirmed` → `sync_calendar` → `booking_confirmed` event; expiry task also expires the link and the event. Customer pages show the link and the confirmation.

**Accept when:** booking in a call shows a "RESERVED" event in the calendar and a payment link on the customer page within seconds; paying with a Razorpay test card flips the booking to confirmed, the event to "CONFIRMED" and shows the confirmation; an unpaid booking expires after the hold (test with a short hold) and the event disappears; the agent never says "confirmed" (persona 18 passes).

---

## Milestone 8 — Dashboards

**Business (client) pages:** Login, **Onboarding** (company details → paste context / upload docs → ingest status), Home cards, Knowledge (upload → ingest status, "test a question"), Agent settings (persona, voices, fillers, rules, tools on/off, blocked dates, call limits), Campaigns (create, upload CSV, live progress, pause/resume, digest), Inbound (Call-us link + QR), Calls (table with owner headline + detail: owner summary → extracted fields → transcript → tool calls), Bookings & callbacks (reservation status, payment status, calendar link; staff can confirm/cancel manually).

**Admin pages:** Overview (calls, completion %, avg latency, avg judge score, cost/call), Latency (avg/P90 over time, EOU/LLM/TTS breakdown), Quality (judge scores per prompt version), Flagged calls, Test suite results.

Keep it simple: plain tables + one chart library. Frontend calls FastAPI only (Supabase client only for Auth).

**Accept when:** the five core metrics (response latency, question coverage, completion rate, groundedness, cost per call) display correctly from real calls, excluding test rows.

---

## Milestone 9 — Full evaluation suite (strongly recommended for the report)

**Tasks:** all 25 personas in `backend/evals/personas.yaml`; judge every transcript; `backend/evals/report.py` produces a table per prompt version (coverage, groundedness, policy, naturalness, expected-check pass rate, avg turns) and optionally keyword vs hybrid search.

**Accept when:** one command produces a comparison table for prompt v1 vs v2.

---

## Milestone 10 — v2 demo features (stretch)

Billing page (wallet, plans, custom-minutes calculator, Razorpay **test mode** checkout + webhook signature verification, usage ledger), balance check in `campaign_tick` and a polite wrap-up at 30 s left; prompt caching layout check (static prefix first); pre-generated filler/greeting audio cache; multi-tenant onboarding (new tenant per signup) + RLS policies; tenant document ingestion pipeline (OCR via Sarvam Document AI, table normalisation, sarvam-translate to English, chunk preview), see `docs/architecture.md`.
