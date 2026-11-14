# REPO: bookings, blocked dates, callbacks. Only SQL here, no business rules.
# Sync psycopg (the agent calls these through asyncio.to_thread, Celery calls them directly).


def plates_booked_on(conn, tenant_id, event_date):
    """Guests already booked that day: confirmed + tentative holds that haven't expired. Test rows don't count."""
    row = conn.execute(
        """
        select coalesce(sum(guests), 0) as plates
        from bookings
        where tenant_id = %s and event_date = %s and not is_test
          and (status = 'confirmed' or (status = 'tentative' and hold_until > now()))
        """,
        (tenant_id, event_date),
    ).fetchone()
    return int(row["plates"])


def is_blocked(conn, tenant_id, event_date):
    row = conn.execute(
        "select reason from blocked_dates where tenant_id = %s and date = %s", (tenant_id, event_date)
    ).fetchone()
    if row is None:
        return None
    return row["reason"] or "blocked by the business"


def lock_date(conn, tenant_id, event_date):
    """Stops two calls from booking the last plates of the same day at the same moment (lasts until commit)."""
    conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"{tenant_id}:{event_date}",))


def insert_booking(conn, b):
    row = conn.execute(
        """
        insert into bookings (tenant_id, call_id, customer_id, customer_name, phone, event_type, event_date,
                              venue_area, zone, guests, package_code, notes, quote_amount, advance_amount,
                              status, hold_until, is_test)
        values (%(tenant_id)s, %(call_id)s, %(customer_id)s, %(customer_name)s, %(phone)s, %(event_type)s,
                %(event_date)s, %(venue_area)s, %(zone)s, %(guests)s, %(package_code)s, %(notes)s,
                %(quote_amount)s, %(advance_amount)s, 'tentative', now() + interval '48 hours', %(is_test)s)
        returning id::text, hold_until
        """,
        b,
    ).fetchone()
    return row


def insert_callback(conn, c):
    row = conn.execute(
        """
        insert into callbacks (tenant_id, call_id, customer_id, customer_name, phone, reason, preferred_time, is_test)
        values (%(tenant_id)s, %(call_id)s, %(customer_id)s, %(customer_name)s, %(phone)s, %(reason)s,
                %(preferred_time)s, %(is_test)s)
        returning id::text
        """,
        c,
    ).fetchone()
    return row["id"]
