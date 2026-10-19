"""Debounced occupancy; unavailable presence never becomes absence."""

from datetime import UTC, datetime


class Presence:
    def __init__(self) -> None:
        self.mode = "present"
        self.candidate: str | None = None
        self.since: datetime | None = None

    def update(self, raw: str | None, now: datetime, delay: float) -> str:
        now = now.astimezone(UTC)
        if raw is None or raw in ("unknown", "unavailable"):
            self.candidate = None
            self.since = None
            return self.mode
        candidate = "present" if raw.lower() in ("on", "home", "true", "present") else "absent"
        if candidate != self.candidate:
            self.candidate, self.since = candidate, now
        if self.since is not None and (now - self.since).total_seconds() >= delay:
            self.mode = candidate
        return self.mode
