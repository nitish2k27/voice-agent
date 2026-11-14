# Milestone 2: quote tests. Run from backend/:  pytest tests/test_quote.py -v
from app.services.quote import calculate_quote


def test_1_doc_example_600_bale_mysuru():
    q = calculate_quote("SI-BALE", adults=600, zone=3)
    assert q["ok"]
    assert q["food_total"] == 390000
    assert q["discount"] == 19500
    assert q["travel"] == 5000
    assert q["subtotal"] == 375500


def test_1b_same_by_area_name():
    q = calculate_quote("SI-BALE", adults=600, area="Mysore")
    assert q["zone"] == 3 and q["subtotal"] == 375500


def test_2_exactly_500_gets_discount_but_normal_travel():
    q = calculate_quote("SI-CLASSIC", adults=500, zone=3)
    assert q["discount"] == 10000          # 5% of 2,00,000
    assert q["travel"] == 8000             # "above 500" means 501+
    assert q["subtotal"] == 200000 - 10000 + 8000


def test_3_501_guests_cheaper_travel():
    q = calculate_quote("SI-CLASSIC", adults=501, zone=3)
    assert q["travel"] == 5000


def test_4_1000_guests_8_percent():
    q = calculate_quote("NI-VEG", adults=1000, zone=1)
    assert q["discount"] == 44000          # 8% of 5,50,000
    assert q["subtotal"] == 506000
    assert any("callback" in n for n in q["notes"]) is False   # exactly 1000 is not "above 1000"


def test_5_children_and_add_on():
    q = calculate_quote("NI-VEG", adults=100, children_5_12=20, zone=1, add_ons=[{"code": "LIVE-CHAAT"}])
    assert q["food_total"] == 100 * 550 + 20 * 330     # children pay 60%
    assert q["add_ons_total"] == 120 * 70              # add-on on all paying guests, full price
    assert q["subtotal"] == 61600 + 8400


def test_6_japanese_below_minimum():
    q = calculate_quote("JP-CLASSIC", adults=25, zone=1)
    assert not q["ok"]
    assert "at least 30" in q["errors"][0]


def test_7_zone3_needs_150():
    q = calculate_quote("SI-CLASSIC", adults=120, zone=3)
    assert not q["ok"]
    assert any("150" in e for e in q["errors"])


def test_8_zone4_travel_by_team():
    q = calculate_quote("SI-CLASSIC", adults=200, zone=4)
    assert q["ok"]
    assert q["travel"] is None
    assert any("quoted by our team" in n for n in q["notes"])


def test_9_custom_menu_minimum_dishes():
    five = [{"item": "starter", "diet": "veg", "count": 2}, {"item": "main_course_curry", "diet": "veg", "count": 3}]
    q = calculate_quote(custom_items=five, adults=100, zone=1)
    assert not q["ok"]
    six = five + [{"item": "indian_sweet", "diet": "veg", "count": 1}]
    q = calculate_quote(custom_items=six, adults=100, zone=1)
    assert q["ok"]
    # 120 base + 2x60 + 3x60 + 40 = 460 per plate
    assert q["subtotal"] == 100 * 460


def test_10_bar_setup_tiers():
    q = calculate_quote("NI-NV", adults=250, zone=1, add_ons=[{"code": "BAR-SETUP-200"}])
    assert q["add_ons_total"] == 40000       # 250 guests -> the up-to-500 tier
    q = calculate_quote("NI-NV", adults=600, zone=1, add_ons=[{"code": "BAR-SETUP-500"}])
    assert not q["ok"]


def test_11_2027_note():
    q = calculate_quote("SI-BALE", adults=900, zone=1, event_date="2027-01-25")
    assert any("2027" in n for n in q["notes"])


def test_unknown_area_and_outside_karnataka():
    assert not calculate_quote("SI-CLASSIC", adults=100, area="Xyzpur")["ok"]
    assert "outside Karnataka" in calculate_quote("SI-CLASSIC", adults=100, area="Chennai")["errors"][0]


def test_per_quantity_add_on_needs_qty():
    q = calculate_quote("SI-CLASSIC", adults=100, zone=1, add_ons=[{"code": "EXTRA-SERVER"}])
    assert not q["ok"]
    q = calculate_quote("SI-CLASSIC", adults=100, zone=1, add_ons=[{"code": "EXTRA-SERVER", "qty": 2}])
    assert q["add_ons_total"] == 2400
