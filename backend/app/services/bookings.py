# Reservations (tentative bookings, held 48 h) and callback requests.
# Payment link + Google Calendar are added in Milestone 7.5.

from app.db.session import get_sync_conn
from app.repos import bookings_repo
from app.services import availability
from app.services.quote import calculate_quote, find_package


def create_reservation(tenant_id, customer_name, phone, event_type, event_date, venue_area, guests,
                       package_code=None, notes="", call_id=None, customer_id=None, is_test=False):
    """Re-checks availability and saves the booking in ONE transaction, so two calls can't overbook a day."""
    with get_sync_conn() as conn:
        with conn.transaction():
            bookings_repo.lock_date(conn, tenant_id, event_date)

            check = availability.check_availability(tenant_id, event_date, guests, venue_area, conn=conn)
            if not check["available"]:
                return {"ok": False, "message": "Not reserved: " + check["message"]}

            # price comes from the quote calculator, never from the LLM
            quote_amount, advance = None, None
            if package_code and find_package(package_code):
                q = calculate_quote(package_code, adults=guests, zone=check["zone"], event_date=event_date)
                if q["ok"]:
                    quote_amount, advance = q["subtotal"], q["advance_40_percent"]

            row = bookings_repo.insert_booking(conn, {
                "tenant_id": tenant_id, "call_id": call_id, "customer_id": customer_id,
                "customer_name": customer_name, "phone": phone, "event_type": event_type,
                "event_date": event_date, "venue_area": check["area_matched"], "zone": check["zone"],
                "guests": guests, "package_code": package_code, "notes": notes,
                "quote_amount": quote_amount, "advance_amount": advance, "is_test": is_test,
            })

    message = (f"Reserved {event_date} for {customer_name}, {guests} guests in {check['area_matched']}. "
               f"Booking id {row['id'][:8]}. It is held for 48 hours and is NOT confirmed yet. ")
    if advance:
        message += f"A payment link for the 40% advance of Rs {advance} will be sent to the customer's mobile; "
        message += "the booking is confirmed once it is paid."
    else:
        message += "Our team will share the advance amount and payment link."
    return {"ok": True, "booking_id": row["id"], "hold_until": row["hold_until"].isoformat(),
            "advance_amount": advance, "message": message}


def schedule_callback(tenant_id, reason, preferred_time=None, customer_name=None, phone=None,
                      call_id=None, customer_id=None, is_test=False):
    with get_sync_conn() as conn:
        callback_id = bookings_repo.insert_callback(conn, {
            "tenant_id": tenant_id, "call_id": call_id, "customer_id": customer_id,
            "customer_name": customer_name, "phone": phone, "reason": reason,
            "preferred_time": preferred_time, "is_test": is_test,
        })
    when = f" ({preferred_time})" if preferred_time else ""
    return {"ok": True, "callback_id": callback_id,
            "message": f"Callback request saved{when}. Our team will call the customer back."}
