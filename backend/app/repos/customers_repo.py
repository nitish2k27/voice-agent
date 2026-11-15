# REPO: customers and their current call job (for the customer call page /c/:token). Only SQL here.


def get_by_token(conn, token):
    return conn.execute(
        "select id::text, tenant_id::text, name, phone, language from customers where token = %s", (token,)
    ).fetchone()


def latest_job(conn, customer_id):
    """The customer's most recent call job (ringing / in_call / no_answer ...)."""
    return conn.execute(
        """select id::text, status, room_name, ring_started_at, attempts
           from call_jobs where customer_id = %s order by updated_at desc limit 1""",
        (customer_id,),
    ).fetchone()


def upsert_customer(conn, tenant_id, external_id, name, phone, language, is_test=False):
    """Insert or update a customer by (tenant, phone). Returns id and token."""
    return conn.execute(
        """insert into customers (tenant_id, external_id, name, phone, language, is_test)
           values (%s, %s, %s, %s, %s, %s)
           on conflict (tenant_id, phone) do update set name = excluded.name, language = excluded.language
           returning id::text, token""",
        (tenant_id, external_id, name, phone, language, is_test),
    ).fetchone()


def create_ringing_job(conn, tenant_id, customer_id, customer_row, room_name, is_test=False):
    """A call job that is ringing right now (Milestone 6's dial_call does this for real campaigns)."""
    from psycopg.types.json import Json
    return conn.execute(
        """insert into call_jobs (tenant_id, customer_id, customer, status, attempts, room_name, ring_started_at, is_test)
           values (%s, %s, %s, 'ringing', 1, %s, now(), %s) returning id::text""",
        (tenant_id, customer_id, Json(customer_row), room_name, is_test),
    ).fetchone()["id"]


def set_job_status(conn, job_id, status, only_if=None):
    """Change a job's status. only_if = the status it must have now (so a late click can't undo a timeout)."""
    if only_if:
        cur = conn.execute("update call_jobs set status = %s where id = %s and status = %s", (status, job_id, only_if))
    else:
        cur = conn.execute("update call_jobs set status = %s where id = %s", (status, job_id))
    return cur.rowcount == 1
