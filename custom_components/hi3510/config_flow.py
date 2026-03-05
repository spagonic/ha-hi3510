"""Config flow per Hi3510 IP Camera."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .api import Hi3510ApiClient, Hi3510AuthError, Hi3510CommandError, Hi3510ConnectionError
from .const import CONF_RTSP_PORT, DEFAULT_PORT, DEFAULT_RTSP_PORT, DEFAULT_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_RTSP_PORT, default=DEFAULT_RTSP_PORT): int,
    }
)


async def _validate_connection(
    hass: Any, data: dict[str, Any]
) -> tuple[dict[str, str], str, str]:
    """Valida connessione alla camera. Ritorna (info, mac, osd_name)."""
    session = aiohttp.ClientSession()
    try:
        api = Hi3510ApiClient(
            host=data[CONF_HOST],
            port=data[CONF_PORT],
            username=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
            session=session,
        )
        info = await api.get_server_info()
        net = await api.get_net_attr()
        mac = net.get("macaddress", "").replace(":", "").lower()
        if not mac:
            mac = f"{data[CONF_HOST]}_{data[CONF_PORT]}"
        # Ricava nome cam dall'OSD region 1 (nome personalizzato)
        osd_name = ""
        try:
            osd = await api.get_overlay_attr(1)
            osd_name = osd.get("name_1", "")
        except Exception:
            pass
        return info, mac, osd_name
    finally:
        await session.close()


class Hi3510ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow per Hi3510."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info, mac, osd_name = await _validate_connection(self.hass, user_input)
            except Hi3510AuthError:
                errors["base"] = "invalid_auth"
            except Hi3510ConnectionError:
                errors["base"] = "cannot_connect"
            except Hi3510CommandError:
                errors["base"] = "not_hi3510"
            except Exception:
                _LOGGER.exception("Errore inatteso nel config flow")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()

                # Titolo: OSD name region 1 > server name > model > host
                title = (
                    osd_name
                    or info.get("name", "")
                    or info.get("model", "")
                    or f"Hi3510 {user_input[CONF_HOST]}"
                )
                if title == "IPCAM":
                    title = info.get("model", f"Hi3510 {user_input[CONF_HOST]}")
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=USER_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> Hi3510OptionsFlow:
        return Hi3510OptionsFlow(config_entry)


class Hi3510OptionsFlow(OptionsFlow):
    """Options flow per modificare configurazione."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await _validate_connection(self.hass, user_input)
            except Hi3510AuthError:
                errors["base"] = "invalid_auth"
            except Hi3510ConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(
                    self._config_entry, data=user_input
                )
                await self.hass.config_entries.async_reload(
                    self._config_entry.entry_id
                )
                return self.async_create_entry(title="", data={})

        current = self._config_entry.data
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=current.get(CONF_HOST, "")): str,
                vol.Required(CONF_PORT, default=current.get(CONF_PORT, DEFAULT_PORT)): int,
                vol.Required(CONF_USERNAME, default=current.get(CONF_USERNAME, DEFAULT_USERNAME)): str,
                vol.Required(CONF_PASSWORD, default=current.get(CONF_PASSWORD, "")): str,
                vol.Required(CONF_RTSP_PORT, default=current.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT)): int,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
