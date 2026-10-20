"""Tempo rules on an aware datetime in Home Assistant's local timezone."""

import unicodedata
from datetime import UTC, datetime

from .models import active_override


def color(raw: str | None) -> str:
    text = unicodedata.normalize("NFKD", raw or "").encode("ascii", "ignore").decode().lower()
    for result, names in {"red": ("red", "rouge"), "white": ("white", "blanc"), "blue": ("blue", "bleu")}.items():
        if any(name in text for name in names):
            return result
    return "unknown"


def restricted(today: str, now: datetime, unknown_blocks: bool) -> bool:
    return 6 <= now.hour < 22 and (today == "red" or (today == "unknown" and unknown_blocks))


def red_window_end(today: str, now: datetime, enabled: bool = True) -> str | None:
    if enabled and today == "red" and restricted(today, now, False):
        return now.replace(hour=22, minute=0, second=0, microsecond=0).astimezone(UTC).isoformat()
    return None


def pump_stop_required(cfg: dict, now: datetime, today: str, runtime: dict) -> bool:
    overrides = runtime.get("overrides", {})
    bypass = active_override(overrides, "tempo_bypass", now) or active_override(overrides, "force", now)
    return bool(red_window_end(today, now, cfg["tempo_enabled"]) and not bypass)


def preheat(today: str, tomorrow: str, now: datetime, start: int) -> bool:
    # A calendar-day entity has already changed after midnight.
    return start <= now.hour < 6 and today == "red" or now.hour >= 22 and tomorrow == "red" and start >= 22
