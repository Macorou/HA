"""Persistent acknowledgement journal; a reboot must not blindly retry commands."""

from dataclasses import asdict
from datetime import UTC, datetime

from .adapters import Command
from .controller import Pending


def dump_control(controller):
    return {
        "fault": controller.fault,
        "pending": {
            key: {"command": asdict(item.command), "since": item.since.isoformat()}
            for key, item in controller.pending.items()
        },
        "last_sent": {key: value.isoformat() for key, value in controller.last_sent.items()},
    }


def aware_time(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("missing_timezone")
    return parsed.astimezone(UTC)


def restore_control(controller, saved, entities):
    """Validate the journal; malformed saved data suspends, never enables commands."""
    if saved is None:
        return
    try:
        if not isinstance(saved, dict) or saved.get("fault") is not None and not isinstance(saved["fault"], str):
            raise ValueError("invalid_journal")
        pending = {}
        for key, item in saved.get("pending", {}).items():
            command = Command(**item["command"])
            if command.entity_id not in entities:
                continue
            if command.field == "hvac_mode" and not controller.tempo_state.get("confirmed"):
                # An interrupted mode transition is ambiguous, not proof that
                # SHM owns an observed off state after the restart.
                raise ValueError("unconfirmed_tempo_transition")
            if key != command.key:
                raise ValueError("invalid_command_key")
            pending[key] = Pending(command, aware_time(item["since"]))
        last_sent = {
            key: aware_time(value)
            for key, value in saved.get("last_sent", {}).items()
            if key.split(":", 1)[0] in entities
        }
        controller.pending = pending
        controller.last_sent = last_sent
        controller.fault = saved.get("fault")
    except (AttributeError, KeyError, TypeError, ValueError):
        controller.pending.clear()
        controller.last_sent.clear()
        controller.fault = "invalid_saved_control_state"
