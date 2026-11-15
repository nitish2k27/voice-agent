# Saves every call to the database (Milestone 4). No audio: just text and numbers.
#
#   start()   -> creates the calls row (so bookings/callbacks made during the call can point to it)
#   on_item() -> every message added to the conversation becomes a transcript item + a turns row
#   finish()  -> writes transcript JSON, turns, tool calls, usage, cost; sets the job status; queues post-call
#
# finish() is safe to call twice (only the first call does anything).

import asyncio
import logging
import time
from datetime import datetime, timezone

from agent.language import script_language
from app.db.session import get_sync_conn
from app.repos import calls_repo
from app.services import cost

log = logging.getLogger("amrutha.logger")


def ms(seconds):
    return int(seconds * 1000) if seconds is not None else None


class CallLogger:
    def __init__(self, state, room_name, job_id=None):
        self.state = state
        self.room_name = room_name
        self.job_id = job_id
        self.started = time.time()
        self.answered = None          # set when the customer is in the call
        self.transcript = []          # [{"i", "speaker", "text", "lang", "t", ...}]
        self.turns = []               # rows for the turns table
        self.last_user_metrics = {}
        self.tools_seen = 0
        self.finished = False

    # ---------------------------------------------------------------- start
    async def start(self):
        row = await asyncio.to_thread(self._insert_call)
        self.state.call_id = row["id"]
        log.info("calls row %s created", self.state.call_id)

    def _insert_call(self):
        s = self.state
        with get_sync_conn() as conn:
            return calls_repo.insert_call(conn, {
                "tenant_id": s.tenant_id, "job_id": self.job_id, "customer_id": s.customer_id,
                "direction": s.direction, "call_type": s.call_type, "room_name": self.room_name,
                "language_initial": s.current_language, "prompt_version": s.config.get("prompt_version"),
                "is_test": s.is_test,
            })

    def mark_answered(self):
        if self.answered is None:
            self.answered = time.time()

    # ---------------------------------------------------------------- during the call
    def on_item(self, event):
        """conversation_item_added handler: one transcript item + one turns row per message."""
        msg = event.item
        role = getattr(msg, "role", None)
        if role not in ("user", "assistant"):
            return
        text = msg.text_content or ""
        if not text.strip():
            return
        if role == "user":
            self.mark_answered()

        m = getattr(msg, "metrics", None) or {}
        index = len(self.transcript)
        self.state.turn_count = index + 1
        speaker = "customer" if role == "user" else "agent"
        lang = self.state.last_heard_language if role == "user" else script_language(text)

        item = {"i": index, "speaker": speaker, "text": text, "lang": lang,
                "t": round(time.time() - (self.answered or self.started), 1)}
        turn = {"turn_index": index, "speaker": speaker, "text": text, "language": lang,
                "eou_delay_ms": None, "llm_ttft_ms": None, "tts_ttfb_ms": None, "total_response_ms": None,
                "interrupted": bool(getattr(msg, "interrupted", False))}

        if role == "user":
            self.last_user_metrics = m
        else:
            # latency of this reply: end of customer speech -> first audio (LiveKit fills these in)
            turn["eou_delay_ms"] = ms(self.last_user_metrics.get("end_of_turn_delay"))
            turn["llm_ttft_ms"] = ms(m.get("llm_node_ttft"))
            turn["tts_ttfb_ms"] = ms(m.get("tts_node_ttfb"))
            turn["total_response_ms"] = ms(m.get("e2e_latency"))
            item["interrupted"] = turn["interrupted"]
            new_tools = self.state.tool_log[self.tools_seen:]
            if new_tools:
                item["tools"] = [t["name"] for t in new_tools]
                self.tools_seen = len(self.state.tool_log)
            if turn["total_response_ms"]:
                log.info("LATENCY | total=%sms | end-of-turn=%sms llm_first_token=%sms tts_first_audio=%sms",
                         turn["total_response_ms"], turn["eou_delay_ms"], turn["llm_ttft_ms"], turn["tts_ttfb_ms"])

        self.transcript.append(item)
        self.turns.append(turn)

    # ---------------------------------------------------------------- end
    async def finish(self, session_usage=None, outcome=None, ended_by=None, has_audio=True):
        if self.finished or not self.state.call_id:
            return
        self.finished = True
        s = self.state
        ended_by = ended_by or s.ended_by or "customer"
        customer_spoke = any(t["speaker"] == "customer" for t in self.turns)
        outcome = outcome or ("completed" if customer_spoke else "no_answer")

        totals = cost.usage_totals(session_usage)
        if has_audio and not totals["stt_seconds"]:
            # Sarvam streaming STT bills every second of audio we stream, i.e. the whole call
            totals["stt_seconds"] = round(time.time() - (self.answered or self.started), 1) if self.answered else 0

        try:
            saved = await asyncio.to_thread(self._save, totals, outcome, ended_by)
            if not saved:
                log.info("Call %s was already closed (declined); nothing to save", s.call_id)
                return
            log.info("Call %s saved | outcome=%s ended_by=%s | %d turns, %d tool calls",
                     s.call_id, outcome, ended_by, len(self.turns), len(s.tool_log))
        except Exception:
            log.exception("could not save call %s", s.call_id)
            return

        if outcome == "completed":
            await asyncio.to_thread(queue_postcall, s.call_id)

    def _save(self, totals, outcome, ended_by):
        s = self.state
        with get_sync_conn() as conn:
            rates = calls_repo.pricing_rates(conn)
            saved = calls_repo.finish_call(conn, s.call_id, {
                "answered_at": datetime.fromtimestamp(self.answered, timezone.utc) if self.answered else None,
                "duration_sec": int(time.time() - (self.answered or self.started)) if self.answered else 0,
                "outcome": outcome,
                "ended_by": ended_by,
                "languages_used": sorted({t["language"] for t in self.turns if t["language"]}),
                "transcript": self.transcript,
                "live_answers": s.answers,
                **totals,
                "api_cost_inr": cost.call_cost_inr(totals, rates),
            })
            if not saved:       # already closed elsewhere (customer declined): keep that, change nothing
                return False
            if self.turns:
                calls_repo.insert_turns(conn, s.call_id, self.turns)
            if s.tool_log:
                calls_repo.insert_tool_calls(conn, s.call_id, s.tool_log)
            if self.job_id:
                job_status = {"completed": "completed", "no_answer": "no_answer", "error": "failed"}.get(outcome, "completed")
                calls_repo.set_job_status(conn, self.job_id, job_status)
        return True


def queue_postcall(call_id):
    """Ask Celery to run post-call processing (Milestone 7). If Redis isn't running, just log it."""
    try:
        from worker.celery_app import celery_app
        celery_app.send_task("worker.tasks.postcall", args=[call_id], queue="postcall",
                             retry=False, ignore_result=True)
        log.info("postcall queued for %s", call_id)
    except Exception as e:  # Redis down etc.: the call is saved anyway, post-call can be re-run later
        log.warning("could not queue postcall for %s (%s)", call_id, type(e).__name__)
