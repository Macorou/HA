"""Daily night window in Home Assistant's local wall-clock time."""

from datetime import datetime, time


def clock_time(value: str) -> time:
    """Accept a local time only, without offsets or fractional seconds."""
    try:
        parsed = time.fromisoformat(value)
    except (TypeError, ValueError) as err:
        raise ValueError("night_time_invalid") from err
    if parsed.tzinfo is not None or parsed.microsecond:
        raise ValueError("night_time_invalid")
    return parsed


def night_active(settings: dict, runtime: dict, now: datetime) -> bool:
    """Start inclusive, end exclusive; equal endpoints mean an empty window."""
    if not runtime.get("night_schedule_enabled", settings["night_schedule_enabled"]):
        return False
    start, end = (clock_time(settings[key]) for key in ("night_start", "night_end"))
    current = now.time().replace(tzinfo=None)
    if start < end:
        return start <= current < end
    if start > end:
        return current >= start or current < end
    return False
