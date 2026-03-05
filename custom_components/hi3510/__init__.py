"""Integrazione Home Assistant per IP Camera Hi3510."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import Hi3510ApiClient, Hi3510AuthError, Hi3510ConnectionError
from .const import CONF_RTSP_PORT, DOMAIN, PLATFORMS
from .coordinator import Hi3510DataCoordinator, Hi3510MotionCoordinator

_LOGGER = logging.getLogger(__name__)

type Hi3510ConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: Hi3510ConfigEntry) -> bool:
    """Setup integrazione da config entry."""
    session = async_get_clientsession(hass)

    api = Hi3510ApiClient(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        session=session,
    )

    # Verifica connessione
    try:
        await api.get_server_info()
    except Hi3510AuthError as err:
        raise ConfigEntryAuthFailed from err
    except Hi3510ConnectionError as err:
        raise ConfigEntryNotReady from err

    # Crea coordinators
    main_coordinator = Hi3510DataCoordinator(hass, api, entry)
    motion_coordinator = Hi3510MotionCoordinator(hass, api, entry)

    # Primo refresh
    await main_coordinator.async_config_entry_first_refresh()
    await motion_coordinator.async_config_entry_first_refresh()

    # Salva in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": main_coordinator,
        "motion_coordinator": motion_coordinator,
    }

    # Forward platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: Hi3510ConfigEntry) -> bool:
    """Unload integrazione."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
