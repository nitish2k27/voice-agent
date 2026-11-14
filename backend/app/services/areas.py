"""SERVICE: area name -> zone, from backend/data/areas.json.

Order: exact alias match → fuzzy match (ratio ≥ 85) → unknown.
Zone None in the data means "outside Karnataka" (not served).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

from rapidfuzz import fuzz, process

from app.core.config import settings

FUZZY_MIN = 85
_DROP_WORDS = {"road", "rd", "layout", "nagara", "city", "town", "area", "near", "bangalore", "bengaluru"}


@dataclass(frozen=True)
class AreaMatch:
    status: str            # "matched" | "outside_karnataka" | "unknown"
    name: str | None       # canonical area name
    zone: int | None
    score: float           # 100 for exact, fuzzy ratio otherwise


def normalise(text: str) -> str:
    t = re.sub(r"[^\w\s]", " ", text.lower())
    words = t.split()
    kept = [w for w in words if w not in _DROP_WORDS] or words   # "Bangalore" alone stays
    return " ".join(kept).strip()


@lru_cache
def _index() -> dict[str, tuple[str, int | None]]:
    """normalised alias -> (canonical name, zone)"""
    data = json.loads(settings.areas_path.read_text(encoding="utf-8"))
    idx: dict[str, tuple[str, int | None]] = {}
    for area in data["areas"]:
        for alias in [area["name"], *area.get("aliases", [])]:
            for key in {alias.lower().strip(), normalise(alias)}:
                if key:
                    idx.setdefault(key, (area["name"], area["zone"]))
    return idx


def _result(name: str, zone: int | None, score: float) -> AreaMatch:
    return AreaMatch("outside_karnataka" if zone is None else "matched", name, zone, score)


def lookup(area: str) -> AreaMatch:
    if not area or not area.strip():
        return AreaMatch("unknown", None, None, 0.0)
    idx = _index()
    for key in (area.lower().strip(), normalise(area)):
        if key in idx:
            return _result(*idx[key], 100.0)
    best = process.extractOne(normalise(area), idx.keys(), scorer=fuzz.ratio)
    if best and best[1] >= FUZZY_MIN:
        return _result(*idx[best[0]], float(best[1]))
    return AreaMatch("unknown", None, None, float(best[1]) if best else 0.0)
