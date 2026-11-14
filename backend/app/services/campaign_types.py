"""SERVICE: call types from backend/data/campaign_types.json (questions, prompt block, fields, sheet columns)."""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from app.core.config import settings

CALL_TYPES = ("post_event_feedback", "enquiry_followup", "pre_event_confirmation", "inbound")


@lru_cache
def _load() -> dict[str, Any]:
    return json.loads(settings.campaign_types_path.read_text(encoding="utf-8"))


def get_type(call_type: str) -> dict[str, Any]:
    types = _load()["types"]
    if call_type not in types:
        raise KeyError(f"unknown call type: {call_type}")
    return types[call_type]


def questions(call_type: str) -> list[dict[str, str]]:
    return list(get_type(call_type)["questions"])


def question_keys(call_type: str) -> list[str]:
    return [q["key"] for q in questions(call_type)]


def call_type_block(call_type: str) -> str:
    return get_type(call_type)["call_type_block"]


def extraction_fields(call_type: str) -> dict[str, str]:
    return dict(get_type(call_type)["extraction_fields"])


def sheet_columns(call_type: str) -> list[str]:
    return list(get_type(call_type)["sheet_columns"])


def owner_summary_fields() -> dict[str, str]:
    return dict(_load()["common"]["owner_summary_fields"])
