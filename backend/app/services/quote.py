# Price calculator. The LLM never does price maths: it calls this.
# All numbers and rules come from backend/data/amrith_sagar_pricing.json ("quote_rules").

import json
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

from app.core.config import settings
from app.services import areas


@lru_cache
def load_pricing():
    return json.loads(settings.pricing_path.read_text(encoding="utf-8"))


def package_codes():
    return [p["code"] for p in load_pricing()["packages"]]


def add_on_codes():
    return [a["code"] for a in load_pricing()["add_ons"]]


def custom_item_names():
    return list(load_pricing()["custom_menu"]["items_per_plate"].keys())


def rupees(x):
    # whole rupees, .5 rounds up (Python's round() would round 0.5 to even)
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def find_package(code):
    for p in load_pricing()["packages"]:
        if p["code"] == code:
            return p
    return None


def find_add_on(code):
    for a in load_pricing()["add_ons"]:
        if a["code"] == code:
            return a
    return None


def find_zone(zone_number):
    for z in load_pricing()["zones"]:
        if z["zone"] == zone_number:
            return z
    return None


def volume_discount_percent(paying_guests):
    for slab in load_pricing()["volume_discounts"]:
        top = slab["max_guests"] or 10**9
        if slab["min_guests"] <= paying_guests <= top:
            return slab["discount_percent"]
    return 0


def custom_menu_plate_price(custom_items, errors):
    """custom_items = [{"item": "starter", "diet": "veg", "count": 2}, ...] -> price per plate"""
    menu = load_pricing()["custom_menu"]
    price = menu["base_service_charge_per_plate"]
    dishes = 0
    for it in custom_items:
        name, diet, count = it.get("item"), it.get("diet", "veg"), int(it.get("count", 1))
        prices = menu["items_per_plate"].get(name)
        if prices is None:
            errors.append(f"unknown custom menu item '{name}'")
            continue
        if diet not in prices:
            errors.append(f"'{name}' is not available as {diet}")
            continue
        price += prices[diet] * count
        dishes += count
    if dishes < menu["min_dishes"]:
        errors.append(f"a custom menu needs at least {menu['min_dishes']} dishes (got {dishes})")
    return price, menu["min_guests"]


