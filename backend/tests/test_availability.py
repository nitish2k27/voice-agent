# Availability rules that don't need the database (they return before any query).
# Run from backend/:  pytest tests/test_availability.py -v
from datetime import date

from app.services.availability import check_availability

TENANT = "00000000-0000-0000-0000-000000000001"
TODAY = date(2026, 11, 15)


def test_too_soon_city():
    r = check_availability(TENANT, "2026-11-22", 200, "Jayanagar", today=TODAY)   # 7 days away
    assert not r["available"] and r["reason"] == "too_soon" and r["min_notice_days"] == 15


def test_zone3_needs_20_days():
    r = check_availability(TENANT, "2026-12-02", 200, "Mysuru", today=TODAY)      # 17 days away
    assert r["reason"] == "too_soon" and r["min_notice_days"] == 20


def test_zone3_minimum_guests():
    r = check_availability(TENANT, "2026-12-20", 100, "Tumkur", today=TODAY)
    assert r["reason"] == "below_zone_minimum"


def test_bad_date_unknown_area_outside():
    assert check_availability(TENANT, "20th Dec", 100, "Jayanagar", today=TODAY)["reason"] == "bad_date"
    assert check_availability(TENANT, "2026-12-20", 100, "Xyzpur", today=TODAY)["reason"] == "unknown_area"
    assert check_availability(TENANT, "2026-12-20", 300, "Chennai", today=TODAY)["reason"] == "outside_karnataka"


def test_past_date_suggests_next_year():
    r = check_availability(TENANT, "2026-10-15", 600, "Mysuru", today=TODAY)
    assert r["reason"] == "past_date" and "2027-10-15" in r["message"]


def test_too_many_guests():
    assert check_availability(TENANT, "2027-01-20", 3500, "Jayanagar", today=TODAY)["reason"] == "too_many_guests"
