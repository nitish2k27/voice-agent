# Milestone 4/5: the call logger really saves turns and tool calls (uses the database; rows are is_test).
# Run from backend/:  pytest tests/test_call_logger.py -v
# This test exists because a missing `return` once made every call skip its turns (2026-11-15).
import asyncio
from types import SimpleNamespace

from agent.call_logger import CallLogger
from agent.tools import CallState
from app.core.config import settings
from app.db.session import get_sync_conn


def msg(role, text):
    return SimpleNamespace(item=SimpleNamespace(role=role, text_content=text, metrics={}, interrupted=False))


def test_finished_call_has_turns_and_tool_calls():
    state = CallState(tenant_id=settings.TENANT_ID, call_type="inbound", direction="inbound", customer={},
                      pending_questions=[], config={}, is_test=True)

    async def run():
        logger = CallLogger(state, room_name="pytest")
        await logger.start()
        logger.mark_answered()
        logger.on_item(msg("assistant", "Namaskara! Which language are you comfortable with?"))
        logger.on_item(msg("user", "English please"))
        state.tool_log.append({"name": "switch_language", "args": {"language": "en-IN"}, "result": "ok",
                               "duration_ms": 1, "ok": True, "turn_index": 2})
        logger.on_item(msg("assistant", "Sure, how can I help?"))
        await logger.finish(None, has_audio=False)

    asyncio.run(run())
    with get_sync_conn() as conn:
        call = conn.execute("select outcome, jsonb_array_length(transcript) n from calls where id = %s", (state.call_id,)).fetchone()
        turns = conn.execute("select count(*) n from turns where call_id = %s", (state.call_id,)).fetchone()["n"]
        tools = conn.execute("select count(*) n from tool_calls where call_id = %s", (state.call_id,)).fetchone()["n"]
        conn.execute("delete from calls where id = %s", (state.call_id,))   # cleanup (turns/tool_calls cascade)
    assert call["outcome"] == "completed" and call["n"] == 3
    assert turns == 3
    assert tools == 1
