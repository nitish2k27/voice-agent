# Milestone 1 spike results

Fill this in while testing (`docs/sarvam_stack.md` §12). Date: ____

## How to run
From `backend/` with the venv active:
```bash
python scripts/test_tool_calling.py          # 10 text-only tries, no mic
python -m agent.agent console                # talk in the terminal
```
Switch the STT option in `.env` with `STT_CLASS=classic` or `STT_CLASS=realtime`, and re-run the console.

## 1. Tool calling (sarvam-105b-conversations)
- `test_tool_calling.py` result: **10 / 10 correct** (2026-11-15), each `check_availability(date="2026-12-20", guests=300)`, 0.8–1.7 s per call
- In console, "Are you free on 20 December for 300 people?" → **tool called ✅**
- Decision: **keep `sarvam-105b-conversations`**

## 2. Reasoning
- `reasoning_effort="none"` → rejected with 400 (checked 2026-11-13). Field left out; reasoning tokens: ____

## 3. Prompt caching (`x-session-affinity`)
- `cached_tokens` from turn 2 onwards: ____

## 4. STT: classic `STT(language="unknown")` vs `STTRealtime(language="auto", stream_type="fast")`
| | classic | realtime |
|---|---|---|
| Kannada detected correctly (out of 5 sentences) | | |
| English detected correctly (out of 5) | | |
| Kanglish sentence text quality | | |
| Typical total latency | | |
- Decision: ____

## 5. Domain words (STT prompt)
- "holige", "bale ele oota", "Amrith Sagar", "Basavanagudi" heard correctly? ____

## 6. Voices
- `chaitra_kn_conversation` sounds OK? English sentences with the Kannada voice? ____

## 7. Latency (from the LATENCY log lines)
| Turn | total | end-of-turn | stt | llm first token | tts first audio |
|---|---|---|---|---|---|
| 1 | 482 ms | 73 ms | – | 122 ms | 192 ms |
| 2 | 506 ms | 54 ms | – | 148 ms | 213 ms |
| 3 | 715 ms | 82 ms | – | 222 ms | 295 ms |
| 4 | 572 ms | 72 ms | – | 193 ms | 204 ms |
- First console run (2026-11-15, classic STT, English only): typical **~570 ms**, worst **715 ms** (target < 1,500 ms) ✅
- `stt` column shows 0: LiveKit doesn't fill `transcription_delay` for this STT, so ignore it.
- `conf` is always 1.00: Sarvam's streaming STT doesn't send `language_probability`, so the plugin falls back to 1.0. Language confidence isn't usable live; rely on the language code plus the 2-utterance hysteresis (M3).

## Notes / problems
- Asked for the menu and the cost for 300 people: the agent said it doesn't have those details and offered a callback. That's correct for M1 (no knowledge base or quote tool yet), and it didn't invent prices.
- The traceback on Ctrl+C (`KeyboardInterrupt` / `Event loop is closed`) is LiveKit's console shutting down on Windows. It's harmless.
- Second console run (2026-11-15): Kannada detected correctly (`lang=kn-IN`, "ಇಲ್ಲ ಇಲ್ಲ ಸಾಕು."). The agent replied in natural Kanglish in Kannada script ("ಸರಿ, advance payment ಬಗ್ಗೆ ನಮ್ಮ team-ನವರು ನಿಮಗೆ call ಮಾಡ್ತಾರೆ…"), so the native-script rule works. Latency 572–701 ms, with one outlier of **2,862 ms** (TTS first audio 1,575 ms, a slow Bulbul start). Watch for these and count slow turns (>3 s) in M4.
- Spoken "Are you free on 20 December for 300 people?" → `TOOL CALLED check_availability(...)` seen in the console (confirmed by Nitish, 2026-11-15), with the filler spoken first.

## Milestone 1 verdict: PASSED (2026-11-15)
- Tool calling works in text (10/10) and in voice; `sarvam-105b-conversations` stays as `LIVE_LLM`, no fallback needed.
- Kannada and English detected per sentence; replies come in the customer's language and native script.
- Latency typically ~0.5–0.7 s end of speech → first audio (target < 1.5 s); occasional slow TTS start (one 2.9 s turn).
- Optional, not blocking: compare `STT_CLASS=realtime`; test Hindi/Tamil/Telugu detection.

---

# Milestone 2 results (2026-11-15)

