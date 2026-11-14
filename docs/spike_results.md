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
