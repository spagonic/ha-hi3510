"""Config flow per Hi3510 IP Camera con discovery automatica."""

from __future__ import annotations

import asyncio
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

SCAN_OPTION = "scan"
MANUAL_OPTION = "manual"

MANUAL_SCHEMA = vol.Schema(
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
        osd_name = ""
        try:
            osd = await api.get_overlay_attr(1)
            osd_name = osd.get("name_1", "")
        except Exception:
            pass
        return info, mac, osd_name
    finally:
        await session.close()


async def _probe_host(
    session: aiohttp.ClientSession, host: str, port: int = 80
) -> dict[str, str] | None:
    """Prova a contattare un host Hi3510. Ritorna info dict o None.

    Identificazione sicura:
    - 200 con formato "var key=value;" → Hi3510 confermata
    - 401 con WWW-Authenticate realm contenente "hi3510" → Hi3510 confermata
    - Qualsiasi altra risposta → scartata
    """
    url = f"http://{host}:{port}/cgi-bin/hi3510/param.cgi?cmd=getserverinfo"
    timeout = aiohttp.ClientTimeout(total=2)
    try:
        async with session.get(url, timeout=timeout) as resp:
            if resp.status == 200:
                text = await resp.text()
                if "var " not in text:
                    return None
                result = Hi3510ApiClient.parse_response(text)
                result["host"] = host
                result["port"] = str(port)
                return result

            if resp.status != 401:
                return None

            # 401 — verifica che il realm contenga "hi3510"
            www_auth = resp.headers.get("WWW-Authenticate", "")
            if "hi3510" not in www_auth.lower():
                return None

            return {"host": host, "port": str(port), "auth_required": "1"}
    except Exception:
        return None



async def _scan_network(hass: Any) -> list[dict[str, str]]:
    """Scansiona la rete locale per cam Hi3510 sulla porta 80."""
    from homeassistant.components.network import async_get_adapters

    adapters = await async_get_adapters(hass)
    subnets: list[str] = []
    for adapter in adapters:
        for ip_info in adapter.get("ipv4", []):
            addr = ip_info.get("address", "")
            if addr and not addr.startswith("127.") and not addr.startswith("172."):
                subnets.append(addr)

    if not subnets:
        return []

    found: list[dict[str, str]] = []
    session = aiohttp.ClientSession()
    try:
        for subnet_ip in subnets:
            prefix = ".".join(subnet_ip.split(".")[:3])
            for batch_start in range(1, 255, 50):
                batch_end = min(batch_start + 50, 255)
                tasks = [
                    _probe_host(session, f"{prefix}.{i}")
                    for i in range(batch_start, batch_end)
                ]
                results = await asyncio.gather(*tasks)
                for r in results:
                    if r is not None:
                        found.append(r)
    finally:
        await session.close()

    return found


def _make_title(info: dict[str, str], osd_name: str, host: str) -> str:
    """Genera titolo per la config entry."""
    title = (
        osd_name
        or info.get("name", "")
        or info.get("model", "")
        or f"Hi3510 {host}"
    )
    if title == "IPCAM":
        title = info.get("model", f"Hi3510 {host}")
    return title


class Hi3510ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow per Hi3510 con discovery automatica."""

    VERSION = 1

    # Cache scan a livello di classe — persiste tra istanze diverse del flow
    _scan_cache: dict[str, dict[str, str]] = {}

    def __init__(self) -> None:
        self._selected_host: str = ""
        self._selected_port: int = DEFAULT_PORT

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: scegli scan o manuale."""
        if user_input is not None:
            choice = user_input.get("method", MANUAL_OPTION)
            if choice == SCAN_OPTION:
                return await self.async_step_scan()
            return await self.async_step_manual()

        schema = vol.Schema(
            {
                vol.Required("method", default=MANUAL_OPTION): vol.In(
                    {
                        MANUAL_OPTION: "✏️ Manual entry",
                        SCAN_OPTION: "🔍 Scan network",
                    }
                )
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_scan(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step scan: mostra cam trovate (scansiona solo la prima volta)."""
        if user_input is not None:
            selected = user_input.get("selected_camera", "")
            if selected == "_rescan_":
                # Forza nuovo scan
                Hi3510ConfigFlow._scan_cache.clear()
                return await self.async_step_scan()
            cam = Hi3510ConfigFlow._scan_cache.get(selected)
            if cam:
                self._selected_host = cam["host"]
                self._selected_port = int(cam.get("port", DEFAULT_PORT))
                return await self.async_step_credentials()
            return await self.async_step_manual()

        # Scan solo se il cache di classe è vuoto
        if not Hi3510ConfigFlow._scan_cache:
            _LOGGER.debug("Avvio scan rete per cam Hi3510...")
            cameras = await _scan_network(self.hass)

            for cam in cameras:
                host = cam["host"]
                name = cam.get("name", "")
                model = cam.get("model", "")
                label = host
                if name and name != "IPCAM":
                    label = f"{name} ({host})"
                elif model:
                    label = f"{model} ({host})"
                key = f"{host}:{cam.get('port', '80')}"
                Hi3510ConfigFlow._scan_cache[key] = cam
                Hi3510ConfigFlow._scan_cache[key]["_label"] = label

        # Filtra cam già configurate dal cache
        configured_macs: set[str] = set()
        configured_hosts: set[str] = set()
        for entry in self._async_current_entries():
            if entry.unique_id:
                configured_macs.add(entry.unique_id)
            configured_hosts.add(entry.data.get(CONF_HOST, ""))

        options: dict[str, str] = {}
        for key, cam in Hi3510ConfigFlow._scan_cache.items():
            host = cam["host"]
            mac = cam.get("macaddress", "").replace(":", "").lower()
            if mac and mac in configured_macs:
                continue
            if host in configured_hosts:
                continue
            options[key] = cam.get("_label", key)

        # Aggiungi opzione rescan in fondo
        options["_rescan_"] = "🔄 Rescan network"

        if not options:
            # Nessuna cam trovata, vai a manuale
            return self.async_show_form(
                step_id="no_cameras",
                data_schema=vol.Schema({}),
            )

        schema = vol.Schema(
            {vol.Required("selected_camera"): vol.In(options)}
        )

        return self.async_show_form(
            step_id="scan",
            data_schema=schema,
            description_placeholders={"count": str(len(options))},
        )

    async def async_step_no_cameras(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Nessuna camera trovata, redirect a manuale."""
        return await self.async_step_manual()

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step credenziali per camera scoperta."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {
                CONF_HOST: self._selected_host,
                CONF_PORT: self._selected_port,
                CONF_USERNAME: user_input[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
                CONF_RTSP_PORT: user_input.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT),
            }
            try:
                info, mac, osd_name = await _validate_connection(self.hass, data)
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
                title = _make_title(info, osd_name, self._selected_host)
                return self.async_create_entry(title=title, data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_RTSP_PORT, default=DEFAULT_RTSP_PORT): int,
            }
        )

        return self.async_show_form(
            step_id="credentials",
            data_schema=schema,
            errors=errors,
            description_placeholders={"host": self._selected_host},
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step inserimento manuale."""
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
                title = _make_title(info, osd_name, user_input[CONF_HOST])
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="manual",
            data_schema=MANUAL_SCHEMA,
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