def calculate_quote(package_code=None, adults=0, children_5_12=0, zone=None, area=None,
                    add_ons=None, custom_items=None, event_date=None):
    """Returns a dict with line items, subtotal (excluding GST) and any errors/notes.

    add_ons      = [{"code": "LIVE-CHAAT"}, {"code": "EXTRA-SERVER", "qty": 2}, ...]
    custom_items = [{"item": "starter", "diet": "veg", "count": 2}, ...]  (instead of a package)
    Give either zone (1-4) or area (we look the zone up).
    """
    pricing = load_pricing()
    errors, notes, lines = [], [], []
    add_ons = add_ons or []

    # ---- zone ----
    area_name = None
    if zone is None and area:
        match = areas.lookup(area)
        if match.status == "outside_karnataka":
            errors.append(f"{match.name} is outside Karnataka; we only cater within Karnataka")
        elif match.status == "unknown":
            errors.append(f"could not find the area '{area}'; ask the customer for the town or locality again")
        else:
            zone, area_name = match.zone, match.name
    if zone is None and not errors:
        zone = 1  # no area given: assume Bengaluru city
        notes.append("no area given, assumed Bengaluru city (zone 1)")

    # ---- guests ----
    paying = int(adults) + int(children_5_12)
    if paying <= 0:
        errors.append("number of guests must be more than 0")
    if paying > pricing["policies"]["max_guests_per_event"]:
        errors.append(f"we can serve at most {pricing['policies']['max_guests_per_event']} guests at one event")
    if paying > 1000:
        notes.append("above 1,000 guests: our team should confirm, schedule a callback")

    # ---- food price per plate ----
    plate, min_guests, food_name = 0, 0, ""
    if package_code:
        pkg = find_package(package_code)
        if pkg is None:
            errors.append(f"unknown package code '{package_code}'")
        else:
            plate, min_guests, food_name = pkg["price_per_plate"], pkg["min_guests"], pkg["name"]
    elif custom_items:
        plate, min_guests = custom_menu_plate_price(custom_items, errors)
        food_name = "Custom menu"
    else:
        errors.append("give a package code or a custom menu")

    if min_guests and paying < min_guests:
        errors.append(f"{food_name} needs at least {min_guests} guests (got {paying})")

    zone_info = find_zone(zone) if zone else None
    if zone_info and zone_info.get("min_guests") and paying < zone_info["min_guests"]:
        errors.append(f"events in {zone_info['name']} need at least {zone_info['min_guests']} guests")

    # ---- food total (children 5-12 pay 60%) ----
    child_rate = pricing["children"]["discounted_rate_percent_of_plate"]
    child_plate = rupees(plate * child_rate / 100)
    food_total = adults * plate + children_5_12 * child_plate
    if plate:
        lines.append({"item": f"{food_name}: {adults} adults x Rs {plate}", "amount": adults * plate})
        if children_5_12:
            lines.append({"item": f"Children 5-12: {children_5_12} x Rs {child_plate} ({child_rate}%)",
                          "amount": children_5_12 * child_plate})

    # ---- volume discount (food only) ----
    pct = volume_discount_percent(paying)
    discount = rupees(food_total * pct / 100)
    if discount:
        lines.append({"item": f"Volume discount {pct}% on food", "amount": -discount})

    # ---- add-ons ----
    add_ons_total = 0
    for a in add_ons:
        code = a.get("code")
        if code and code.startswith("BAR-SETUP"):
            # pick the bar tier from the guest count
            if paying <= 200:
                code = "BAR-SETUP-200"
            elif paying <= 500:
                code = "BAR-SETUP-500"
            else:
                errors.append("bar setup above 500 guests is quoted by our team")
                continue
        info = find_add_on(code)
        if info is None:
            errors.append(f"unknown add-on '{code}'")
            continue
        if info["unit"] in ("per_plate", "per_guest"):
            qty = paying
        elif info["unit"] == "per_event":
            qty = 1
        else:  # per_server, per_box, per_hour: the customer must say how many
            qty = int(a.get("qty") or 0)
            if qty <= 0:
                errors.append(f"how many for '{info['name']}'? ({info['unit']})")
                continue
        amount = qty * info["price"]
        add_ons_total += amount
        lines.append({"item": f"{info['name']}: {qty} x Rs {info['price']}", "amount": amount})

    # ---- travel ----
    travel = 0
    if zone_info:
        if zone_info["travel_charge"] is None:
            travel = None
            notes.append("travel for this area is quoted by our team; schedule a callback")
        elif zone_info.get("travel_charge_above_500_guests") is not None and paying > 500:
            travel = zone_info["travel_charge_above_500_guests"]
        else:
            travel = zone_info["travel_charge"]
        if travel:
            lines.append({"item": f"Travel ({zone_info['name']})", "amount": travel})

    # ---- event year ----
    if event_date and str(event_date)[:4].isdigit() and int(str(event_date)[:4]) > pricing["valid_for_event_year"]:
        notes.append("prices may be revised for 2027 bookings")

    subtotal = food_total - discount + add_ons_total + (travel or 0)
    advance = rupees(subtotal * pricing["policies"]["advance_percent"] / 100)

    return {
        "ok": not errors,
        "zone": zone,
        "area": area_name,
        "paying_guests": paying,
        "line_items": lines,
        "food_total": food_total,
        "discount": discount,
        "add_ons_total": add_ons_total,
        "travel": travel,
        "subtotal": subtotal if not errors else None,
        "advance_40_percent": advance if not errors else None,
        "gst_note": "plus GST at the current rate",
        "notes": notes,
        "errors": errors,
    }


def quote_for_llm(result):
    """Short English text the voice agent can read and speak from."""
    if not result["ok"]:
        return "Cannot quote yet: " + "; ".join(result["errors"])
    parts = [f"{li['item']} = Rs {li['amount']}" for li in result["line_items"]]
    text = "; ".join(parts) + f". SUBTOTAL Rs {result['subtotal']}. GST is NOT included: always say 'plus GST'."
    if result["notes"]:
        text += " Notes: " + "; ".join(result["notes"])
    return text
