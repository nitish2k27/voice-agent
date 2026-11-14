# REPO: the active agent configuration of a business (persona, voices, fillers, rules, limits).


def get_active(conn, tenant_id):
    return conn.execute(
        """select persona_name, greeting_outbound, greeting_inbound, rules, voices, fillers, tools_enabled,
                  prompt_version, max_call_seconds, silence_timeout_seconds
           from agent_configs where tenant_id = %s and is_active limit 1""",
        (tenant_id,),
    ).fetchone()