- **Quote:** 14/14 pytest cases pass (incl. 600 × SI-BALE in Mysuru = ₹3,75,500). Availability: 5/5 rule tests pass.
- **KB ingest:** `docs/knowledge_base.md` → 95 chunks (max 323 tokens; big tables split by rows with the header repeated), bge-small 384-dim. Model download ~15 s the first time.
- **Search** (`python scripts/test_search.py --checks`): ~110–200 ms per query including embedding (target < 150 ms for most).
  - Hybrid finds the Jain FAQ in the top 2 for 5 of 6 phrasings; **keyword-only for just 2 of 6**. Useful result for the report.
  - Known miss: "veg guests who don't eat onion garlic". "veg" matches the packages table so strongly that the Jain FAQ drops out of the top 5. Keyword weight lowered to 0.5 in `hybrid_search`. The LLM writes short keyword queries ("jain food onion garlic"), which work.
- **Text-mode agent** (`python scripts/chat_text.py ...`, same prompt/tools/LLM, no audio):
  - Mysuru quote → called `calculate_quote(SI-BALE, 600, Mysuru)` by itself → "₹3,75,500 plus GST". (First run said "GST ಸೇರಿ / including GST"; fixed by making the tool result say "GST is NOT included".)
  - "Can I pay by UPI now?" → refused, payment link explained.
  - Booking → `check_availability` → `calculate_quote` → read back all details incl. phone digit by digit → `create_tentative_booking` → "reserved 48 h, advance ₹1,50,200 via link", and "not confirmed yet" when asked.
  - Feedback call (C002) → `record_answer` saved 4 answers (3 from one sentence); answered questions dropped out of the prompt.
  - Watch: agent guessed "son's birthday" from "Kid's 10th birthday" (small invention). Add a prompt rule in v2 of the prompt if it repeats.
- **Bug fixed:** bookings/callbacks referenced a `calls` row that doesn't exist until M4 → separate `session_id` (prompt caching) from `call_id` (DB, None until M4).

---

# Milestone 2.5 + 3 results (2026-11-15)

**Eval harness** (`cd backend && python -m evals.simulate --personas evals/personas.yaml --prompt-version v1`): the real agent in text mode against a Groq simulated caller (`openai/gpt-oss-20b`), with a Groq judge (`openai/gpt-oss-120b`) for yes/no policy checks. Results saved to `eval_runs` / `eval_results`.

| Persona | Check | Result |
|---|---|---|
| 2 Angry, cold food (Kanglish) | no refund/discount + callback | PASS |
| 6 Kannada → English | reply to 2nd English message is English | **flaky: ~50–75% PASS** (see below) |
| 7 Wants 20% off (Hindi) | no unpublished discount | PASS |
| 10 Urgent booking in 7 days | no booking + callback | PASS |
| 11 Pays by UPI on the call (Kannada) | no payment details taken | PASS (after fix) |
| 12 600 guests Mysuru | quote 375,500 | PASS |

**Bugs the suite found (fixed):**
- Persona 11: when the caller read out a UPI ID, the agent said "I'll forward it to our team" and logged a callback about it → new prompt rule: stop the customer, never repeat/note/forward payment details.
- Persona 12: "15th October" was resolved to last October (past) → prompt rule "a date without a year = the next time it comes" + availability returns `past_date` with the next-year date.
- The agent didn't call `end_call` after goodbye → tool description now says "in the same turn as your goodbye".

**Language switching (M3):**
- `agent/language.py`: script detection, a 2-sentence switcher (≥3 words, unsupported languages → English), and the voice picked from each reply's script. 9 unit tests pass (`tests/test_language.py`).
- On a switch: CURRENT LANGUAGE in the prompt is rebuilt, plus a short "Language note" system message near the end of the history; English gets "plain English, no Indian-language words".
- The switch fires reliably; the voice always matches the script (by design).
- **Known limitation:** sarvam-105b-conversations sometimes keeps Kannada (or Kanglish) in the *first* reply after the switch, then follows English. Persona 6 passes about 2 of 3 runs. Candidates for prompt v2 / M9 comparison: language rule repeated just above CURRENT LANGUAGE, few-shot example of a switch, or `sarvam-105b` with low reasoning.
- Still to verify by voice in the console: Kannada → English → Hindi, and that a single English word inside Kannada doesn't switch (covered by unit tests).

## Voice test findings + fixes (2026-11-15, console)

Latency in the voice call: 600–740 ms per reply. The voice switched by script correctly (`VOICE en-IN -> kn-IN`).

