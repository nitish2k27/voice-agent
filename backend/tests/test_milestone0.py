"""Milestone 0 smoke tests: config, data loaders, area lookup (no network)."""
from app.core.config import settings
from app.services import areas, campaign_types


def test_settings_paths_exist() -> None:
    assert settings.pricing_path.exists()
    assert settings.areas_path.exists()
    assert settings.campaign_types_path.exists()
    assert settings.EMBED_DIM == 384


def test_campaign_types_load() -> None:
    assert len(campaign_types.questions("post_event_feedback")) == 8
    assert "food_rating" in campaign_types.question_keys("post_event_feedback")
    assert campaign_types.questions("inbound") == []
    assert "headline" in campaign_types.owner_summary_fields()


def test_area_exact_and_alias() -> None:
    assert areas.lookup("Jayanagar").zone == 1
    assert areas.lookup("Mysore").name == "Mysuru"
    assert areas.lookup("ಮೈಸೂರು").zone == 3
    assert areas.lookup("Devanahalli").zone == 2
    assert areas.lookup("Hubli").zone == 4


def test_area_fuzzy_and_unknown() -> None:
    assert areas.lookup("Koramangla").name == "Koramangala"      # STT typo
    assert areas.lookup("Chennai").status == "outside_karnataka"
    assert areas.lookup("Xyzpur").status == "unknown"
    assert areas.lookup("").status == "unknown"
