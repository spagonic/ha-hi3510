"""Integrazione Home Assistant per IP Camera Hi3510."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import entity_registry as er

from .api import Hi3510ApiClient, Hi3510AuthError, Hi3510ConnectionError
from .const import CONF_PTZ_ENABLED, CONF_RTSP_PORT, DOMAIN, PLATFORMS, PTZ_ACTIONS, PTZ_MAX_PRESETS, PTZ_MAX_SPEED
from .coordinator import Hi3510DataCoordinator, Hi3510MotionCoordinator
from .sd_browser import Hi3510SdBrowserView, Hi3510SdCacheStatsView, Hi3510SdClearView, Hi3510SdDownloadView, Hi3510SdHubView, Hi3510SdIndexView, Hi3510SdMergeView, Hi3510SdMonthView
from .view_utils import cleanup_cache
from .views import Hi3510CacheBrowserView, Hi3510CacheFileView, Hi3510CacheHubView, Hi3510PlaybackView

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

    # Pulizia entità PTZ orfane (cam senza PTZ abilitato)
    ptz_enabled = entry.options.get(CONF_PTZ_ENABLED, False) or entry.data.get(CONF_PTZ_ENABLED, False)
    if not ptz_enabled:
        ent_reg = er.async_get(hass)
        ptz_keys = {"ptz_left", "ptz_right", "ptz_up", "ptz_down", "ptz_home",
                     "ptz_zoom_in", "ptz_zoom_out", "ptz_preset"}
        for key in ptz_keys:
            uid = f"{entry.unique_id}_{key}"
            entity_id = ent_reg.async_get_entity_id("button" if key != "ptz_preset" else "select", DOMAIN, uid)
            if entity_id:
                ent_reg.async_remove(entity_id)
                _LOGGER.debug("Rimossa entità PTZ orfana: %s", entity_id)

    # Registra HTTP view per playback SD (una sola volta)
    if not hass.data[DOMAIN].get("_view_registered"):
        hass.http.register_view(Hi3510PlaybackView(hass))
        hass.http.register_view(Hi3510CacheHubView(hass))
        hass.http.register_view(Hi3510CacheBrowserView(hass))
        hass.http.register_view(Hi3510CacheFileView(hass))
        hass.http.register_view(Hi3510SdHubView(hass))
        hass.http.register_view(Hi3510SdBrowserView(hass))
        hass.http.register_view(Hi3510SdIndexView(hass))
        hass.http.register_view(Hi3510SdMonthView(hass))
        hass.http.register_view(Hi3510SdCacheStatsView(hass))
        hass.http.register_view(Hi3510SdMergeView(hass))
        hass.http.register_view(Hi3510SdDownloadView(hass))
        hass.http.register_view(Hi3510SdClearView(hass))
        hass.data[DOMAIN]["_view_registered"] = True
        # Pulizia cache vecchia all'avvio
        await hass.async_add_executor_job(cleanup_cache, hass)

    # Registra servizi PTZ (una sola volta)
    if not hass.data[DOMAIN].get("_services_registered"):
        _register_services(hass)
        hass.data[DOMAIN]["_services_registered"] = True

    return True


def _register_services(hass: HomeAssistant) -> None:
    """Registra i servizi hi3510.ptz_move e hi3510.ptz_preset."""

    SERVICE_PTZ_MOVE = "ptz_move"
    SERVICE_PTZ_PRESET = "ptz_preset"

    PTZ_MOVE_SCHEMA = vol.Schema(
        {
            vol.Required("entry_id"): cv.string,
            vol.Required("action"): vol.In(PTZ_ACTIONS),
            vol.Optional("speed", default=1): vol.All(
                int, vol.Range(min=0, max=PTZ_MAX_SPEED)
            ),
        }
    )

    PTZ_PRESET_SCHEMA = vol.Schema(
        {
            vol.Required("entry_id"): cv.string,
            vol.Required("action"): vol.In(["go", "save"]),
            vol.Required("number"): vol.All(
                int, vol.Range(min=1, max=PTZ_MAX_PRESETS)
            ),
        }
    )

    async def handle_ptz_move(call: ServiceCall) -> None:
        """Gestisce il servizio ptz_move."""
        entry_id = call.data["entry_id"]
        data = hass.data.get(DOMAIN, {}).get(entry_id)
        if not data or not isinstance(data, dict):
            _LOGGER.error("Entry %s non trovata", entry_id)
            return
        api: Hi3510ApiClient = data["api"]
        await api.ptz_command(call.data["action"], call.data["speed"])

    async def handle_ptz_preset(call: ServiceCall) -> None:
        """Gestisce il servizio ptz_preset."""
        entry_id = call.data["entry_id"]
        data = hass.data.get(DOMAIN, {}).get(entry_id)
        if not data or not isinstance(data, dict):
            _LOGGER.error("Entry %s non trovata", entry_id)
            return
        api: Hi3510ApiClient = data["api"]
        number = call.data["number"]
        if call.data["action"] == "go":
            await api.ptz_preset_go(number)
        else:
            await api.ptz_preset_save(number)

    hass.services.async_register(DOMAIN, SERVICE_PTZ_MOVE, handle_ptz_move, PTZ_MOVE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_PTZ_PRESET, handle_ptz_preset, PTZ_PRESET_SCHEMA)


async def async_unload_entry(hass: HomeAssistant, entry: Hi3510ConfigEntry) -> bool:
    """Unload integrazione."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