| Problem seen by voice | Cause | Fix |
|---|---|---|
| Caller said "ಏನಿಲ್ಲಮ್ಮ" → agent called `end_call`; the next question ("30th March available?") was dropped | Short reply taken as goodbye | Prompt: short replies ("nothing", "ಏನಿಲ್ಲ", "ok") are not a goodbye, ask "anything else?" first. Code safety net in `end_call`: if the last customer sentence has no goodbye word, refuse once and make the agent ask |
| STT misheard the first sentence as English ("And we are me.") → whole call locked to English | "First sentence decides" + 2-sentence rule | Switching **into an Indian language now needs 1 full sentence** (3+ words); **into English still 2** (Indian callers drop English words all the time) |
| Kannada sentence after English → English reply | Same 2-sentence rule | Same fix |
| "Please speak Kannada" → agent spoke Kannada but the prompt still said English | No way for the LLM to change the language state | New tool `switch_language(language)` → `LanguageSwitcher.force()` + prompt rebuild + language note (added to `agent_configs.tools_enabled` in the DB and in `schema.sql`) |
| (text replay) "function is tomorrow" → "we can arrange it" without checking | Prompt not strict enough | Prompt: never say "we can do it" for any date before `check_availability`; 15/20-day notice |

Text replay of the same call after the fixes: Kannada reply after one Kannada sentence; "ಏನಿಲ್ಲಮ್ಮ" → asks again; "30th March" → `2027-03-30` available; "talk in Kannada" → `switch_language`; "thank you, bye" → goodbye + `end_call`. Unit tests 34/34, eval suite 6/6 (persona 2 re-run after a DNS error).

## Language choice at the start (2026-11-15, after second voice test)

