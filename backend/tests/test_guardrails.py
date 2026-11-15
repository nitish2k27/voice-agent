# Milestone 4: guardrails with a fake session (no audio needed). Run: pytest tests/test_guardrails.py -v
import asyncio
from types import SimpleNamespace

from agent import guardrails
from agent.guardrails import Guardrails


class FakeSession:
    def __init__(self):
        self.replies = []
        self.shut_down = False
        self.handlers = {}

    def on(self, name, fn):
        self.handlers[name] = fn

    def generate_reply(self, instructions, **kwargs):
        self.replies.append(instructions)

    def shutdown(self, drain=True):
        self.shut_down = True


def state():
    return SimpleNamespace(ended_by=None)


def event(new_state):
    return SimpleNamespace(new_state=new_state)


def test_silence_asks_then_hangs_up_by_itself():
    # LiveKit sends "away" only once, so the hang-up must come from our own timer
    async def run():
        s, st = FakeSession(), state()
        g = Guardrails(s, st, max_call_seconds=999, silence_seconds=0.1)
        g.start()
        g.on_user_state(event("away"))
        assert "still there" in s.replies[0] and not s.shut_down      # asks first
        await asyncio.sleep(0.3)                                       # no second "away" event arrives
        assert st.ended_by == "silence" and s.shut_down               # ...but it still hangs up
        g.stop()
    asyncio.run(run())


def test_speaking_after_the_question_cancels_hang_up():
    async def run():
        s, st = FakeSession(), state()
        g = Guardrails(s, st, max_call_seconds=999, silence_seconds=0.1)
        g.start()
        g.on_user_state(event("away"))
        g.on_user_state(event("speaking"))                             # "yes, I'm here"
        await asyncio.sleep(0.3)
        assert not s.shut_down and st.ended_by is None
        g.stop()
    asyncio.run(run())


def test_max_length_wraps_up_then_ends(monkeypatch):
    monkeypatch.setattr(guardrails, "WRAP_UP_BEFORE", 0.05)
    async def run():
        s, st = FakeSession(), state()
        g = Guardrails(s, st, max_call_seconds=0.1, silence_seconds=20)
        g.start()
        await asyncio.sleep(0.3)
        assert "wrap up" in s.replies[0]
        assert st.ended_by == "max_duration" and s.shut_down
    asyncio.run(run())
