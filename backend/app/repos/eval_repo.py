# REPO: simulated test-suite runs (eval_runs, eval_results).
from psycopg.types.json import Json


def start_run(conn, tenant_id, prompt_version, live_llm, sim_llm, judge_llm, search_mode, personas_count):
    row = conn.execute(
        """insert into eval_runs (tenant_id, prompt_version, live_llm, sim_llm, judge_llm, search_mode, personas_count)
           values (%s, %s, %s, %s, %s, %s, %s) returning id::text""",
        (tenant_id, prompt_version, live_llm, sim_llm, judge_llm, search_mode, personas_count),
    ).fetchone()
    return row["id"]


def save_result(conn, run_id, persona_id, persona_name, turns, transcript, tool_log, passed, why):
    conn.execute(
        """insert into eval_results (run_id, persona_id, persona_name, turns, transcript, tool_log,
                                     judge_scores, expected_check_passed)
           values (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (run_id, persona_id, persona_name, turns, Json(transcript), Json(tool_log), Json({"check": why}), passed),
    )


def finish_run(conn, run_id):
    conn.execute("update eval_runs set finished_at = now() where id = %s", (run_id,))
