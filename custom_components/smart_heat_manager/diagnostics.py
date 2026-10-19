"""Privacy preserving diagnostics; no complete source attributes are exported."""

import hashlib


async def async_get_config_entry_diagnostics(hass, entry):
    data = entry.runtime_data.diagnostic_data()
    mapping = {}

    def anonymize(value):
        if isinstance(value, dict):
            return {
                anonymize(str(k)): anonymize(v)
                for k, v in value.items()
                if k not in ("name", "actuator_notes", "attributes")
            }
        if isinstance(value, list):
            return [anonymize(v) for v in value]
        if isinstance(value, str):
            # Redact every configured entity even inside fault and pending strings.
            for entity, replacement in mapping.items():
                value = value.replace(entity, replacement)
        return value

    cfg = entry.runtime_data.config
    entities = [v for k, v in cfg["settings"].items() if k.endswith("_entity") and v]
    for room in cfg["rooms"]:
        entities.extend([room["sensor"], *room["actuators"]])
    for entity in sorted(set(entities), key=len, reverse=True):
        mapping[entity] = "entity_" + hashlib.sha256(entity.encode()).hexdigest()[:10]
    return anonymize(data)
