"""Independent hysteresis using only the external room temperature."""

from .models import RoomDecision


def regulate(
    room: dict, temperature: float | None, target: float, previous: bool, enabled: bool = True
) -> RoomDecision:
    target = max(room["frost"], min(35.0, target))
    if temperature is None:
        return RoomDecision(None, target, False, 0, "sensor_unavailable")
    frost = temperature < room["frost"]
    if not enabled and not frost:
        return RoomDecision(temperature, target, False, 0, "disabled")
    demand = frost or (
        temperature < target + room["hysteresis"] if previous else temperature <= target - room["hysteresis"]
    )
    opening = min(100.0, max(10.0, (target - temperature + room["hysteresis"]) * room["gain"])) if demand else 0.0
    return RoomDecision(
        temperature, target, demand, round(opening), "frost" if frost else "demand" if demand else "satisfied", frost
    )
