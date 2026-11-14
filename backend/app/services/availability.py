# Can we take an event on this date? Rules from docs/api_contracts.md -> Availability rules.

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.db.session import get_sync_conn
from app.repos import bookings_repo
from app.services import areas
from app.services.quote import load_pricing


def today_india():
    return datetime.now(ZoneInfo(settings.TIMEZONE)).date()


def parse_date(text):
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def check_availability(tenant_id, event_date, guests, area, conn=None, today=None):
    """Returns {"available": bool, "reason": str, "message": str, "zone": int|None, ...}"""
    policies = load_pricing()["policies"]
    today = today or today_india()
    guests = int(guests)

    def answer(available, reason, message, zone=None, area_name=None, notice=None):
        return {"available": available, "reason": reason, "message": message,
                "zone": zone, "area_matched": area_name, "min_notice_days": notice}

    day = parse_date(event_date)
    if day is None:
        return answer(False, "bad_date", f"'{event_date}' is not a valid date; ask the customer for the date again")

    if day < today:
        return answer(False, "past_date", f"{day.isoformat()} has already passed. If the customer meant next year, "
                      f"check {day.replace(year=day.year + 1).isoformat()} instead.")

    match = areas.lookup(area)
    if match.status == "unknown":
        return answer(False, "unknown_area", f"could not find the area '{area}'; ask the customer for the town or locality again")
    if match.status == "outside_karnataka":
        return answer(False, "outside_karnataka", f"{match.name} is outside Karnataka; we cater only within Karnataka. Offer a callback.",
                      area_name=match.name)

    zone = match.zone
    notice = 20 if zone in (3, 4) else policies["min_booking_notice_days"]

    if day < today + timedelta(days=notice):
        return answer(False, "too_soon",
                      f"we need at least {notice} days notice for {match.name}; {day.isoformat()} is too soon. "
                      "Offer a callback so the owner can check.", zone, match.name, notice)
    if guests > policies["max_guests_per_event"]:
        return answer(False, "too_many_guests", f"we serve at most {policies['max_guests_per_event']} guests at one event",
                      zone, match.name, notice)
    if zone in (3, 4) and guests < 150:
        return answer(False, "below_zone_minimum", f"events in {match.name} need at least 150 guests", zone, match.name, notice)

    # database checks (open a connection only if the caller didn't give one)
    if conn is None:
        with get_sync_conn() as new_conn:
            blocked, booked = date_status(new_conn, tenant_id, day)
    else:
        blocked, booked = date_status(conn, tenant_id, day)

    if blocked:
        return answer(False, "blocked", f"{day.isoformat()} is not available ({blocked})", zone, match.name, notice)
    if booked + guests > policies["max_plates_per_day"]:
        return answer(False, "fully_booked", f"{day.isoformat()} is fully booked for that many guests", zone, match.name, notice)

    return answer(True, "ok", f"{day.isoformat()} is available for {guests} guests in {match.name} (zone {zone}). "
                  "A booking stays tentative until the advance is paid.", zone, match.name, notice)


def date_status(conn, tenant_id, day):
    """(blocked reason or None, plates already booked that day)"""
    return bookings_repo.is_blocked(conn, tenant_id, day), bookings_repo.plates_booked_on(conn, tenant_id, day)


def availability_for_llm(result):
    return json.dumps({"available": result["available"], "message": result["message"]})
