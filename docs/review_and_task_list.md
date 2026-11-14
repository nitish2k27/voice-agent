# Spec review + implementation task list

Review: 2026-11-12. Fixes applied to the spec pack on the same day. This file records **what changed and why**, so later decisions stay consistent.

## Owner decisions (2026-11-12)

1. **No audio recording.** Each call is stored as a JSON transcript. After every call an LLM keeps only what matters for the owner (`call_results.owner_summary`). After each campaign it writes one digest (`campaigns.digest`). Removed: `recorder.py`, the recordings bucket, `recording_path`, the batch-STT diarization step.
2. **Small embedding model, real hybrid search** (updated later on 2026-11-12). BGE-M3 (~2.2 GB) is too heavy for a laptop, so the model is `BAAI/bge-small-en-v1.5` via fastembed (ONNX, ~130 MB, 384 dims). Chunks are embedded at ingest (onboarding / upload); during calls only the short English query is embedded (~10 ms). Search = vector + Postgres full-text fused with RRF. Keyword-only stays as the fallback and the eval baseline.

3. **Reservation + calendar + payment link** (added 2026-11-12). The agent reserves the date under the customer's name (48 h), mirrors it to the business Google Calendar, and sends a Razorpay (test mode) payment link for the 40% advance. It never takes payment details and never says "confirmed". Payment (webhook) confirms the booking automatically. Milestone 7.5.

## What was fixed

| # | Problem found | Fix applied | Where |
|---|---|---|---|
| A1 | RLS off on all tables while the anon key ships in the frontend | RLS enabled deny-all on every table; frontend uses Supabase only for Auth | `schema.sql`, `api_contracts.md`, `CLAUDE.md` |
| A2 | Direct Supabase DB host is IPv6-only | Pooler URL in `.env.example`, Milestone 0 and CLAUDE facts | `.env.example`, `build_plan.md` |
| A3 | No mechanism for live question tracking | `record_answer` tool + `calls.live_answers` + `update_instructions` | `prompts.md`, `api_contracts.md`, `schema.sql` |
| A4 | Prompt had no current date | `{today}` (IST) in the dynamic tail | `prompts.md` |
| A5 | No area → zone mapping | `backend/data/areas.json` with aliases (incl. Kannada script), fuzzy match; LLM passes area in English letters | `backend/data/areas.json` |
| A6 | Tool calls not stored, judge needs them | `tool_calls` table | `schema.sql` |
| A7 | Questions / extraction fields / Sheet columns spread over 3 docs and inconsistent | `backend/data/campaign_types.json` single source (also owner summary fields) | `data/` |
| A8 | Ring was fire-and-forget; 30 s timeout lived in the browser | Server-owned ring state (`ring_started_at`), SSE sends current state on connect | `api_contracts.md`, `schema.sql` |
| A9 | No call guardrails in v1 | Wait-for-participant 45 s, silence hang-up, max call length (per tenant config) | `api_contracts.md`, `schema.sql` |
| A10 | Public `/inbound/start` with no limits | Per-IP rate limit + concurrency cap (Redis) | `api_contracts.md` |
| A11 | `pricing_rates` seed duplicated on re-run | `unique(provider, valid_from)`; whole schema is now idempotent | `schema.sql` |
| A12 | Pricing ambiguities | `quote_rules` block (paying guests, ">500" means 501+, add-ons on paying guests at full price, bar tiers, zone 4, 2027 note, rounding) + 11 test cases | pricing JSON, `build_plan.md` |
| B1 | Agent would import the API package | Restructured (2026-11-13) to `backend/` + `frontend/` + `supabase/`; `backend/app/` layered routers → services → repos → db; agent/worker reuse services/repos only | `CLAUDE.md`, `architecture.md` |
| B2 | Celery `retry(countdown)` made retries invisible and pause/cancel hard | DB-driven scheduler: beat `campaign_tick` + `next_attempt_at`; IST timezone | `api_contracts.md` |
| B3 | Agent crash stalls the queue for 10 min | `dial_call` also checks LiveKit `list_rooms` | `api_contracts.md` |
| B4 | TTS voice could mismatch the LLM's script | Hysteresis sets the instructed language; `tts_node` picks the voice from the reply's script | `build_plan.md` M3 |
| B5 | BGE-M3 (~2.2 GB) loaded per agent process | Replaced by bge-small-en-v1.5 via fastembed (~200 MB RAM per process, no torch) | everywhere |
| B6 | `websearch_to_tsquery` ANDs all words | `kb_or_query()` ORs keywords; `hybrid_search` works with a null embedding | `schema.sql` |
| B7 | No customers table | `customers` (phone unique per tenant, personal link token) | `schema.sql` |
| B8 | Evals would write real bookings | `is_test` on customers, jobs, calls, bookings, callbacks; excluded from metrics and availability | `schema.sql` |
| B9 | Missing tables | `eval_runs`, `eval_results`, `blocked_dates`, `agent_configs.fillers`, one active config per tenant, signup trigger for `profiles` | `schema.sql` |
| B10 | Prompt versions had no home | `backend/agent/prompts/v1.txt`… | `prompts.md` |
| B11 | Evals would test a copy of the agent | LiveKit text-only test mode with the same `Agent` class | `build_plan.md` M2.5 |
| B12 | No disclosure about transcription | "This call is transcribed for quality" in both openings and the KB policy | `prompts.md`, `knowledge_base.md` |
| C | `end_call` missing from prompt/tools; missing handover rules; two campaign-start descriptions; no enums; no `declined` outcome; HTTPS needed for phone mic; JWKS vs JWT secret; duplicate design doc; unsplit requirements; KB package count | All fixed; duplicate moved to `docs/archive/`; `backend/requirements/` split | various |
| New | Embeddings needed a trigger point | Company onboarding flow (company details → paste context / upload docs → ingest) + `/onboarding/*` endpoints + Onboarding page | `architecture.md`, `api_contracts.md`, `build_plan.md` |

## Still open: decide while building

- **Live LLM fallback** if sarvam-105b tool calling is unreliable (Milestone 1). Candidate options go into `LIVE_LLM_FALLBACK`.
- **Real Bulbul v4 Flash speaker IDs** per language (fetch from Sarvam docs in Milestone 3).
- **Exact LiveKit API names** (`update_instructions`, `tts_node`, metrics classes, text test mode): verify in the installed package.
- The online design and KB artifacts are older than this review; the repo files win.

## Implementation task list (in order)

### Step 1, now
1. `git init` and a first commit of this spec pack.
2. Milestone 0 by hand: LiveKit, Sarvam, Supabase (Mumbai) → run `supabase/schema.sql` → `kb-docs` bucket → **session pooler** URL, Gemini, Groq + model, Google service account + Sheet + Calendar, Razorpay test keys, Docker / Python 3.11 / Node 20.

### Step 2 onward: follow `docs/build_plan.md`
3. M0 scaffold + `check_env.py`
4. M1 console spike (tool calling, reasoning off, language detection, latency → `docs/spike_results.md`)
5. M2 quote (11 tests) → areas/availability/bookings → ingest (bge-small embeddings) + hybrid search → tools incl. `record_answer` → prompt builder
6. M2.5 starter eval harness (6 personas, text mode)
7. M3 language switching
8. M4 transcript JSON / turns / tool_calls / cost + guardrails
9. M5 browser calling (inbound + customer page, HTTPS)
10. M6 campaigns with the `campaign_tick` scheduler
11. M7 post-call: extraction + owner summary + English transcript, judge, Sheets, campaign digest; M7.5 calendar + payment link
12. M8 dashboards (incl. onboarding)
13. M9 full eval suite; M10 stretch
