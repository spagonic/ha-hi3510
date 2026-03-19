"""Diagnostica per Hi3510 IP Camera."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import DOMAIN

REDACT_KEYS = {CONF_PASSWORD, CONF_USERNAME, "password", "username"}


def _redact(data: dict[str, Any]) -> dict[str, Any]:
    """Rimuove dati sensibili."""
    return {
        k: "**REDACTED**" if k in REDACT_KEYS else v
        for k, v in data.items()
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Ritorna dati diagnostici per il config entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not data or not isinstance(data, dict):
        return {"error": "Integration data not available"}

    coordinator = data["coordinator"]
    motion = data["motion_coordinator"]

    result: dict[str, Any] = {
        "entry": {
            "data": _redact(dict(entry.data)),
            "options": dict(entry.options),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "data": coordinator.data,
        },
        "motion_coordinator": {
            "last_update_success": motion.last_update_success,
            "data": motion.data,
        },
    }

    # Sanitizza password da server_info se presente
    if coordinator.data and "server_info" in coordinator.data:
        info = dict(coordinator.data["server_info"])
        result["coordinator"]["data"] = dict(coordinator.data)
        result["coordinator"]["data"]["server_info"] = _redact(info)

    return result
