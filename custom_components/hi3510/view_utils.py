"""Utility condivise per le HTTP views Hi3510."""

from __future__ import annotations

import ipaddress
import logging
import time
from pathlib import Path

from aiohttp import web

from homeassistant.core import HomeAssistant

from .const import (
    CACHE_DIR,
    CACHE_MAX_AGE_DAYS,
    CONF_ALLOWED_NETWORKS,
    CONF_CACHE_RETENTION_DAYS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_DEFAULT_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "::1/128",
        "fe80::/10",
    )
)


def get_allowed_networks(
    hass: HomeAssistant,
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Legge le reti ammesse dalle options di qualsiasi entry hi3510."""
    for entry_id, data in hass.data.get(DOMAIN, {}).items():
        if not isinstance(data, dict):
            continue
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.options.get(CONF_ALLOWED_NETWORKS):
            nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
            for n in entry.options[CONF_ALLOWED_NETWORKS].split(","):
                n = n.strip()
                if n:
                    try:
                        nets.append(ipaddress.ip_network(n, strict=False))
                    except ValueError:
                        pass
            nets.extend([
                ipaddress.ip_network("127.0.0.0/8"),
                ipaddress.ip_network("::1/128"),
            ])
            return tuple(nets)
    return _DEFAULT_NETWORKS


def is_local_request(request: web.Request, hass: HomeAssistant) -> bool:
    """Verifica che la richiesta arrivi da una rete ammessa."""
    peername = request.transport.get_extra_info("peername")
    if not peername:
        return False
    try:
        addr = ipaddress.ip_address(peername[0])
    except ValueError:
        return False
    return any(addr in net for net in get_allowed_networks(hass))


def get_cam_name(hass: HomeAssistant, entry_id: str) -> str:
    """Ottieni nome camera dal device registry."""
    from homeassistant.helpers import device_registry as dr

    data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not data or not isinstance(data, dict):
        return f"Camera {entry_id[:8]}"
    api = data["api"]
    cam_name = f"Hi3510 {api.host}"
    device_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_reg, entry_id):
        cam_name = device.name_by_user or device.name or cam_name
        break
    return cam_name


def cache_dir(hass: HomeAssistant) -> Path:
    """Ritorna il path della directory cache."""
    return Path(hass.config.path(CACHE_DIR))


def cleanup_cache(hass: HomeAssistant) -> int:
    """Elimina file cache più vecchi della retention configurata."""
    retention_days = CACHE_MAX_AGE_DAYS
    for entry_id, data in hass.data.get(DOMAIN, {}).items():
        if not isinstance(data, dict):
            continue
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and CONF_CACHE_RETENTION_DAYS in entry.options:
            retention_days = entry.options[CONF_CACHE_RETENTION_DAYS]
            break

    cd = cache_dir(hass)
    if not cd.exists():
        return 0

    max_age_secs = retention_days * 86400
    now = time.time()
    removed = 0

    for f in cd.iterdir():
        if f.is_file() and f.suffix == ".mp4":
            age = now - f.stat().st_mtime
            if age > max_age_secs:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass

    if removed:
        _LOGGER.info("Cache cleanup: rimossi %d file (>%d giorni)", removed, retention_days)
    return removed