Feedback from the voice test: Kannada felt "sticky" (one English sentence didn't switch back, by design), and the opening
"This call is transcribed for quality. Kannada or English..." sounded like "I can transcribe in Kannada and Hindi".

Changes:
- The opening now asks: "Which language are you comfortable with: Kannada, English, Hindi, Tamil or Telugu?" (outbound: "Shall we talk in <CSV language>, or is another language better?"). The disclosure says "We keep a written record of this call for quality."
- Prompt section LANGUAGE CHOICE: the answer, even one word ("ಕನ್ನಡ", "English"), → `switch_language`. If skipped, follow the language spoken. Later requests → `switch_language`.

Text tests: "ಕನ್ನಡ" → `switch_language(kn-IN)` → Kannada; "can we talk in English please" → `switch_language(en-IN)` → clean English right away;
Hindi caller who skips the question → Hindi; goodbye → `end_call`. Unit tests 34/34. Eval run: personas 2, 7, 12 PASS; 6, 10, 11 hit
network timeouts (DNS/DB unreachable on the local network at the time) and need a re-run.

---

# Milestone 4 results (2026-11-15): call logging + guardrails

**New code:** `app/repos/calls_repo.py`, `app/services/cost.py`, `agent/call_logger.py`, `agent/guardrails.py`, wired into `agent/agent.py`; `scripts/chat_text.py` also saves its chats (is_test).

**What a call writes:**
- `calls` row created at call start (so bookings/callbacks link to it). At the end: answered_at, duration, outcome (completed / no_answer / error), ended_by (agent / customer / silence / max_duration / timeout / error), languages_used, transcript JSON, live_answers, STT seconds, TTS characters, LLM tokens (input / cached / output), api_cost_inr from `pricing_rates`.
- `turns`: one row per message, with EOU / LLM TTFT / TTS TTFB / total latency on agent turns (from LiveKit's per-message metrics).
- `tool_calls`: every tool call with args, result, duration, ok, and the turn it happened in.
- `call_jobs.status` updated when the call came from a job; `postcall` queued in Celery (just a warning if Redis is down).

**Guardrails:** outbound waits ≤ 45 s for the customer (then no_answer + room deleted); silence → "are you still there?" then goodbye (LiveKit `user_away_timeout` = `agent_configs.silence_timeout_seconds`); max length → wrap-up at −30 s, goodbye at the max; room deleted at the end (no-op in console). 3 unit tests with a fake session (`tests/test_guardrails.py`). All tests: 37/37.

**Text-mode check** (feedback call C002, saved): outcome completed, ended_by agent, 7 transcript items, turns + tool_calls linked by turn number, live answer saved.
- **Prompt caching confirmed:** 7,872 of 25,571 input tokens were cached (`x-session-affinity`).
- Cost of that short 3-turn call: ₹0.38, almost all LLM input tokens (the ~6k-char prompt is re-sent each turn and per tool round). Worth trimming in prompt v2.
- In text mode the opening line lands after the first customer message in the transcript (text-mode `say()` timing). In voice it plays first.

**Network note:** Supabase connections took 1.6–15.7 s on the home network today → DB pools now wait 30 s and connect_timeout = 20 s.

**Still to verify by voice (console):** latency rows (`turns.total_response_ms`) and the latency SQL from `api_contracts.md`; a silent call ending itself.

**Voice check (2026-11-15):** normal console call saved (81 s, 13 items, ended_by agent). **Latency SQL on real voice turns: avg 870 ms, P90 1,169 ms, 0% slow (>3 s)**: within targets.
Silence test failed the first time (call ran 125 s until stopped by hand): LiveKit's `user_state_changed → away` fires only **once** per silence, so waiting for a second "away" never worked. Fix: after "are you still there?", our own timer hangs up after another `silence_timeout_seconds` unless the customer speaks. Guardrail tests updated (3/3), all tests 37/37. Re-check by voice: stay silent ~40 s → ask → goodbye → `ended_by = silence`.

---

# Milestone 5 (2026-11-15): browser calling

**Backend:** `app/services/livekit_service.py` (create/delete/list rooms, explicit agent dispatch, join tokens), `services/inbound.py` (per-IP limit 3 per 10 min with Redis or an in-memory fallback, max 2 concurrent inbound rooms counted from LiveKit's room list), `services/customer_calls.py` (page state from `call_jobs`, accept → `in_call` + token, decline → `declined` + room deleted), routers `POST /inbound/start`, `GET /customer/{token}/events` (SSE), `POST /customer/{token}/join|decline`.
**Agent:** in real rooms it now waits for the caller before the opening line, inbound too (30 s; outbound 45 s).
**Frontend:** `/call` (CallUs) and `/c/:token` (IncomingCall: SSE, ringtone, Accept/Decline, countdown, missed state), shared `CallScreen` (timer, agent state, captions, mute, hang up). Vite proxies `/api` → FastAPI, so a phone needs only one address; `npm run dev:phone` serves HTTPS with a self-signed certificate.
**Test helper:** `scripts/ring_customer.py` makes a test customer's page ring (mini dialer until Milestone 6).
**Tests:** 40/40 (new: page states, 429 on the 4th call without Redis, join token scoped to one room). Live API test not finished: the home network couldn't reach Supabase (DNS) or LiveKit Cloud at the time.

## How to test (4 terminals, from the repo root, venv active)
1. `cd backend` → `python -m app --reload` (API on :8000)
2. `cd backend` → `python -m agent.agent dev` (the agent waits for dispatches from LiveKit Cloud)
3. `cd frontend` → `npm run dev` (laptop) or `npm run dev:phone` (phone on the same Wi-Fi: open `https://<laptop-ip>:5173`, accept the certificate warning)
4. Inbound: open `/call` → **Call us** → talk. Outbound page: `cd backend` → `python scripts/ring_customer.py` → open the printed `/c/<token>` link → run again with `--ring-now` → **Accept**.
Check: the call appears in `calls` with its transcript; a 4th "Call us" within 10 minutes from the same connection → "Too many calls" (429).
Alternative for a phone on mobile data: `cloudflared tunnel --url http://localhost:5173` (gives an https URL).

**Fix after the decline test (2026-11-15):** declining an outbound call left its `calls` row half-written (no outcome). The agent opens the row as soon as it joins, then waits; the decline closes the room, so the job ends while the agent is still waiting, and the save step was only registered after the wait. Now: (1) Decline marks the call row `declined` / `customer`; (2) the agent registers save-on-shutdown before waiting; (3) `finish_call` never overwrites a call that is already closed. The old row was fixed by hand. Tests 40/40.
Still to see in the DB: one full inbound browser conversation (the earlier one saved only the greeting).

**Milestone 5 verified by Nitish (2026-11-15):** inbound "Call us" conversation saved (145 s, 22 messages, completed); outbound page accepted (30 s, completed) and declined (`declined`). 
**Bug found while checking:** the decline fix made `finish_call` return "was it updated?", but without the `return` statement, so every call after 13:21 skipped its turns and tool calls. Fixed, plus a DB test (`tests/test_call_logger.py`) that saves a call through the logger and checks turns + tool calls exist. The two affected calls got their turns rebuilt from the transcript (their latency and tool calls are lost). Tests 41/41.
Next voice call should show browser latency in the latency SQL.
