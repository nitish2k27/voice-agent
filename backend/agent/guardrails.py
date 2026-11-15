# Call guardrails (Milestone 4): no call goes on forever and nobody waits in silence.
#
#   1. Outbound: wait at most WAIT_FOR_PARTICIPANT_SECONDS for the customer to join (done in agent.py).
#   2. Silence: LiveKit marks the customer "away" after user_away_timeout seconds of nobody talking.
#      First time -> "Are you still there?"   Second time in a row -> goodbye and hang up.
#   3. Max length: at max_call_seconds - 30 the agent wraps up; at max_call_seconds it says goodbye and hangs up.

import asyncio
import logging

log = logging.getLogger("amrutha.guardrails")

WRAP_UP_BEFORE = 30   # seconds before the max length


class Guardrails:
    def __init__(self, session, state, max_call_seconds, silence_seconds):
        self.session = session
        self.state = state
        self.max_call_seconds = max_call_seconds
        self.silence_seconds = silence_seconds
        self.timer = None            # max-length timer
        self.silence_timer = None    # runs after "are you still there?"

    def start(self):
        self.session.on("user_state_changed", self.on_user_state)
        self.timer = asyncio.create_task(self.max_length_timer())

    def stop(self):
        for t in (self.timer, self.silence_timer):
            if t:
                t.cancel()

    # ---------------------------------------------------------------- silence
    def on_user_state(self, event):
        if event.new_state == "speaking":
            # they're back: forget the silence
            if self.silence_timer:
                self.silence_timer.cancel()
                self.silence_timer = None
            return
        if event.new_state != "away" or self.silence_timer:
            return
        # LiveKit says "away" only ONCE per silence (voice test 2026-11-15), so we can't wait for a 2nd event:
        # ask now, then hang up ourselves if they still haven't spoken after another silence_seconds.
        log.info("customer silent for %ss: asking if they are still there", self.silence_seconds)
        self.session.generate_reply(instructions="The customer has been silent. In CURRENT LANGUAGE, "
                                                 "ask briefly and politely if they are still there.")
        self.silence_timer = asyncio.create_task(self.hang_up_if_still_silent())

    async def hang_up_if_still_silent(self):
        try:
            await asyncio.sleep(self.silence_seconds)
            log.info("customer still silent: ending the call")
            self.end_call("silence", "The customer is not responding. In CURRENT LANGUAGE, say a short polite "
                                     "goodbye and that our team will call back if needed.")
        except asyncio.CancelledError:
            pass

    # ---------------------------------------------------------------- max length
    async def max_length_timer(self):
        try:
            await asyncio.sleep(max(self.max_call_seconds - WRAP_UP_BEFORE, 0))
            log.info("call nearly at max length: wrapping up")
            self.session.generate_reply(instructions="The call time is almost over. In CURRENT LANGUAGE, politely "
                                                     "say you need to wrap up, and repeat any next step in one sentence.")
            await asyncio.sleep(WRAP_UP_BEFORE)
            log.info("max call length reached: ending the call")
            self.end_call("max_duration", "In CURRENT LANGUAGE, say a short polite goodbye.")
        except asyncio.CancelledError:
            pass

    # ---------------------------------------------------------------- helper
    def end_call(self, reason, goodbye_instructions):
        if self.state.ended_by:            # already ending
            return
        self.state.ended_by = reason
        self.session.generate_reply(instructions=goodbye_instructions, tool_choice="none")
        self.session.shutdown(drain=True)  # finish saying goodbye, then close
