# REPO: calls, turns, tool_calls, call_jobs status, pricing rates. Only SQL here.
from psycopg.types.json import Json


def insert_call(conn, c):
    row = conn.execute(
        """
        insert into calls (tenant_id, job_id, customer_id, direction, call_type, room_name,
                           language_initial, prompt_version, started_at, is_test)
        values (%(tenant_id)s, %(job_id)s, %(customer_id)s, %(direction)s, %(call_type)s, %(room_name)s,
                %(language_initial)s, %(prompt_version)s, now(), %(is_test)s)
        returning id::text, started_at
        """,
        c,
    ).fetchone()
    return row


def finish_call(conn, call_id, f):
    """Returns True if the row was updated, False if the call was already closed (e.g. declined)."""
    return conn.execute(
        """
        update calls set
            answered_at = %(answered_at)s, ended_at = now(), duration_sec = %(duration_sec)s,
            outcome = %(outcome)s, ended_by = %(ended_by)s, languages_used = %(languages_used)s,
            transcript = %(transcript)s, live_answers = %(live_answers)s,
            stt_seconds = %(stt_seconds)s, tts_characters = %(tts_characters)s,
            llm_input_tokens = %(llm_input_tokens)s, llm_cached_tokens = %(llm_cached_tokens)s,
            llm_output_tokens = %(llm_output_tokens)s, api_cost_inr = %(api_cost_inr)s
        where id = %(call_id)s and ended_at is null
        """,
        {**f, "call_id": call_id, "transcript": Json(f["transcript"]), "live_answers": Json(f["live_answers"])},
    ).rowcount == 1   # False = already finished (e.g. marked declined by the backend): don't overwrite


def mark_declined(conn, job_id):
    """The customer pressed Decline: close the call row the agent opened for this job."""
    conn.execute(
        """update calls set outcome = 'declined', ended_by = 'customer', ended_at = now(), duration_sec = 0
           where job_id = %s and ended_at is null""",
        (job_id,),
    )


def insert_turns(conn, call_id, turns):
    with conn.cursor() as cur:
        cur.executemany(
            """insert into turns (call_id, turn_index, speaker, text, language, eou_delay_ms, llm_ttft_ms,
                                  tts_ttfb_ms, total_response_ms, interrupted)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [(call_id, t["turn_index"], t["speaker"], t["text"], t["language"], t["eou_delay_ms"],
              t["llm_ttft_ms"], t["tts_ttfb_ms"], t["total_response_ms"], t["interrupted"]) for t in turns],
        )


def insert_tool_calls(conn, call_id, tool_log):
    with conn.cursor() as cur:
        cur.executemany(
            """insert into tool_calls (call_id, turn_index, name, args, result, duration_ms, ok)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            [(call_id, t.get("turn_index"), t["name"], Json(t["args"]), Json({"text": str(t["result"])}),
              t["duration_ms"], t["ok"]) for t in tool_log],
        )


def set_job_status(conn, job_id, status, error=None):
    conn.execute("update call_jobs set status = %s, last_error = %s where id = %s", (status, error, job_id))


def pricing_rates(conn):
    """{"sarvam_stt": 0.49, ...} using the newest rate per provider."""
    rows = conn.execute(
        """select distinct on (provider) provider, rate_inr from pricing_rates
           where valid_from <= current_date order by provider, valid_from desc"""
    ).fetchall()
    return {r["provider"]: float(r["rate_inr"]) for r in rows}
