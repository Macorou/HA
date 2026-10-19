"""Signed energy accounting and time based surplus qualification."""

from datetime import UTC, datetime

from .models import Snapshot


def surplus(snapshot: Snapshot, settings: dict) -> tuple[float | None, float | None]:
    if snapshot.grid is not None:
        net = snapshot.grid if settings["grid_export_positive"] else -snapshot.grid
    elif snapshot.production is not None and snapshot.house is not None:
        net = snapshot.production - snapshot.house
        if not settings["house_includes_pump"]:
            if snapshot.pump_power is None:
                return None, None
            net -= max(0, snapshot.pump_power)
    else:
        return None, None
    budget = net
    if snapshot.pump_on and snapshot.pump_power is not None:
        budget += max(0, snapshot.pump_power)
    return net, budget - settings["solar_margin"]


class Solar:
    def __init__(self) -> None:
        self.active = False
        self.high_since: datetime | None = None
        self.low_since: datetime | None = None
        self.started: datetime | None = None

    def update(self, budget: float | None, now: datetime, enabled: bool, cfg: dict) -> bool:
        now = now.astimezone(UTC)
        if not enabled or budget is None:
            self.active = False
            self.high_since = self.low_since = self.started = None
            return False
        if not self.active:
            if budget >= cfg["solar_start"] + cfg["solar_hysteresis"]:
                if self.high_since is None:
                    self.high_since = now
                if (now - self.high_since).total_seconds() >= cfg["solar_delay"]:
                    self.active, self.started = True, now
            else:
                self.high_since = None
        else:
            if budget < cfg["solar_hold"] - cfg["solar_hysteresis"]:
                if self.low_since is None:
                    self.low_since = now
                if (
                    (now - self.low_since).total_seconds() >= cfg["solar_stop_delay"]
                    and self.started is not None
                    and (now - self.started).total_seconds() >= cfg["solar_min_on"]
                ):
                    self.active = False
                    self.high_since = self.low_since = self.started = None
            else:
                self.low_since = None
        return self.active
