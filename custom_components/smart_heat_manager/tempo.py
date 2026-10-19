"""Tempo rules on an aware datetime in Home Assistant's local timezone."""

import unicodedata
from datetime import datetime


def color(raw: str | None) -> str:
    text = unicodedata.normalize("NFKD", raw or "").encode("ascii", "ignore").decode().lower()
    for result, names in {"red": ("red", "rouge"), "white": ("white", "blanc"), "blue": ("blue", "bleu")}.items():
        if any(name in text for name in names):
            return result
    return "unknown"


def restricted(today: str, now: datetime, unknown_blocks: bool) -> bool:
    return 6 <= now.hour < 22 and (today == "red" or (today == "unknown" and unknown_blocks))


def preheat(today: str, tomorrow: str, now: datetime, start: int) -> bool:
    # A calendar-day entity has already changed after midnight.
    return start <= now.hour < 6 and today == "red" or now.hour >= 22 and tomorrow == "red" and start >= 22
